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
---

# Pegasus Workflow Scaffold

You are a Pegasus workflow generator. The user has invoked `/pegasus-scaffold` to create a new workflow project from scratch.

## Step 1: Read Reference Materials

1. Read `references/PEGASUS.md` from the repository root — this is the comprehensive guide for all Pegasus patterns.
2. Read `assets/templates/workflow_generator_template.py` — your starting point for the workflow generator.
3. Read `assets/templates/wrapper_template.py"` and `assets/templates/wrapper_template.sh` — starting points for wrappers.
4. Read `assets/templates/Dockerfile_template` — starting point for the container.

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
7. **Container preference**: pip-based (simple) or micromamba (complex bioinformatics)?
8. **Wrapper type**: Python wrappers (recommended for most) or shell wrappers (for tools with nested output)?

## Step 3: Select Reference Workflow

Based on the user's answers, select the closest existing workflow as a reference pattern:

| If the workflow has... | Study this example |
|------------------------|-------------------|
| Per-sample parallelism, fan-in merge | `examples/workflow_generator_tnseq.py` |
| API fetch + region loops | `examples/workflow_generator_earthquake.py` |
| Shell wrappers, micromamba, `--test` mode | `examples/workflow_generator_mag.py` |
| ML train-then-predict | `examples/workflow_generator_soilmoisture.py` |
| Dual pipeline, skip flags, multiple data sources | `examples/workflow_generator_airquality.py` |

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

### 4b. `bin/{step}.py` (one per pipeline step)

Start from `assets/templates/wrapper_template.py` and customize:

1. **argparse arguments**: Must exactly match what `workflow_generator.py` passes in `add_args()`
2. **`os.makedirs`**: Create output subdirectories before writing
3. **Tool invocation**: Use `subprocess.run()` for CLI tools, or call Python libraries directly
4. **Exit code propagation**: `sys.exit(result.returncode)` after subprocess calls
5. **Logging**: Print the command being run for debugging

For fan-in merge wrappers, use `action="append"` or `nargs="+"` for the input argument.

For shell wrappers (when tools produce nested output), start from `assets/templates/wrapper_template.sh`.

### 4c. `Docker/{Name}_Dockerfile`

Start from `assets/templates/Dockerfile_template` and customize:

1. Choose base image: `python:3.8-slim` (pip), `mambaorg/micromamba:1.5-jammy` (conda), or `ubuntu:22.04` (apt+pip)
2. Install all tools needed by all wrapper scripts
3. Set `ENV PYTHONUNBUFFERED=1`
4. If using shell wrappers with `is_stageable=False`, `COPY bin/*.sh /usr/local/bin/` and `chmod +x`

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

- [ ] **File I/O match**: Every `add_args()` filename matches a `File()` LFN, and the wrapper's argparse matches
- [ ] **Dependency chain**: File objects are shared between producer/consumer jobs (not duplicated)
- [ ] **stage_out strategy**: Only final outputs have `stage_out=True`
- [ ] **Unique job IDs**: No duplicate `_id` values across all jobs
- [ ] **Replica Catalog completeness**: All local input files and support scripts are registered
- [ ] **Wrapper `os.makedirs`**: Any output path with `/` has `os.makedirs` before writing
- [ ] **Container has all tools**: Every tool called by every wrapper is installed in the Dockerfile
- [ ] **`--help` works**: `python3 workflow_generator.py --help` would produce useful output
- [ ] **No directory scanning**: No `glob()`, `os.listdir()`, or `list.files()` between jobs
- [ ] **Support files use `os.getcwd()`**: Not `__file__`-relative paths

## Full Workflow Repositories

For complete working examples beyond the excerpts in `examples/`:
- https://github.com/pegasus-isi/tnseq-workflow
- https://github.com/pegasus-isi/earthquake-workflow
- https://github.com/pegasus-isi/mag-workflow
- https://github.com/pegasus-isi/soilmoisture-workflow
- https://github.com/pegasus-isi/airquality-workflow
