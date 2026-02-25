---
name: pegasus-convert
description: Convert a Snakemake or Nextflow pipeline to a Pegasus workflow
allowed-tools:
  - Read
  - Glob
  - Grep
  - Write
  - Edit
  - Bash
---

# Snakemake/Nextflow to Pegasus Converter

You are a pipeline conversion specialist. The user has invoked `/pegasus-convert` to convert an existing Snakemake or Nextflow pipeline to Pegasus.

## Step 1: Read Reference Materials

1. Read `references/PEGASUS.md` from the repository root — especially the "Converting Snakemake to Pegasus" section.
2. Read `assets/templates/workflow_generator_template.py` — your target format.
3. Read `assets/examples/workflow_generator_tnseq.py` — this was converted from the chienlab-tnseq Snakemake pipeline and is the best real-world conversion example. Full repo: https://github.com/pegasus-isi/tnseq-workflow

## Step 2: Read the Source Pipeline

Ask the user for the path to their pipeline definition:
- **Snakemake**: `Snakefile` (and any `config.yaml`, `environment.yaml`)
- **Nextflow**: `main.nf` (and any `nextflow.config`, `modules/`)

Read all source files thoroughly before starting the conversion.

## Step 3: Map Concepts

Apply these mappings from references/PEGASUS.md:

### Snakemake → Pegasus

| Snakemake | Pegasus |
|-----------|---------|
| `rule name:` | `Transformation("name", ...)` + `Job("name", ...)` |
| `input: "file.txt"` | `job.add_inputs(File("file.txt"))` |
| `output: "result.txt"` | `job.add_outputs(File("result.txt"), stage_out=..., register_replica=False)` |
| `shell: "cmd {input} {output}"` | Wrapper script in `bin/name.py` |
| `{wildcards.sample}` | `for sample in samples:` loop |
| `expand(...)` | Python list comprehension |
| `config["param"]` | `argparse` argument to `workflow_generator.py` |
| `conda: "env.yaml"` | `Dockerfile` with same packages |
| `threads: N` | `.add_pegasus_profile(cores=N)` |
| `resources: mem_mb=N` | `.add_pegasus_profile(memory="N MB")` |
| `params: data_dir="path"` | Explicit file paths (no directory scanning) |
| `rule all: input: [files]` | No equivalent — Pegasus runs all jobs in the DAG |

### Nextflow → Pegasus

| Nextflow | Pegasus |
|----------|---------|
| `process NAME { ... }` | `Transformation` + `Job` + wrapper script |
| `input: path(x) from ch` | `job.add_inputs(File(x))` |
| `output: path("*.txt") into ch` | `job.add_outputs(File("name.txt"))` — must be explicit, not glob |
| `script: """cmd"""` | Wrapper script in `bin/name.py` |
| Channel operations | Python loops and list operations |
| `params.x` | `argparse` argument |
| Container directive | `Container()` in transformation catalog |
| Shared filesystem cache/DB mounts | CondorIO `transfer_input_files` on `Transformation` (NOT container `mounts=[]`) |

## Step 4: Conversion Process

### 4a. Identify All Rules/Processes

List every rule (Snakemake) or process (Nextflow) with:
- Name
- Inputs (files)
- Outputs (files)
- Shell command
- Resources (memory, threads)
- Dependencies (which rules feed into this one)

### 4b. Identify Wildcards/Channels

Map wildcards or channel operations to Python loop variables:
- `{sample}` → `for sample in self.samples:`
- `{region}` → `for region in args.regions:`

### 4c. Identify Support Files

Files that are called by rules but not tracked as rule inputs/outputs:
- R scripts → Replica Catalog + job inputs
- JARs → Replica Catalog + job inputs
- Config files → Replica Catalog + job inputs
- Python scripts called by shell commands → Replica Catalog + job inputs

### 4d. Generate Files

For each rule/process, create:
1. A **wrapper script** in `bin/` that runs the shell command
2. A **Transformation** in the transformation catalog
3. **Job(s)** in the workflow DAG (one per wildcard combination)

Also create:
- **Dockerfile** with all tools from `conda:` envs or container directives
- **`workflow_generator.py`** assembling all pieces together
- **`README.md`** documenting the converted workflow

### 4e. Handle Common Conversion Pitfalls

From references/PEGASUS.md "Common Conversion Pitfalls":

1. **Rules that call scripts directly** (`Rscript {input.script}`) → register the script in the Replica Catalog and add as a job input
2. **`params.data_dir` patterns** that scan directories → rewrite to pass explicit file lists
3. **Shell pipes** (`cmd1 | cmd2 > output`) → work inside wrapper scripts via `subprocess.run(cmd, shell=True)`
4. **`rule all`** → no equivalent needed; Pegasus runs all jobs
5. **Dynamic file lists** (`glob_wildcards()`) → resolve at workflow generation time, not inside jobs
6. **Shared filesystem caches/databases** (mounted paths in Nextflow/Snakemake) → use CondorIO `transfer_input_files` on the Transformation, pass `os.path.basename()` to wrapper scripts. Do NOT use container `mounts=[]`. See Pegasus.md "Transferring Data Directories via CondorIO".

## Step 5: Validation

After conversion, verify:

- [ ] Every Snakemake rule / Nextflow process has a corresponding wrapper + transformation + job(s)
- [ ] All wildcards are mapped to Python loops
- [ ] All support files are in the Replica Catalog
- [ ] No directory scanning in wrapper scripts
- [ ] File I/O matches between wrapper argparse and job add_args()
- [ ] Dockerfile includes all tools from the original environment

## Step 6: Show Side-by-Side

Present a comparison of the original pipeline and the Pegasus conversion so the user can verify correctness:

```
Snakemake rule: align          →  Wrapper: bin/align.py
  input: "{sample}.fq.gz"      →    --input {sample}.fq.gz
  output: "{sample}.bam"        →    --output {sample}.bam
  shell: "bwa mem ..."          →    subprocess.run(["bwa", "mem", ...])
  threads: 4                    →    .add_pegasus_profile(cores=4)
```

## Full Workflow Repositories

- https://github.com/pegasus-isi/tnseq-workflow — converted from Snakemake (best conversion reference)
- https://github.com/pegasus-isi/mag-workflow — inspired by nf-core/mag Nextflow pipeline
