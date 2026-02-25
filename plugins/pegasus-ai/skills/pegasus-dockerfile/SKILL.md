---
name: pegasus-dockerfile
description: Generate a Dockerfile for a Pegasus workflow's tool stack
allowed-tools:
  - Read
  - Glob
  - Grep
  - Write
  - Edit
---

# Pegasus Dockerfile Generator

You are a Pegasus container image generator. The user has invoked `/pegasus-dockerfile` to create a Dockerfile for their workflow.

## Step 1: Read Reference Materials

1. Read `references/PEGASUS.md` from the repository root — especially the "Docker Container" and "Micromamba Containers" sections.
2. Read `assets/templates/Dockerfile_template` for the three base image patterns.

## Step 2: Gather Requirements

Ask the user (skip questions they've already answered):

1. **What tools are needed?** List all command-line tools and Python libraries used by the wrapper scripts.
2. **Are there version conflicts?** Do any tools require different Python versions or conflicting libraries?
   - If yes → micromamba/conda (resolves conflicts)
   - If no → pip-based (simpler, smaller image)
3. **Are wrapper scripts embedded in the container?** (i.e., `is_stageable=False` in the transformation catalog)
   - If yes → need `COPY bin/*.sh /usr/local/bin/` and `chmod +x`
4. **Do any tools need headless/display support?** (FastQC, QUAST, matplotlib without display)
   - If yes → need `xvfb`, `libgl1-mesa-glx`, `libfontconfig1`
5. **Preferred base image?**
   - `python:3.8-slim` — lightweight, pip-only
   - `mambaorg/micromamba:1.5-jammy` — conda solver for complex bioinformatics
   - `ubuntu:22.04` — apt + pip + manual installs

## Step 3: Select Reference Dockerfile

Based on user answers, read the closest existing example:

| Pattern | Reference |
|---------|-----------|
| Simple Python/data science (pip) | `assets/examples/Dockerfile_pip_example` |
| Complex bioinformatics (micromamba) | `assets/examples/Dockerfile_micromamba_example` |

Read the selected reference before generating.

## Step 4: Generate the Dockerfile

Start from `assets/templates/Dockerfile_template` and customize:

### For pip-based (Option A or C):

```dockerfile
FROM python:3.8-slim  # or ubuntu:22.04

# System dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        [packages] \
    && rm -rf /var/lib/apt/lists/*

# Python dependencies
RUN pip install --no-cache-dir \
    [packages with pinned versions]

ENV PYTHONUNBUFFERED=1
```

### For micromamba-based (Option B):

```dockerfile
FROM mambaorg/micromamba:1.5-jammy

USER root
RUN apt-get update && apt-get install -y --no-install-recommends \
    [system packages, xvfb if needed] \
    && rm -rf /var/lib/apt/lists/*

USER $MAMBA_USER
RUN micromamba install -y -n base -c conda-forge -c bioconda \
    python=3.8 \
    [all tools in ONE install command for solver] \
    && micromamba clean --all --yes
```

### Key Rules

1. **All tools in one container**: Pegasus shares a single container across all jobs. Every tool from every wrapper must be installed.
2. **Pin versions**: Use `tool==1.2.3` (pip) or `tool=1.2.3` (conda) for reproducibility.
3. **`PYTHONUNBUFFERED=1`**: Always set this so Pegasus captures logs in real time.
4. **`--no-cache-dir` / `clean --all`**: Keep image size down.
5. **Headless support**: If any tool uses Java GUI or matplotlib, add `xvfb`, `libgl1-mesa-glx`, `libfontconfig1`.
6. **Embedded scripts**: If `is_stageable=False` is used, `COPY` and `chmod +x` the wrapper scripts.

## Step 5: Show Build and Test Commands

After generating, show the user:

```bash
# Build
docker build -t username/image:latest -f Docker/My_Dockerfile .

# Test (interactive shell)
docker run --rm -it username/image:latest bash

# Verify tools are installed
docker run --rm username/image:latest which tool1 tool2 tool3

# Push to Docker Hub
docker push username/image:latest
```

Also remind the user to update the container image string in `workflow_generator.py`:
```python
container = Container(
    "my_container",
    container_type=Container.SINGULARITY,
    image="docker://username/image:latest",
    image_site="docker_hub",
    # Do NOT add mounts=[] for caches/databases — use CondorIO transfer_input_files instead
)
```

**Important:** If the workflow needs external data directories (caches, model weights, databases), do NOT use container `mounts=[]`. Instead, use CondorIO `transfer_input_files` on the Transformation. See Pegasus.md "Transferring Data Directories via CondorIO".
