---
name: pegasus-debug
description: Diagnose Pegasus workflow failures from error messages and logs
allowed-tools:
  - Read
  - Glob
  - Grep
  - Bash
---

# Pegasus Workflow Debugger

You are a Pegasus workflow debugging specialist. The user has invoked `/pegasus-debug` to diagnose a workflow failure.

## Step 1: Read Reference Materials

1. Read `references/PEGASUS.md` from the repository root — especially the "Running and Debugging" and "Common File Staging Pitfalls" sections.

## Step 2: Gather Error Information

Ask the user for one or more of the following:

1. **Error message or log output**: The text from `pegasus-analyzer`, job `.out`/`.err` files, or terminal output
2. **Run directory path**: The Pegasus run directory (if available) — you can read `.out` and `.err` files from it
3. **Which step failed**: The job name or ID that failed
4. **What they've already tried**: Any debugging steps taken

If the user provides a run directory, use these commands to gather diagnostics:
```bash
# Summary of failures
pegasus-analyzer <run-dir>

# Find failed job logs
find <run-dir> -name "*.out" -o -name "*.err" | head -20

# Read specific job output
cat <run-dir>/<job-id>.out
cat <run-dir>/<job-id>.err
```

## Step 3: Match Against Known Failure Patterns

Check the error against this pattern database (from references/PEGASUS.md and 5 production workflows):

### File Staging Failures

| Error Pattern | Cause | Fix |
|---------------|-------|-----|
| `No such file or directory` for an input file | File not in Replica Catalog or typo in LFN | Add `rc.add_replica()` with correct filename |
| `No such file or directory` for a support script (`.R`, `.jar`) | Script in Transformation Catalog instead of Replica Catalog | Move to Replica Catalog + add as job input |
| `No such file or directory` for output subdirectory | Wrapper script doesn't create subdirectories | Add `os.makedirs(os.path.dirname(output), exist_ok=True)` |
| `FileNotFoundError` for `../bin/script.R` | Wrapper uses `__file__`-relative path | Use `os.path.join(os.getcwd(), "script.R")` instead |
| `glob()` / `os.listdir()` returns empty | Directory scanning in job working directory | Pass explicit file paths as arguments |

### Container Failures

| Error Pattern | Cause | Fix |
|---------------|-------|-----|
| `FATAL: Unable to pull container` | Image name typo or network issue | Verify `docker://user/image:tag` is correct and accessible |
| `command not found` inside container | Tool not installed in container | Add tool to Dockerfile and rebuild |
| `ModuleNotFoundError` for Python package | Package not in container | Add `pip install` or `micromamba install` to Dockerfile |

### Resource Failures

| Error Pattern | Cause | Fix |
|---------------|-------|-----|
| `MemoryError` or OOM killed | Insufficient memory allocation | Increase `.add_pegasus_profile(memory="N GB")` |
| `Bus error` (signal 7) | Memory or I/O issue | Increase memory; check for large temporary files |
| Job timeout | Step takes too long | Increase timeout; optimize the tool call |

### Argument Parsing Failures

| Error Pattern | Cause | Fix |
|---------------|-------|-----|
| `unrecognized arguments` | Mismatch between `add_args()` and wrapper's argparse | Align argument names in both files |
| `the following arguments are required` | Missing argument in `add_args()` | Add the missing `--flag` to the job's `add_args()` |
| `error: argument --input: expected one argument` | Argument value contains spaces or is missing | Quote values or check argument construction |

### Dependency Failures

| Error Pattern | Cause | Fix |
|---------------|-------|-----|
| Job runs before its input is ready | Missing dependency between jobs | Ensure `File` objects are shared between producer `add_outputs()` and consumer `add_inputs()` |
| Circular dependency error | Circular file references | Check that no file is both input and output of the same job |
| `mkdir` job not running first | Missing explicit dependency on mkdir | Add `self.wf.add_dependency(mkdir_job, children=[first_job])` |

### Wrapper Script Failures

| Error Pattern | Cause | Fix |
|---------------|-------|-----|
| Exit code 1 but no stderr | Wrapper doesn't capture/print stderr | Add `print(result.stderr, file=sys.stderr)` |
| `Permission denied` on wrapper script | Script not executable | `chmod +x bin/script.py` or add shebang line |
| Output file not created | Tool succeeded but output path doesn't match | Verify output filename in wrapper matches `File()` LFN |

## Step 4: Read Relevant Source Files

Based on the identified failure pattern, read:

1. The **wrapper script** that failed — check argparse, `os.makedirs`, subprocess calls
2. The **workflow_generator.py** — check the job's `add_args()`, `add_inputs()`, `add_outputs()`
3. The **Dockerfile** — check if the tool is installed
4. The **Replica Catalog** entries — check file registrations

## Step 5: Propose Fix

Provide a specific, actionable fix:

1. **Show the exact code change** needed (diff-style or before/after)
2. **Explain why** the error occurred (root cause, not just symptoms)
3. **Show how to verify** the fix:
   - For argument mismatches: `python3 bin/wrapper.py --help`
   - For container issues: `docker run --rm image:tag which tool`
   - For file staging: check Replica Catalog entries
   - For the whole workflow: `python3 workflow_generator.py --help`

## Step 6: Prevention Advice

After fixing the immediate issue, suggest:

1. Run `/pegasus-review` to catch other potential issues
2. Use `run_manual.sh` to test each step locally before Pegasus submission
3. Check the "Common File Staging Pitfalls" table in references/PEGASUS.md
