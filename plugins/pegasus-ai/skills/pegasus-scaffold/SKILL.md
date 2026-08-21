---
name: pegasus-scaffold
description: Create a complete Pegasus workflow project from a pipeline description
allowed-tools:
  - Read
  - Glob
  - Grep
  - Write
  - Edit
  - Bash
# What a finished workflow must contain. Declared here so a consumer can state
# it in always-on context without restating it: the requirement stays defined in
# one place, and a model that never loads this skill still learns of it.
deliverables:
  - workflow_generator.py
  - bin/<one wrapper per step>
  - Apptainer/<Name>_Container.def
  - run_manual.sh
  - README.md
---

# Pegasus Workflow Scaffold

You are a Pegasus workflow generator. The user has invoked `/pegasus-scaffold` to create a new workflow project from scratch.

## Step 1: Read Reference Materials

Every path below is relative to the **`pegasus-ai` plugin directory** — the one
containing `skills/`, `references/` and `assets/` — and *not* to your working
directory. Hosts run this skill from wherever the user is working, so a bare
`references/PEGASUS.md` will not resolve. If the context you were given names the
plugin directory, read from there. If it does not, locate the guide with a glob
for `**/pegasus-ai/references/PEGASUS.md` and resolve the rest against it.

If you cannot find these files, say so and stop. Do not proceed to Step 2:
without the guide you will re-derive patterns this project has already settled,
and the container, staging and fan-out conventions below assume you have read it.

1. Read `references/PEGASUS.md` — this is the comprehensive guide for all Pegasus patterns.
2. Read `assets/templates/workflow_generator_template.py` — your starting point for the workflow generator.
3. Read `assets/templates/wrapper_template.py` and `assets/templates/wrapper_template.sh` — starting points for wrappers.
4. Read `assets/templates/Apptainer_template.def` — starting point for the container.

## Step 2: Gather Requirements

Ask the user the following questions. If they've already provided some answers in their message, skip those.

1. **Pipeline name**: What should the workflow be called? (e.g., "rnaseq", "weather-analysis")
2. **Pipeline steps**: Describe each step in order — what tool does it run, what are its inputs and outputs?
3. **Data source**: Where does input data come from?
   - Local files (FASTQ, CSV, etc.) — needs Replica Catalog entries
   - API fetch at runtime (USGS, OpenAQ, etc.) — first job fetches, no RC entries needed
   - Both (reference files + API data)
4. **Iteration pattern**: How does the pipeline parallelize?
   - Per-sample (like tnseq: each sample goes through the same pipeline independently)
   - Per-region/location (like earthquake: loop over geographic regions)
   - Single linear pipeline (no parallelism)
   - Fan-out/fan-in (process items in parallel, then merge)
5. **Tools needed**: List all command-line tools or Python libraries each step uses
6. **ML component?**: Does the pipeline include model training and/or inference?
   - If yes: train-once-predict-many (hub-and-spoke) or train-per-item?
7. **External data directories?**: Does the pipeline need access to external data directories at runtime (model caches, databases, reference collections)?
   - If yes → use CondorIO (`transfer_input_files`) to transfer them to jobs (see Pegasus.md "Transferring Data Directories via CondorIO")
   - Do NOT use container `mounts=[]` for this — CondorIO is preferred
8. **Container preference**: pip-based (simple) or micromamba (complex bioinformatics)?
9. **Wrapper type**: Python wrappers (recommended for most) or shell wrappers (for tools with nested output)?

## Step 3: Select Reference Workflow

Based on the user's answers, select the closest existing workflow as a reference pattern:

| If the workflow has... | Study this example |
|------------------------|-------------------|
| Per-sample parallelism, fan-in merge | `examples/workflow_generator_tnseq.py` |
| API fetch + region loops | `examples/workflow_generator_earthquake.py` |
| Shell wrappers, micromamba, `--test` mode | `examples/workflow_generator_mag.py` |
| ML train-then-predict | `examples/workflow_generator_soilmoisture.py` |
| Dual pipeline, skip flags, multiple data sources | `examples/workflow_generator_airquality.py` |
| Fork-join topology, complex branching, PLINK bioinformatics | `examples/workflow_generator_gwas_qc.py` |
| Nextflow conversion, R support files (edgeR/DESeq2) | `examples/workflow_generator_rnaseq.py` |
| CondorIO for caches/databases, GPU jobs, batch inference | `examples/workflow_generator_proteinfold.py` + Pegasus.md "Transferring Data Directories via CondorIO" |
| Image tiling, split→parallel→merge, GPU U-Net training | `examples/workflow_generator_s2_segmentation.py` |
| Federated learning with SubWorkflows, FL rounds as sub-DAGs | `examples/workflow_generator_medical_imaging_fl.py` + `examples/fl_round.py` |
| Time-window splitting, parallel observation data harvesting | `examples/workflow_generator_obs_harvest.py` |
| Hierarchical merge tree, DAGMan rate limiting, inline submit | `examples/workflow_generator_sra_search.py` |

Read the selected reference workflow before generating code.

## Step 4: Generate Files

Create the following files in `{pipeline-name}-workflow/`:

### 4a. `workflow_generator.py`

Start from `assets/templates/workflow_generator_template.py` and customize:

1. **Class name**: `{PipelineName}Workflow`
2. **`wf_name`**: `"{pipeline_name}"`
3. **`__init__`**: Add pipeline-specific parameters
4. **`create_transformation_catalog`**: Register one `Transformation` per wrapper script with appropriate memory/cores
5. **`create_replica_catalog`**: Register input files (or leave empty for API-fetch patterns)
6. **`create_workflow`**: Build the DAG with jobs, file objects, and dependencies
7. **`main()`**: Add pipeline-specific argparse arguments
8. **Input validation**: Validate required arguments before any Pegasus API calls

Key rules:
- Use `infer_dependencies=True` on the Workflow
- Use `stage_out=True` only on final outputs; `stage_out=False` for intermediates
- Use `register_replica=False` on all outputs
- Job `_id` must be unique — use `f"{step}_{item}"` pattern
- File objects must be shared between producer and consumer jobs (same Python object, not just same string)
- For fan-in merge steps, collect output files in a list and pass to a merge job via `add_inputs(*files)`
- For external data directories (caches, databases), use CondorIO `transfer_input_files` on the Transformation — do NOT use container `mounts=[]`. Pass `os.path.basename()` of the directory to wrapper scripts.

### 4b. `bin/{step}.py` (one per pipeline step)

Start from `assets/templates/wrapper_template.py` and customize:

1. **argparse arguments**: Must exactly match what `workflow_generator.py` passes in `add_args()`
2. **`os.makedirs`**: Create output subdirectories before writing
3. **Tool invocation**: Use `subprocess.run()` for CLI tools, or call Python libraries directly
4. **Exit code propagation**: `sys.exit(result.returncode)` after subprocess calls
5. **Logging**: Print the command being run for debugging

For fan-in merge wrappers, use `action="append"` or `nargs="+"` for the input argument.

For shell wrappers (when tools produce nested output), start from `assets/templates/wrapper_template.sh`.

### 4c. `Apptainer/{Name}_Container.def`

Start from `assets/templates/Apptainer_template.def` and customize:

1. Choose base image: `python:3.8-slim` (pip), `mambaorg/micromamba:1.5-jammy` (conda), or `ubuntu:22.04` (apt+pip)
2. Install all tools needed by all wrapper scripts
3. Set `export PYTHONUNBUFFERED=1` in `%environment`
4. If using shell wrappers with `is_stageable=False`, add a `%files` section (`bin/*.sh /usr/local/bin/`) and `chmod +x` them in `%post`
5. Build with `apptainer build {Name}_Container.sif Apptainer/{Name}_Container.def` and reference the resulting `.sif` via `file://` in `workflow_generator.py`'s `Container()`

### 4d. `README.md`

Start from `assets/templates/README_template.md` and customize with the actual pipeline name, steps, options, and outputs.

### 4e. `run_manual.sh`

Start from `assets/templates/run_manual_template.sh` and customize:

1. Test data download or generation
2. One section per pipeline step, calling the wrapper script with test arguments
3. Output verification after each step

Make the script executable: `chmod +x run_manual.sh`

## Step 5: Validation Checklist

Before presenting the generated code to the user, verify:

**First, that every deliverable is on disk.** Run `ls -R` on the project
directory and read the listing against this list — do not rely on remembering
what you wrote:

- [ ] `workflow_generator.py`
- [ ] `bin/` — one wrapper per pipeline step
- [ ] `Apptainer/{Name}_Container.def`
- [ ] `run_manual.sh`, executable
- [ ] `README.md`
- [ ] any document the user asked for (a specification, say), inside the project
      directory rather than beside it

`run_manual.sh` and `README.md` are the two that get skipped when the generator
and wrappers took a long time to write. A workflow missing them is one nobody
else can run or understand, so it is not finished. Create what is missing before
you reply; never describe the workflow as complete while an item is absent, and
never tell the user to add one themselves.

**Then, that the code is correct:**

- [ ] **File I/O match**: Every `add_args()` filename matches a `File()` LFN, and the wrapper's argparse matches
- [ ] **Dependency chain**: File objects are shared between producer/consumer jobs (not duplicated)
- [ ] **stage_out strategy**: Only final outputs have `stage_out=True`
- [ ] **Unique job IDs**: No duplicate `_id` values across all jobs
- [ ] **Replica Catalog completeness**: All local input files and support scripts are registered
- [ ] **Wrapper `os.makedirs`**: Any output path with `/` has `os.makedirs` before writing
- [ ] **Container has all tools**: Every tool called by every wrapper is installed via the Apptainer `.def` file
- [ ] **`--help` works**: `python3 workflow_generator.py --help` would produce useful output
- [ ] **No directory scanning**: No `glob()`, `os.listdir()`, or `list.files()` between jobs
- [ ] **Support files use `os.getcwd()`**: Not `__file__`-relative paths

## Step 6: Plan It

The checklist above is you reading your own code, which is exactly the state of
mind that wrote the bug. Finish by having the planner read it instead:

```bash
python3 workflow_generator.py <args>          # writes workflow.yml + the catalogs
pegasus-plan --dir submit --sites condorpool --output-sites local workflow.yml
```

Planning is local, takes seconds, needs no container built and no pool running.
It resolves every file against its producer and every transformation against its
site, so it catches in one pass what no amount of re-reading does:

- a file consumed by one job and produced by none
- a fan-out loop that registered only its last iteration
- a container whose `image_site` never got set
- a transformation pointing at a site the Site Catalog does not define

Two of those shipped in a real workflow that passed the Step 5 checklist. The
generator ran, the YAML looked right, every deliverable was on disk, and it could
not be planned.

**A workflow that has not been planned is not finished.** If the plan fails, fix
the generator (not the generated YAML — it is overwritten on the next run),
regenerate, and plan again until it succeeds. Then tell the user it plans, and
what the DAG contains:

```
Plans clean: 99 compute jobs (24 subjects x 4 steps + 3 aggregation).
```

If something genuinely outside the workflow blocks planning — Pegasus not
installed, an input the user has not supplied yet — say plainly that it is
unplanned and why, rather than reporting it as done.

## Full Workflow Repositories

For complete working examples beyond the excerpts in `examples/`:
- https://github.com/pegasus-isi/tnseq-workflow — per-sample bioinformatics, fan-in merge
- https://github.com/pegasus-isi/earthquake-workflow — API data fetch, per-region loops
- https://github.com/pegasus-isi/mag-workflow — shell wrappers, micromamba, metagenomics
- https://github.com/pegasus-isi/soilmoisture-workflow — ML train-then-predict
- https://github.com/pegasus-isi/airquality-workflow — dual pipeline, LSTM forecasting
- https://github.com/pegasus-isi/crophealth-workflow — CNN classification, edge-to-cloud DPU
- https://github.com/pegasus-isi/gwas-qc-workflow — fork-join GWAS QC, PLINK
- https://github.com/pegasus-isi/orcasound-workflow — S3 audio data, per-sensor parallelism
- https://github.com/pegasus-isi/rnaseq-workflow — Nextflow conversion, RNA-Seq, R support files
- https://github.com/pegasus-isi/proteinfold-workflow — GPU protein folding, CondorIO for model caches
- https://github.com/pegasus-isi/s2-segmentation-workflow — Sentinel-2 image tiling, GPU U-Net training
- https://github.com/pegasus-isi/medical-imaging-fl-workflow — federated learning with SubWorkflows
- https://github.com/swarm-workflows/obs-harvest-workflow — parallel observation data harvesting
- https://github.com/pegasus-isi/sra-search-pegasus-workflow — hierarchical merge tree, DAGMan rate limiting
