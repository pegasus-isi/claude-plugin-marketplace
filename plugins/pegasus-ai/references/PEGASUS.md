# Pegasus Workflow Development Guide

A practical guide for creating [Pegasus WMS](https://pegasus.isi.edu/) workflows, based on lessons learned from the tnseq-workflow, orcasound-workflow, mag-workflow, earthquake-workflow, soilmoisture-workflow, and airquality-workflow projects in this repository.

## Core Concepts

A Pegasus workflow consists of five components:

| Component | Purpose |
|-----------|---------|
| **Properties** | Pegasus configuration (transfer threads, retry settings) |
| **Site Catalog** | Defines execution sites (local, condorpool, etc.) |
| **Transformation Catalog** | Registers executables (wrapper scripts) and containers |
| **Replica Catalog** | Registers input data files and their physical locations |
| **Workflow (DAG)** | Defines jobs, their I/O files, and dependencies |

## Project Structure

```
my-workflow/
├── workflow_generator.py       # Generates all Pegasus catalogs + DAG
├── bin/
│   ├── step1.py                # Python wrapper for each pipeline step
│   ├── step2.py
│   ├── helper_script.R         # Non-executable support files (R, shell, etc.)
│   └── tool.jar                # Binary dependencies
├── Docker/
│   └── My_Dockerfile           # Container with all required tools
├── data/
│   └── test/                   # Test input data
├── references/                 # Reference files (genomes, indices, etc.)
└── README.md
```

## Workflow Generator Template

```python
#!/usr/bin/env python3

import os
import sys
import glob
from pathlib import Path
from argparse import ArgumentParser
from Pegasus.api import *


class MyWorkflow:
    wf = None
    sc = None
    tc = None
    rc = None
    props = None

    dagfile = None
    wf_dir = None
    shared_scratch_dir = None
    local_storage_dir = None
    wf_name = "my_workflow"

    def __init__(self, dagfile="workflow.yml"):
        self.dagfile = dagfile
        self.wf_dir = str(Path(__file__).parent.resolve())
        self.shared_scratch_dir = os.path.join(self.wf_dir, "scratch")
        self.local_storage_dir = os.path.join(self.wf_dir, "output")

    def write(self):
        if self.sc is not None:
            self.sc.write()
        self.props.write()
        self.rc.write()
        self.tc.write()
        self.wf.write(file=self.dagfile)

    def create_pegasus_properties(self):
        self.props = Properties()
        self.props["pegasus.transfer.threads"] = "16"

    def create_sites_catalog(self, exec_site_name="condorpool"):
        self.sc = SiteCatalog()
        local = Site("local").add_directories(
            Directory(
                Directory.SHARED_SCRATCH, self.shared_scratch_dir
            ).add_file_servers(
                FileServer("file://" + self.shared_scratch_dir, Operation.ALL)
            ),
            Directory(
                Directory.LOCAL_STORAGE, self.local_storage_dir
            ).add_file_servers(
                FileServer("file://" + self.local_storage_dir, Operation.ALL)
            ),
        )
        exec_site = (
            Site(exec_site_name)
            .add_condor_profile(universe="vanilla")
            .add_pegasus_profile(style="condor")
        )
        self.sc.add_sites(local, exec_site)

    def create_transformation_catalog(self, exec_site_name="condorpool"):
        # See "Transformation Catalog" section below
        pass

    def create_replica_catalog(self):
        # See "Replica Catalog" section below
        pass

    def create_workflow(self):
        # See "Building the DAG" section below
        pass
```

## Transformation Catalog

The Transformation Catalog registers executables and their containers.

### Container Definition

```python
container = Container(
    "my_container",
    container_type=Container.SINGULARITY,    # SINGULARITY or DOCKER
    image="docker://username/image:latest",
    image_site="docker_hub",
)
```

### Transformation Registration

```python
self.tc = TransformationCatalog()

# Local-only transformation (runs on submit node)
mkdir = Transformation(
    "mkdir", site="local", pfn="/bin/mkdir", is_stageable=False
)

# Containerized transformation (runs on worker nodes)
my_step = Transformation(
    "my_step",
    site=exec_site_name,
    pfn=os.path.join(self.wf_dir, "bin/my_step.py"),
    is_stageable=True,
    container=container,
).add_pegasus_profile(memory="4 GB", cores=2)

self.tc.add_containers(container)
self.tc.add_transformations(mkdir, my_step)
```

### What Goes in the Transformation Catalog

- **Executables** that Pegasus invokes directly as job entry points (Python wrapper scripts)
- Each transformation maps a logical name to a physical script path

### What Does NOT Go in the Transformation Catalog

- Support files called by wrapper scripts (R scripts, JARs, config files)
- These go in the **Replica Catalog** as data dependencies instead

## Replica Catalog

The Replica Catalog registers input data files and their physical locations.

```python
self.rc = ReplicaCatalog()

# Reference files
self.rc.add_replica("local", "reference.fasta",
                    "file://" + os.path.abspath("references/reference.fasta"))

# Support scripts/tools called by wrappers (NOT transformations)
jar_path = os.path.join(self.wf_dir, "bin/tool.jar")
self.rc.add_replica("local", "tool.jar", "file://" + jar_path)

r_script = os.path.join(self.wf_dir, "bin/analysis.R")
self.rc.add_replica("local", "analysis.R", "file://" + r_script)

# Input data files
for sample in samples:
    path = os.path.join(data_dir, f"{sample}.fq.gz")
    self.rc.add_replica("local", f"{sample}.fq.gz",
                        "file://" + os.path.abspath(path))
```

### Key Rule: Executables vs Data Dependencies

| File Type | Catalog | Example |
|-----------|---------|---------|
| Wrapper script invoked by Pegasus | Transformation | `bin/align.py` |
| Script called by a wrapper | Replica | `bin/analysis.R` |
| Binary tool called by a wrapper | Replica | `bin/tool.jar` |
| Reference data | Replica | `references/genome.fasta` |
| Input data | Replica | `data/sample.fq.gz` |

## Building the DAG

### Automatic Dependency Inference

Use `infer_dependencies=True` to let Pegasus build the DAG from file I/O relationships:

```python
self.wf = Workflow(self.wf_name, infer_dependencies=True)
```

When enabled, Pegasus automatically creates edges between jobs that produce and consume the same `File` object. You only need explicit `add_dependency()` for ordering that isn't captured by file I/O (e.g., mkdir before first job).

### File Objects

Declare files that flow between jobs as `File` objects:

```python
ref_file = File("reference.fasta")    # Input from replica catalog
jar_file = File("tool.jar")           # Support file from replica catalog
output = File("results/output.txt")   # Produced by a job
```

### Job Definition

```python
input_file = File("input.fq.gz")
output_file = File("results/aligned.bam")

job = (
    Job("my_step", _id="step_sample1", node_label="step_sample1")
    .add_args(
        f"--input input.fq.gz "
        f"--output results/aligned.bam "
        f"--reference reference.fasta"
    )
    .add_inputs(input_file, ref_file)
    .add_outputs(output_file, stage_out=True, register_replica=False)
    .add_pegasus_profiles(label="sample1")
)
self.wf.add_jobs(job)
```

### stage_out and register_replica

| Parameter | Purpose |
|-----------|---------|
| `stage_out=True` | Copy file to `local_storage_dir` (final output) |
| `stage_out=False` | Keep file in scratch only (intermediate file) |
| `register_replica=False` | Don't register output in replica catalog (typical) |

Use `stage_out=True` only for files the user needs in the final output directory. Intermediate files that only flow between jobs should use `stage_out=False`.

### Explicit Dependencies

Only needed when file I/O doesn't capture the ordering:

```python
# mkdir must complete before jobs that write to those directories
self.wf.add_dependency(mkdir_job, children=[first_job])
```

## File Staging and Naming

### How Pegasus Stages Files Between Jobs

Each Pegasus job runs in its own working directory. Input files are staged IN, the job runs, and output files are staged OUT. Understanding this is critical:

1. **Input files** from the replica catalog or upstream jobs are copied into the job's working directory
2. **The wrapper script** reads inputs and writes outputs relative to the working directory
3. **Output files** matching declared `File` objects are picked up by Pegasus for downstream jobs or final output

### Hierarchical File Names (LFNs with paths)

File LFNs can contain directory separators for organized output:

```python
# Output will be staged to: output/read_counts/totalcounts_mid/sample.tab
tab_file = File("read_counts/totalcounts_mid/sample.totalcounts.tab")
```

The wrapper script must create the subdirectory and write to the matching path:

```python
# In the wrapper script
os.makedirs(os.path.dirname(args.output), exist_ok=True)
```

### Passing Files Between Jobs Explicitly

**Do NOT** rely on directory scanning (`list.files()`, `glob()`, `os.listdir()`) to discover files between jobs. Pegasus stages files individually and directory structure may not be preserved in the job's working directory.

**Instead**, pass file paths explicitly as arguments:

```python
# BAD - scanning a directory (may be empty in Pegasus working dir)
concat_job.add_args(f"--input-dir results/counts/")

# GOOD - explicit file paths
file_args = ' '.join([f"--input {f.lfn}" for f in tab_files])
concat_job.add_args(f"--output merged.tsv " + file_args)
```

In the wrapper script, accept repeated `--input` arguments:

```python
parser.add_argument("--input", action="append", required=True,
                    help="Input file (can be specified multiple times)")
```

### Common File Staging Pitfalls

| Pitfall | Problem | Solution |
|---------|---------|----------|
| Directory scanning in jobs | `list.files()` / `glob()` finds nothing | Pass explicit file paths as arguments |
| Relative script paths | `../bin/script.R` doesn't exist in working dir | Add scripts to Replica Catalog + job inputs |
| Hardcoded absolute paths | Paths don't exist on worker nodes | Use only filenames; let Pegasus stage files |
| Missing `os.makedirs()` | Subdirectories don't exist in working dir | Create dirs before writing in wrapper scripts |

## Parallel Execution

Pegasus automatically runs jobs in parallel when their dependencies allow it. Design your DAG to maximize parallelism:

### Per-Sample Parallelism

Process independent samples in parallel by creating separate jobs per sample:

```python
for sample in samples:
    clip_job = Job("clip", _id=f"clip_{sample}", ...)
    align_job = Job("align", _id=f"align_{sample}", ...)
    # Each sample's pipeline is independent → runs in parallel
```

### Branching Within a Sample

Create parallel branches by having multiple jobs consume the same output file:

```python
# rm_dupe produces marked_bam
# Both bam2bw and genomecov consume marked_bam → they run in parallel
bw_job.add_inputs(marked_bam)      # Branch 1
genomecov_job.add_inputs(marked_bam) # Branch 2 (parallel)
```

### Fan-Out / Fan-In

```python
# Fan-out: one input → multiple parallel jobs
for variant in variants:
    map_job = Job("map", _id=f"map_{variant}_{sample}", ...)
    map_job.add_inputs(count_file)  # Same input, different params

# Fan-in: multiple parallel jobs → one aggregation job
concat_job.add_inputs(*all_tab_files)  # Waits for all tab jobs
```

### Job Labels for Clustering

Use labels to hint that jobs should run on the same node (reduces data transfer):

```python
job.add_pegasus_profiles(label=sample)
```

### Visualizing the DAG

After generating the workflow:

```bash
# Pegasus can generate a DOT graph of the DAG
pegasus-plan --submit -s condorpool -o local workflow.yml
pegasus-status <run-dir>
```

## Writing Wrapper Scripts

Each pipeline step needs a Python wrapper script in `bin/`. The wrapper:
1. Parses arguments with `argparse`
2. Creates any needed output directories
3. Runs the underlying tool via `subprocess`
4. Exits with the tool's return code

### Template

```python
#!/usr/bin/env python3

"""Description of what this step does."""

import argparse
import os
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description="Step description")
    parser.add_argument("--input", required=True, help="Input file")
    parser.add_argument("--output", required=True, help="Output file")
    parser.add_argument("--threads", type=int, default=1, help="Number of threads")
    args = parser.parse_args()

    # Create output directory if needed
    out_dir = os.path.dirname(args.output)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    # Run the underlying tool
    cmd = f"mytool --input {args.input} --output {args.output} --threads {args.threads}"

    print(f"Running: {cmd}")
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    print(result.stdout)
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        sys.exit(result.returncode)

    print(f"Output: {args.output}")


if __name__ == "__main__":
    main()
```

### Wrapper Script Rules

1. **Arguments must match** what the workflow generator passes in `add_args()`
2. **Use `os.getcwd()`** to find support files (R scripts, JARs) staged by Pegasus — not paths relative to the script
3. **Create subdirectories** with `os.makedirs(exist_ok=True)` before writing output
4. **Use `action="append"`** for arguments that accept multiple files (e.g., QC jobs, concat jobs)
5. **Propagate exit codes** — Pegasus uses the return code to detect failures
6. **Print the command** being run for debugging failed jobs

### Finding Support Files

Support files (R scripts, JARs) added to the Replica Catalog and declared as job inputs are staged into the job's working directory:

```python
# GOOD - Pegasus stages the file to the working directory
script_path = os.path.join(os.getcwd(), "analysis.R")

# BAD - the wrapper script is staged separately, __file__ path is wrong
script_path = os.path.join(os.path.dirname(__file__), "analysis.R")
```

## Docker Container

### Dockerfile Template

```dockerfile
FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && \
    apt-get install -y \
        python3 python3-pip \
        tool1 tool2 tool3 \
    && rm -rf /var/lib/apt/lists/*

# Install tools not available via apt
RUN pip3 install --no-cache-dir some-python-tool==1.2.3

# Ensure python3 is available as python
RUN ln -sf /usr/bin/python3 /usr/bin/python
```

### Container Considerations

- Include **all tools** needed by all wrapper scripts (the same container is shared)
- Pin versions for reproducibility
- Use language runtimes compatible with your support scripts (e.g., R >= 4.2 if using `|>` pipe syntax, or rewrite scripts for base R compatibility)
- Test the container locally before deploying:
  ```bash
  docker build -t username/image:latest -f Docker/My_Dockerfile .
  docker run --rm -it username/image:latest bash
  ```

## Converting Snakemake to Pegasus

### Mapping Snakemake Concepts to Pegasus

| Snakemake | Pegasus |
|-----------|---------|
| `rule` | `Transformation` + `Job` |
| `input:` | `job.add_inputs(File(...))` |
| `output:` | `job.add_outputs(File(...))` |
| `shell:` | Wrapper script in `bin/` |
| `config.yaml` | CLI arguments to `workflow_generator.py` |
| `{wildcards}` | Loop variables in Python |
| `expand(...)` | Python list comprehension |
| Conda `environment.yaml` | `Dockerfile` |
| `threads:` | `.add_pegasus_profile(cores=N)` |
| `resources: mem_mb=` | `.add_pegasus_profile(memory="N GB")` |

### Conversion Steps

1. **Identify all rules** and their input/output relationships
2. **Create a wrapper script** for each rule (or group of similar rules)
3. **Build a Dockerfile** with all tools from the Conda environment
4. **Map wildcards to loops** — Snakemake `{sample}` wildcards become Python `for sample in samples:` loops
5. **Register all input files** in the Replica Catalog (reference files, input data, support scripts)
6. **Define transformations** for each wrapper script
7. **Build the DAG** with jobs, ensuring file I/O captures all dependencies
8. **Use `infer_dependencies=True`** instead of manually specifying rule ordering

### Common Conversion Pitfalls

- **Snakemake rules that call scripts directly** (e.g., `Rscript {input.script}`) need the script registered as a Replica Catalog entry and added as a job input
- **Snakemake `params.data_dir`** patterns that scan directories must be rewritten to pass explicit file lists
- **Shell pipes** (`cmd1 | cmd2 > output`) work inside wrapper scripts via `subprocess.run(cmd, shell=True)`
- **Snakemake's `rule all`** has no Pegasus equivalent — Pegasus runs all jobs in the DAG

## Running and Debugging

### Workflow Lifecycle

```bash
# 1. Generate workflow
./workflow_generator.py [options] --output workflow.yml

# 2. Plan and submit
pegasus-plan --submit -s condorpool -o local workflow.yml

# 3. Monitor
pegasus-status <run-directory>

# 4. Debug failures
pegasus-analyzer <run-directory>

# 5. Get statistics
pegasus-statistics <run-directory>
```

### Debugging Failed Jobs

1. Check `pegasus-analyzer` output for the failed job
2. Look at the job's `.out` and `.err` files in the run directory
3. The wrapper script's `print(f"Running: {cmd}")` shows the exact command
4. Check `stdout` and `stderr` captured by the wrapper
5. Common failures:
   - Missing input files → check Replica Catalog entries
   - "No such file or directory" for support scripts → add to Replica Catalog + job inputs
   - Out of memory → increase `memory` in Transformation profile
   - Container pull failures → verify Docker image name and network access

## Reference: Complete Pegasus Python API

```python
from Pegasus.api import *

# Properties
props = Properties()
props["pegasus.transfer.threads"] = "16"

# Site Catalog
sc = SiteCatalog()
site = Site("condorpool").add_condor_profile(universe="vanilla")
sc.add_sites(site)

# Container
container = Container("name", Container.SINGULARITY, "docker://img:tag", "docker_hub")

# Transformation Catalog
tc = TransformationCatalog()
tx = Transformation("name", site="condorpool", pfn="/path/to/script.py",
                    is_stageable=True, container=container)
tx.add_pegasus_profile(memory="4 GB", cores=2)
tc.add_containers(container)
tc.add_transformations(tx)

# Replica Catalog
rc = ReplicaCatalog()
rc.add_replica("local", "logical_name", "file:///absolute/path")

# Workflow
wf = Workflow("name", infer_dependencies=True)

# Files
input_f = File("input.txt")
output_f = File("output.txt")

# Job
job = (Job("transformation_name", _id="unique_id", node_label="label")
       .add_args("--input input.txt --output output.txt")
       .add_inputs(input_f)
       .add_outputs(output_f, stage_out=True, register_replica=False)
       .add_pegasus_profiles(label="group"))
wf.add_jobs(job)

# Explicit dependency (only when file I/O doesn't capture ordering)
wf.add_dependency(parent_job, children=[child_job])

# Write all catalogs
props.write()
sc.write()
tc.write()
rc.write()
wf.write(file="workflow.yml")
```

## Advanced Patterns

The following patterns were distilled from real workflows in this repository: mag-workflow, earthquake-workflow, soilmoisture-workflow, and airquality-workflow.

### Shell Wrapper Scripts (Alternative to Python)

For bioinformatics tools that produce nested output directories, shell wrappers can normalize outputs for Pegasus staging. The mag-workflow uses this pattern:

```bash
#!/bin/bash
# megahit.sh — wrapper that flattens nested tool output

# Parse arguments to extract output directory and sample name
OUTPUT_DIR=""
SAMPLE=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        -o|--out-dir) OUTPUT_DIR="$2"; shift 2 ;;
        --sample) SAMPLE="$2"; shift 2 ;;
        *) ARGS+=("$1"); shift ;;
    esac
done

# Run the tool (creates nested output structure)
megahit "${ARGS[@]}" -o "$OUTPUT_DIR"

# Copy expected output to flat location for Pegasus stage-out
cp "${OUTPUT_DIR}/final.contigs.fa" "${SAMPLE}_contigs.fa"
```

This solves the problem of tools that create deeply nested output directories — the wrapper copies the relevant files to the working directory root where Pegasus expects them.

**When to use shell vs Python wrappers:**

| Situation | Use |
|-----------|-----|
| Tool produces nested directories that need flattening | Shell wrapper |
| Tool requires headless/display handling | Shell wrapper |
| Multiple arguments need parsing + validation | Python wrapper |
| Tool called via subprocess with complex logic | Python wrapper |
| Scripts already embedded in container | Shell wrapper |

### Container-Embedded Scripts (`is_stageable=False`)

When wrapper scripts are baked into the container image (e.g., installed at `/usr/local/bin/`), use `is_stageable=False` so Pegasus doesn't try to transfer them from the submit host:

```python
# Scripts are INSIDE the container — don't stage from submit host
tx = Transformation(
    "megahit",
    site="local",
    pfn="/usr/local/bin/megahit.sh",  # Path inside container
    is_stageable=False,               # Already in container
    container=my_container,
)
```

Compare with the stageable pattern (scripts on submit host, transferred to workers):

```python
# Scripts are on submit host — Pegasus stages them to workers
tx = Transformation(
    "my_step",
    site=exec_site_name,
    pfn=os.path.join(self.wf_dir, "bin/my_step.py"),  # Path on submit host
    is_stageable=True,                                  # Transfer to workers
    container=my_container,
)
```

**Dockerfile for embedded scripts:**

```dockerfile
COPY bin/*.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/*.sh
```

### Per-Tool Resource Configuration

Define memory and CPU requirements per tool in a configuration dictionary, then apply during transformation registration:

```python
TOOL_CONFIGS = {
    "fastqc":   {"memory": "2 GB",  "cores": 2},
    "fastp":    {"memory": "4 GB",  "cores": 4},
    "megahit":  {"memory": "16 GB", "cores": 8},
    "quast":    {"memory": "8 GB",  "cores": 4},
    "gtdbtk":   {"memory": "64 GB", "cores": 8},   # Taxonomy is expensive
    "train":    {"memory": "4 GB",  "cores": 2},    # ML training
    "predict":  {"memory": "2 GB",  "cores": 1},    # ML inference
}

# Apply during transformation catalog creation
for tool_name, config in TOOL_CONFIGS.items():
    tx = Transformation(tool_name, site=exec_site_name, ...)
    tx.add_pegasus_profile(
        memory=config["memory"],
        cores=config.get("cores", 1),
    )
```

This centralizes resource tuning and makes it easy to adjust without hunting through job definitions.

### Conditional DAG Construction

Use CLI flags to build different DAG topologies from the same generator. This avoids maintaining separate workflow files:

```python
parser.add_argument("--skip-fastqc", action="store_true")
parser.add_argument("--skip-binning", action="store_true")
parser.add_argument("--skip-taxonomy", action="store_true")
parser.add_argument("--skip-forecast", action="store_true")

# In create_workflow():
if not args.skip_fastqc:
    fastqc_job = Job("fastqc", ...)
    self.wf.add_jobs(fastqc_job)

if not args.skip_binning:
    binning_job = Job("metabat2", ...)
    self.wf.add_jobs(binning_job)

    if not args.skip_taxonomy:
        taxonomy_job = Job("gtdbtk", ...)  # 64 GB RAM
        self.wf.add_jobs(taxonomy_job)
```

Benefits:
- Test workflows faster by skipping expensive steps
- Adapt to data source limitations (e.g., skip ML when training data unavailable)
- Same codebase serves both quick validation and full production runs

### Built-in Test Mode

Include a `--test` flag that auto-downloads sample data, eliminating setup friction for new users:

```python
parser.add_argument("--test", action="store_true",
                    help="Download test data and run with minimal settings")

def download_test_data(self):
    """Download small test dataset for validation."""
    test_dir = os.path.join(self.wf_dir, "data", "test")
    os.makedirs(test_dir, exist_ok=True)

    test_files = {
        "sample1_R1.fastq.gz": "https://example.com/test/sample1_R1.fastq.gz",
        "sample1_R2.fastq.gz": "https://example.com/test/sample1_R2.fastq.gz",
    }
    for name, url in test_files.items():
        path = os.path.join(test_dir, name)
        if not os.path.exists(path):
            urllib.request.urlretrieve(url, path)

    # Return sample list for workflow generation
    return [{"id": "sample1", "fastq_1": ..., "fastq_2": ...}]

# In main():
if args.test:
    samples = workflow.download_test_data()
elif args.samplesheet:
    samples = parse_samplesheet(args.samplesheet)
else:
    print("Error: Either --test or --samplesheet required")
    sys.exit(1)
```

### API Data Acquisition (No Pre-Staged Input)

Some workflows fetch data from external APIs at runtime rather than using pre-staged input files. This breaks the traditional Pegasus assumption that inputs are registered in the Replica Catalog before workflow submission.

**Pattern: First job fetches data, downstream jobs consume it:**

```python
# No replica catalog entries for input data — the fetch job creates them
fetch_job = (
    Job("fetch_data", _id=f"fetch_{region}", node_label=f"fetch_{region}")
    .add_args(
        f"--region {region} "
        f"--start-date {start_date} "
        f"--output {region}_data.csv"
    )
    .add_outputs(data_file, stage_out=False, register_replica=False)
)

# Downstream jobs depend on fetch output via File objects
analyze_job = (
    Job("analyze", _id=f"analyze_{region}")
    .add_inputs(data_file)  # Dependency on fetch job
    ...
)
```

**Best practices for API-fetching jobs:**

```python
# In the wrapper script
import requests

response = requests.get(api_url, params=params, timeout=60)
response.raise_for_status()  # Fail fast on HTTP errors
```

- Set explicit timeouts (60s recommended)
- Validate response status codes
- Handle rate limits with documentation
- Pass API keys via environment variables (not command-line args):

```python
# In workflow_generator.py — inject credentials at runtime
fetch_job.add_env(API_KEY=os.environ.get("API_KEY", ""))

# In wrapper script — validate early
api_key = os.environ.get("API_KEY")
if not api_key:
    print("Error: API_KEY environment variable not set", file=sys.stderr)
    sys.exit(1)
```

### Region/Location-Based Parameterization

For workflows that process multiple independent regions, locations, or polygons, parameterize the DAG generation loop:

```python
# Earthquake: multiple seismic regions
for region in args.regions:
    self._add_region_pipeline(region)

# Air quality: multiple monitoring locations
for location_id in args.location_ids:
    safe_name = location_name.replace(" ", "_").replace("-", "_")
    self._add_location_pipeline(location_id, safe_name)

# Soil moisture: multiple field polygons
for polygon_id in args.polygon_ids:
    self._add_polygon_pipeline(polygon_id)
```

Each iteration creates an independent sub-DAG. With `infer_dependencies=True`, all sub-DAGs run in parallel automatically.

**Safe naming for filesystem compatibility:**

```python
safe_name = location_name.replace(" ", "_").replace("-", "_").replace("/", "_")
```

**Loading parameters from configuration files:**

```python
# Polygon IDs from JSON config (user edits config, not workflow code)
if not args.polygon_ids:
    with open(args.polygons_file) as f:
        polygons = json.load(f)
    args.polygon_ids = [p["id"] for p in polygons]
```

### Fan-In Merge / Aggregation Jobs

When multiple parallel jobs produce results that need aggregation, create a conditional merge step:

```python
# Collect output files from all parallel jobs
anomaly_files = []
for location in locations:
    anomaly_file = File(f"{location}_anomalies.json")
    anomaly_files.append(anomaly_file)
    # ... add to per-location jobs

# Create merge job only if multiple locations
if len(anomaly_files) > 1:
    merged = File("merged_anomalies.json")
    file_args = " ".join([f"-i {f.lfn}" for f in anomaly_files])
    merge_job = (
        Job("merge", _id="merge_all")
        .add_args(f"{file_args} -o {merged.lfn}")
        .add_inputs(*anomaly_files)
        .add_outputs(merged, stage_out=True, register_replica=False)
    )
    self.wf.add_jobs(merge_job)
```

**Merge script pattern (using `nargs='+'` or `action='append'`):**

```python
# merge.py
parser.add_argument("-i", "--input", nargs="+", required=True,
                    help="Input JSON files to merge")
parser.add_argument("-o", "--output", required=True)

def merge_results(input_files):
    merged = {"locations": {}, "summary": {"total": 0}}
    for f in input_files:
        with open(f) as fh:
            data = json.load(fh)
        location = data.get("location", os.path.basename(f))
        merged["locations"][location] = data
        merged["summary"]["total"] += 1
    return merged
```

### ML Pipeline Integration

For workflows that include machine learning, structure the pipeline as separate Pegasus jobs:

```
fetch_data → prepare_features → train_model → predict → visualize
                                     ↓
                              (model artifact)
                                     ↓
                          predict_location_1  (parallel)
                          predict_location_2  (parallel)
                          predict_location_N  (parallel)
```

**Hub-and-spoke pattern (train once, predict many):**

```python
# Shared model artifact
model_file = File("model.pt")
model_metadata = File("model_metadata.json")

# Single training job
train_job = (
    Job("train_model", _id="train")
    .add_inputs(training_data)
    .add_outputs(model_file, model_metadata, stage_out=False)
    .add_pegasus_profile(memory="4 GB")
)

# Multiple prediction jobs reuse the trained model
for location in locations:
    predict_job = (
        Job("predict", _id=f"predict_{location}")
        .add_inputs(location_data, model_file, model_metadata)
        .add_outputs(prediction_file, stage_out=True)
        .add_pegasus_profile(memory="2 GB")
    )
```

**Graceful ML fallback (when ML dependencies are optional):**

```python
# In wrapper script — fall back to rule-based if PyTorch unavailable
try:
    import torch
    ML_AVAILABLE = True
except ImportError:
    ML_AVAILABLE = False
    logger.warning("PyTorch not available — using rule-based predictions")

if ML_AVAILABLE and model_path:
    result = ml_predict(model_path, features)
else:
    result = rule_based_predict(features)
```

### Headless Mode for GUI Tools

Some bioinformatics tools (FastQC, QUAST) attempt to open a GUI display. Handle this in wrapper scripts:

```bash
#!/bin/bash
# Disable display for headless execution
unset DISPLAY
export JAVA_TOOL_OPTIONS="-Djava.awt.headless=true"

# Use virtual framebuffer if available, otherwise run directly
if command -v xvfb-run &> /dev/null; then
    xvfb-run --auto-servernum fastqc "$@"
else
    fastqc "$@"
fi
```

Include `xvfb` in the Dockerfile:

```dockerfile
RUN apt-get install -y xvfb libgl1-mesa-glx libfontconfig1
```

### Output File Restructuring in Wrappers

Tools that create nested directory structures need their outputs flattened for Pegasus stage-out. Common patterns:

```bash
# QUAST: copies reports from nested output to working directory
quast "$@"
cp "${OUTPUT_DIR}/report.tsv" "${SAMPLE}_quast_report.tsv"
cp "${OUTPUT_DIR}/report.html" "${SAMPLE}_quast_report.html"

# GTDB-Tk: finds summary file in deep subdirectory
find "${OUTPUT_DIR}" -name "*.summary.tsv" -exec cp {} "${SAMPLE}_taxonomy.tsv" \;

# Prokka: copies multiple output types
cp "${OUTPUT_DIR}/${PREFIX}.gff" "${SAMPLE}_annotation.gff"
cp "${OUTPUT_DIR}/${PREFIX}.faa" "${SAMPLE}_proteins.faa"
```

The key insight: Pegasus expects output files to be in the job's working directory (or at the exact path declared in `File()`). Wrapper scripts bridge the gap between tool conventions and Pegasus expectations.

### Manual Testing Scripts

Create a standalone script that runs each pipeline step locally before attempting Pegasus submission. This catches tool errors early:

```bash
#!/bin/bash
# run_manual.sh — validate pipeline locally before Pegasus
set -e

echo "=== Step 1: Fetching data ==="
./bin/fetch_data.py --output test_data.csv

echo "=== Step 2: Analysis ==="
./bin/analyze.py --input test_data.csv --output test_analysis.json

echo "=== Step 3: ML Training ==="
./bin/train_model.py --input test_data.csv --output test_model.pt --epochs 10

echo "=== Step 4: Prediction ==="
./bin/predict.py --input test_analysis.json --model test_model.pt --output test_pred.json

echo "=== Complete! ==="
ls -la test_*
```

Benefits:
- Tests tool installations and dependencies
- Validates argument parsing matches workflow generator
- Identifies missing files or permissions issues
- Runs in seconds vs minutes for Pegasus plan+submit cycle

### Dual Pipeline Architecture

Some workflows split into independent pipelines that share early stages but diverge later. The airquality-workflow demonstrates this:

```python
# Both pipelines share the extract step
extract_job = Job("extract_timeseries", ...)

# Base pipeline (always runs): analyze → detect_anomalies → merge
analyze_job.add_inputs(timeseries_file)
anomaly_job.add_inputs(timeseries_file, analysis_file)

# Forecast pipeline (optional, skippable):
# fetch_historical → prepare_features → train → predict → visualize
if not args.skip_forecast:
    fetch_hist_job.add_inputs(catalog_file)
    prepare_job.add_inputs(timeseries_file, historical_file)
    train_job.add_inputs(features_file)
    predict_job.add_inputs(model_file, timeseries_file)
    visualize_job.add_inputs(prediction_file, timeseries_file)
```

Both branches run in parallel since `infer_dependencies=True` sees no file overlap between them.

### Multiple Data Sources

When a workflow supports different data sources, convert all formats to a common intermediate at workflow generation time:

```python
def create_replica_catalog(self):
    self.rc = ReplicaCatalog()

    # Convert source-specific format to unified CSV at generation time
    if self.data_source == "openaq":
        self.fetch_openaq_catalog()  # Creates openaq_catalog.csv
    elif self.data_source == "sage":
        self.load_sage_catalog()     # Also creates openaq_catalog.csv

    # All downstream jobs use the same unified format
    self.rc.add_replica("local", "catalog.csv",
                        "file://" + os.path.join(self.wf_dir, "catalog.csv"))
```

**Conditional validation based on data source:**

```python
if args.data_source == "openaq" and not args.location_ids:
    raise ValueError("--location-ids required for OpenAQ source")

if args.data_source == "sage" and not args.skip_forecast:
    print("Warning: SAGE lacks historical data — skipping forecast pipeline")
    args.skip_forecast = True
```

### Micromamba Containers for Complex Tool Stacks

When a container needs many bioinformatics tools with conflicting Python/library versions, use micromamba instead of pip:

```dockerfile
FROM mambaorg/micromamba:1.5-jammy

# Single solver resolves all version conflicts
RUN micromamba install -y -n base -c conda-forge -c bioconda \
    python=3.8 \
    fastqc fastp multiqc \
    megahit spades quast \
    prodigal metabat2 samtools \
    checkm2 gtdbtk prokka

# System dependencies for headless tools
USER root
RUN apt-get update && apt-get install -y xvfb libgl1-mesa-glx && \
    rm -rf /var/lib/apt/lists/*

# Install wrapper scripts
COPY bin/*.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/*.sh
```

Advantages over pip:
- Conda solver finds compatible versions across all tools simultaneously
- Handles C/Fortran library dependencies (HDF5, BLAS, etc.)
- Better reproducibility for complex bioinformatics stacks

### Structured Logging in Wrapper Scripts

Use consistent logging across all wrapper scripts for easier debugging via `pegasus-analyzer`:

```python
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Log inputs and parameters
logger.info(f"Input: {args.input}")
logger.info(f"Parameters: crop_type={args.crop_type}, soil={args.soil_type}")

# Log the command being run
logger.info(f"Running: {' '.join(cmd)}")

# Log results summary
logger.info(f"Processed {len(results)} records, output: {args.output}")
```

Set `PYTHONUNBUFFERED=1` in the container to ensure logs appear in real time:

```dockerfile
ENV PYTHONUNBUFFERED=1
```

### Pre-Submission Validation

Validate inputs before any Pegasus API calls to catch errors early:

```python
# Validate required arguments
if not args.test and not args.samplesheet:
    print("Error: Either --test or --samplesheet must be provided")
    sys.exit(1)

# Validate file existence
if args.samplesheet and not os.path.exists(args.samplesheet):
    print(f"Error: Samplesheet not found: {args.samplesheet}")
    sys.exit(1)

# Validate data files before adding to replica catalog
for sample in samples:
    path = sample["fastq_1"]
    if not os.path.exists(path):
        print(f"Warning: Input file not found: {path} — skipping")
        continue
    rc.add_replica("local", os.path.basename(path), "file://" + os.path.abspath(path))
```

### Selective Output Staging Strategy

Use `stage_out` strategically to minimize data transfer:

```python
# Intermediate files — keep in scratch only
.add_outputs(features_file, stage_out=False, register_replica=False)
.add_outputs(model_checkpoint, stage_out=False, register_replica=False)

# Final user-facing results — stage to output directory
.add_outputs(forecast_plot, stage_out=True, register_replica=False)
.add_outputs(summary_json, stage_out=True, register_replica=False)
.add_outputs(merged_results, stage_out=True, register_replica=False)
```

**Guidelines:**

| File Type | stage_out | Reason |
|-----------|-----------|--------|
| Feature matrices, scaler params | `False` | Only needed by downstream jobs |
| ML model checkpoints | `False` | Only needed by prediction jobs |
| Intermediate alignments | `False` | Only needed by downstream steps |
| Final reports, plots, CSVs | `True` | User needs these in output dir |
| QC reports | `True` | User reviews for quality |
| Merged/aggregated results | `True` | Final deliverable |

### Forcing Jobs to Run Locally

Some jobs (like `mkdir`) must run on the submit node, not on remote workers:

```python
from Pegasus.api import Namespace

mkdir_job = (
    Job("mkdir", _id=f"mkdir_{location}")
    .add_args(f"-p {output_dir}/results/{location}")
    .add_profiles(Namespace.SELECTOR, key="execution.site", value="local")
)
```

The `execution.site=local` profile forces Pegasus to schedule this job on the submit host.

## Workflow Comparison Summary

| Pattern | tnseq | orcasound | mag | earthquake | soilmoisture | airquality |
|---------|-------|-----------|-----|------------|--------------|------------|
| Python wrappers | x | x | | x | x | x |
| Shell wrappers | | | x | | | |
| `is_stageable=True` | x | x | | x | x | x |
| `is_stageable=False` | | | x | | | |
| `--test` mode | | | x | | | |
| Skip flags | | | x | | | x |
| API data fetch | | | | x | x | x |
| Region/location loop | | | | x | x | x |
| ML training + inference | | | | | x | x |
| Fan-in merge | x | | | | | x |
| Edge-to-cloud DPU | | x | | | x | x |
| Manual test script | | | x | | x | |
| Micromamba container | | | x | | | |
| Per-tool resource dict | | | x | x | | |
| Environment variable secrets | | | | | | x |
| Dual pipeline architecture | | | | | | x |
| Multiple data sources | | | | | | x |
