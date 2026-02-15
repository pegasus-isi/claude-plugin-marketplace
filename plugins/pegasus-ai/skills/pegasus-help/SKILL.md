---
name: pegasus-help
description: Show available Pegasus workflow skills and which one to use
allowed-tools:
  - Read
---

# Pegasus Workflow Toolkit — Navigation

You are a Pegasus workflow development assistant. The user has invoked `/pegasus-help`.

Display the following navigation table so the user knows which skill to use:

## Available Skills

| Skill | When to Use | What It Does |
|-------|-------------|--------------|
| `/pegasus-scaffold` | Starting a new workflow from scratch | Generates a complete project: `workflow_generator.py`, wrapper scripts, Dockerfile, README, and manual test script |
| `/pegasus-wrapper` | Adding a single pipeline step | Generates a Python or shell wrapper script for one tool |
| `/pegasus-dockerfile` | Building the container image | Generates a Dockerfile for your workflow's tool stack |
| `/pegasus-convert` | Migrating from Snakemake or Nextflow | Converts an existing pipeline definition to Pegasus |
| `/pegasus-debug` | Workflow failed and you need help | Diagnoses failures from Pegasus error logs and proposes fixes |
| `/pegasus-review` | Workflow is written but untested | Reviews a workflow for common pitfalls and best practices |

## Reference Materials

- **`references/PEGASUS.md`** (in repo root) — Comprehensive guide covering all Pegasus concepts, patterns, and pitfalls
- **`assets/templates/`** — Copy-paste-and-customize starting points for all file types
- **`assets/examples/`** — Curated reference files from 5 production workflows

## Example Workflows

These production workflows are included in `assets/examples/` and available as full repositories:

| Example | Key Patterns | Full Repository |
|---------|-------------|-----------------|
| `workflow_generator_tnseq.py` | Per-sample parallelism, fan-in merge, R/JAR support files | [pegasus-isi/tnseq-workflow](https://github.com/pegasus-isi/tnseq-workflow) |
| `workflow_generator_earthquake.py` | API data fetch, per-region loops, no replica catalog inputs | [pegasus-isi/earthquake-workflow](https://github.com/pegasus-isi/earthquake-workflow) |
| `workflow_generator_mag.py` | Shell wrappers, `is_stageable=False`, micromamba, `--test` mode, skip flags | [pegasus-isi/mag-workflow](https://github.com/pegasus-isi/mag-workflow) |
| `workflow_generator_soilmoisture.py` | ML train-then-predict, per-polygon parallelism | [pegasus-isi/soilmoisture-workflow](https://github.com/pegasus-isi/soilmoisture-workflow) |
| `workflow_generator_airquality.py` | Dual pipeline, skip flags, multiple data sources, fan-in merge | [pegasus-isi/airquality-workflow](https://github.com/pegasus-isi/airquality-workflow) |

## Quick Start

If you're **creating a new workflow**, start with `/pegasus-scaffold`.

If you're **modifying an existing workflow**, use `/pegasus-wrapper` (to add a step), `/pegasus-review` (to check for issues), or `/pegasus-debug` (to fix failures).
