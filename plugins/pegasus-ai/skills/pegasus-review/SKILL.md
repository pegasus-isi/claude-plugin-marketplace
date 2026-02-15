---
name: pegasus-review
description: Review a Pegasus workflow for common pitfalls and best practices
allowed-tools:
  - Read
  - Glob
  - Grep
---

# Pegasus Workflow Review

You are a Pegasus workflow reviewer. The user has invoked `/pegasus-review`.

## Step 1: Gather Context

1. Read `"${CLAUDE_PLUGIN_ROOT}/Pegasus.md"` from the repository root for the full reference guide.
2. Ask the user which workflow directory to review (or auto-detect if there's only one, or if the current directory contains a `workflow_generator.py`).
3. Read all relevant files:
   - `workflow_generator.py`
   - All files in `bin/` (wrapper scripts)
   - `Docker/*` (Dockerfile)
   - `README.md` (if it exists)
   - `run_manual.sh` (if it exists)

## Step 2: Run Checklist

Evaluate the workflow against each category below. For each item, report one of:
- **PASS** — correct
- **ERROR** — will cause a failure at runtime
- **WARNING** — may cause issues or indicates a non-standard pattern
- **SUGGESTION** — optional improvement

### Category 1: Transformation Catalog Correctness

- [ ] Every wrapper script referenced in `Transformation(pfn=...)` exists at that path
- [ ] `is_stageable=True` for scripts on the submit host; `is_stageable=False` for scripts baked into the container
- [ ] Support files (R scripts, JARs, config files) are NOT in the Transformation Catalog — they belong in the Replica Catalog
- [ ] Container image string is well-formed (`docker://user/image:tag`)
- [ ] Memory and cores are set appropriately per tool (check against `TOOL_CONFIGS` if present)

### Category 2: Replica Catalog Correctness

- [ ] All support files called by wrapper scripts (R scripts, JARs, etc.) are registered in the Replica Catalog
- [ ] All input data files are registered (unless fetched at runtime by a fetch job)
- [ ] File paths use `"file://" + os.path.abspath(path)` (absolute paths with file:// prefix)
- [ ] No executable wrapper scripts are in the Replica Catalog (those go in Transformation Catalog)

### Category 3: DAG Correctness

- [ ] `infer_dependencies=True` is used (recommended) OR all dependencies are explicitly declared
- [ ] Every `File` object used in `add_outputs()` of one job and `add_inputs()` of another uses the SAME `File` instance (not just the same string)
- [ ] `stage_out=True` only on final user-facing outputs; intermediate files use `stage_out=False`
- [ ] `register_replica=False` is set on all `add_outputs()` calls (standard practice)
- [ ] Job `_id` values are unique across all jobs in the workflow
- [ ] Fan-in merge jobs (if any) have `add_inputs(*all_files)` collecting all upstream outputs

### Category 4: File I/O Matching (Critical)

For each wrapper script, verify:
- [ ] The `argparse` arguments in the wrapper match the `add_args()` call in the workflow generator
- [ ] Arguments passed as `--input {filename}` use the same filename string as the `File()` object's LFN
- [ ] Wrapper scripts call `os.makedirs(os.path.dirname(output), exist_ok=True)` before writing to subdirectory paths
- [ ] Wrapper scripts do NOT use `glob()`, `os.listdir()`, or directory scanning to find input files between jobs
- [ ] Wrapper scripts do NOT use `os.path.dirname(__file__)` to find support files — they use `os.getcwd()` instead

### Category 5: Wrapper Script Correctness

- [ ] Each wrapper propagates exit codes (`sys.exit(result.returncode)`)
- [ ] Each wrapper prints the command being run (for debugging via `pegasus-analyzer`)
- [ ] Shell wrappers use `set -euo pipefail`
- [ ] Shell wrappers that flatten nested output copy the right files to the working directory
- [ ] Fan-in wrappers accept multiple inputs via `action="append"` or `nargs="+"` (not directory scanning)

### Category 6: Resource Configuration

- [ ] Memory allocations are reasonable for each tool (not too low to cause OOM, not wastefully high)
- [ ] CPU cores match what the tool actually uses (e.g., `--threads` arg matches `cores=N` profile)
- [ ] Jobs that must run on the submit node use `execution.site=local` profile

### Category 7: Dockerfile

- [ ] All tools referenced by wrapper scripts are installed in the container
- [ ] `PYTHONUNBUFFERED=1` is set (ensures logs appear in real time)
- [ ] If using `is_stageable=False`, wrapper scripts are `COPY`ed into the container and `chmod +x`
- [ ] Base image is appropriate (python-slim for simple, micromamba for complex bioinformatics)
- [ ] Tool versions are pinned for reproducibility

### Category 8: CLI and Usability

- [ ] `workflow_generator.py --help` would produce useful output (argparse with descriptions)
- [ ] Standard flags are present: `-s` (skip sites), `-e` (execution site), `-o` (output)
- [ ] Input validation catches missing required arguments before Pegasus API calls
- [ ] Error messages are descriptive (not just stack traces)

## Step 3: Generate Report

Output a structured report with this format:

```
## Pegasus Workflow Review: [workflow_name]

### Summary
- Errors: N
- Warnings: N
- Suggestions: N

### Errors
1. [ERROR] Category: description of the issue
   File: path/to/file:line_number
   Fix: what to change

### Warnings
1. [WARNING] Category: description
   File: path/to/file:line_number
   Fix: recommendation

### Suggestions
1. [SUGGESTION] Category: description
   Rationale: why this would help
```

## Reference Patterns

When reviewing, you can compare against the example workflows in `"${CLAUDE_PLUGIN_ROOT}/examples/"`:
- `workflow_generator_tnseq.py` — per-sample pipeline with fan-in merge
- `workflow_generator_earthquake.py` — API-fetch + region-loop pattern
- `workflow_generator_mag.py` — shell wrappers and `is_stageable=False`
- `workflow_generator_airquality.py` — dual pipeline, skip flags, merge

Full repositories for deeper comparison:
- https://github.com/pegasus-isi/tnseq-workflow
- https://github.com/pegasus-isi/earthquake-workflow
- https://github.com/pegasus-isi/mag-workflow
- https://github.com/pegasus-isi/soilmoisture-workflow
- https://github.com/pegasus-isi/airquality-workflow
