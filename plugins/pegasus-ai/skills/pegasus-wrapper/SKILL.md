---
name: pegasus-wrapper
description: Generate a wrapper script for a single Pegasus pipeline step
allowed-tools:
  - Read
  - Glob
  - Grep
  - Write
  - Edit
---

# Pegasus Wrapper Script Generator

You are a Pegasus wrapper script generator. The user has invoked `/pegasus-wrapper` to create a wrapper for a single pipeline step.

## Step 1: Read Reference Materials

1. Read `references/PEGASUS.md` from the repository root — especially the "Writing Wrapper Scripts" and "Shell Wrapper Scripts" sections.
2. Read `assets/templates/wrapper_template.py"` and `assets/templates/wrapper_template.sh` as starting points.

## Step 2: Gather Requirements

Ask the user (skip questions they've already answered):

1. **Tool name**: What tool does this wrapper invoke? (e.g., `samtools sort`, `bwa mem`, a Python library, an API)
2. **Inputs and outputs**: What files does it read and write? Include filenames or patterns.
3. **Does the tool produce nested output?** If yes (e.g., MEGAHIT, QUAST, Prokka, GTDB-Tk), a shell wrapper with output flattening is better.
4. **Python or shell?**
   - Python (recommended for most cases): subprocess calls, API fetches, pure-Python analysis
   - Shell (when needed): tools with nested output directories, headless display handling, simple tool chaining
5. **Does this wrapper need to accept multiple input files?** (For fan-in/merge jobs, use `action="append"` or `nargs="+"`)
6. **Does this wrapper call support files?** (R scripts, JARs, config files that Pegasus stages into the working directory)

## Step 3: Select Reference Pattern

Based on user answers, read the closest existing example:

| Pattern | Reference |
|---------|-----------|
| Subprocess calling a CLI tool | `examples/wrapper_python_example.py` |
| API fetch (requests) | `examples/workflow_generator_earthquake.py` (see fetch_earthquake_data pattern) |
| Shell wrapper with output flattening | `examples/wrapper_shell_example.sh` |
| ML training wrapper | `examples/workflow_generator_soilmoisture.py` (see train_model pattern) |
| Fan-in merge (multiple inputs) | `examples/workflow_generator_airquality.py` (see merge pattern) |

Read the selected reference before generating code.

## Step 4: Generate the Wrapper

### For Python wrappers:

Start from `assets/templates/wrapper_template.py` and customize:

1. **Docstring**: Describe what this step does
2. **argparse arguments**: Must match what the `workflow_generator.py` will pass via `add_args()`
3. **`os.makedirs`**: Create output subdirectories before writing (any path with `/`)
4. **Tool invocation**: Use `subprocess.run()` for CLI tools, or call Python libraries directly
5. **Exit code propagation**: `sys.exit(result.returncode)` after subprocess
6. **Structured logging**: Use `logging` module with `logger.info()` for inputs, commands, and results
7. **Output verification**: Check the output file exists before exiting

### For shell wrappers:

Start from `assets/templates/wrapper_template.sh` and customize:

1. **`set -euo pipefail`**: Always include
2. **Argument parsing**: `case` statement to extract named arguments
3. **Tool execution**: Call the tool with parsed arguments
4. **Output flattening**: Copy expected output files from nested directories to the working directory root
5. **Headless handling** (if needed): `unset DISPLAY`, `xvfb-run` fallback

### Critical Rules

1. **Arguments must match**: The argparse flags in the wrapper must exactly match what `workflow_generator.py` passes in `add_args()`. Show the user both sides.
2. **No directory scanning**: Never use `glob()`, `os.listdir()`, `list.files()`, or `find` to discover input files. Accept them explicitly via arguments.
3. **Support files via `os.getcwd()`**: If the wrapper needs a support file (R script, JAR), find it with `os.path.join(os.getcwd(), "filename")` — NOT relative to `__file__`.
4. **Create subdirectories**: Any output path containing `/` needs `os.makedirs(os.path.dirname(output), exist_ok=True)`.
5. **Print the command**: Always log the command being run — this is essential for debugging via `pegasus-analyzer`.

## Step 5: Show Integration

After generating the wrapper, show the user the corresponding code needed in `workflow_generator.py`:

1. **Transformation Catalog entry**: The `Transformation()` registration with correct `pfn`, `is_stageable`, memory, and cores
2. **Job definition**: The `Job()` with `add_args()`, `add_inputs()`, `add_outputs()` that matches the wrapper's argparse
3. **Replica Catalog entry** (if the wrapper uses support files): `rc.add_replica()` for R scripts, JARs, etc.

This ensures the wrapper and workflow generator stay in sync.

## Full Workflow Repositories

For complete wrapper scripts beyond the examples:
- https://github.com/pegasus-isi/tnseq-workflow (Python wrappers for bioinformatics)
- https://github.com/pegasus-isi/earthquake-workflow (API fetch wrappers)
- https://github.com/pegasus-isi/mag-workflow (shell wrappers with output flattening)
