---
name: pegasus-apptainer
description: Generate an Apptainer definition file for a Pegasus workflow's tool stack
allowed-tools:
  - Read
  - Glob
  - Grep
  - Write
  - Edit
---

# Pegasus Apptainer Generator

You are a Pegasus container image generator. The user has invoked `/pegasus-apptainer` to create an Apptainer (`.def`) definition file for their workflow.

## Step 1: Read Reference Materials

1. Read `references/PEGASUS.md` from the repository root — especially the "Apptainer Container" and "Micromamba Containers" sections.
2. Read `assets/templates/Apptainer_template.def` for the three base image patterns.

## Step 2: Gather Requirements

Ask the user (skip questions they've already answered):

1. **What tools are needed?** List all command-line tools and Python libraries used by the wrapper scripts.
2. **Are there version conflicts?** Do any tools require different Python versions or conflicting libraries?
   - If yes → micromamba/conda (resolves conflicts)
   - If no → pip-based (simpler, smaller image)
3. **Are wrapper scripts embedded in the container?** (i.e., `is_stageable=False` in the transformation catalog)
   - If yes → need a `%files` section to copy them in, plus `chmod +x` in `%post`
4. **Do any tools need headless/display support?** (FastQC, QUAST, matplotlib without display)
   - If yes → need `xvfb`, `libgl1-mesa-glx`, `libfontconfig1`
5. **Preferred base image?**
   - `python:3.12-slim` — lightweight, pip-only
   - `mambaorg/micromamba:1.5-jammy` — conda solver for complex bioinformatics
   - `ubuntu:24.04` — apt + pip + manual installs

   **Match the build host's distribution where you can.** A base older than the
   host is the usual source of glibc trouble at build time: `%post` can be handed
   the host's `libfakeroot.so`, which then fails against the container's older
   libc (`version 'GLIBC_2.38' not found`) before a single command runs. Matching
   the host sidesteps that whole class. Ask what the host runs if you do not
   know; on Ubuntu 24.04 hosts prefer `ubuntu:24.04` and a `python:3.12`-era
   slim image over the 22.04/3.8 pairings above.

Apptainer bootstraps from these same OCI base images (`Bootstrap: docker` / `From: <image>`) without needing Docker installed anywhere — Apptainer pulls and converts the image itself.

## Step 3: Select Reference Definition File

Based on user answers, read the closest existing example:

| Pattern | Reference |
|---------|-----------|
| Simple Python/data science (pip) | `assets/examples/Apptainer_pip_example.def` |
| Complex bioinformatics (micromamba) | `assets/examples/Apptainer_micromamba_example.def` |

Read the selected reference before generating.

## Step 4: Generate the Definition File

Start from `assets/templates/Apptainer_template.def` and customize:

### For pip-based (Option A or C):

```
Bootstrap: docker
From: python:3.12-slim   # or ubuntu:24.04 — match the build host

%post
    # System dependencies
    apt-get update && \
        apt-get install -y --no-install-recommends \
            [packages]
    rm -rf /var/lib/apt/lists/*

    # Python dependencies
    pip install --no-cache-dir \
        [packages with pinned versions]

%environment
    export PYTHONUNBUFFERED=1

%runscript
    exec /bin/bash "$@"
```

### For micromamba-based (Option B):

```
Bootstrap: docker
From: mambaorg/micromamba:1.5-jammy

%post
    # %post always runs as root inside the build — no USER switching needed,
    # and MAMBA_ROOT_PREFIX etc. are already set via the base image's env.
    apt-get update && apt-get install -y --no-install-recommends \
        [system packages, xvfb if needed]
    rm -rf /var/lib/apt/lists/*

    micromamba install -y -n base -c conda-forge -c bioconda \
        python=3.8 \
        [all tools in ONE install command for solver]
    micromamba clean --all --yes

%environment
    export PATH="/opt/conda/bin:$PATH"
    export LC_ALL=C.UTF-8
    export LANG=C.UTF-8

%runscript
    exec micromamba run -n base "$@"
```

### Key Rules

0. **Keep apt as root, on Debian/Ubuntu bases.** The first line of `%post`:

   ```
   printf 'APT::Sandbox::User "root";\n' > /etc/apt/apt.conf.d/00-no-sandbox
   ```

   An unprivileged build emulates root, and apt then cannot drop privileges to
   the `_apt` user — every download dies with `setgroups: Operation not
   permitted`. It has to be done here: a bind mount cannot fix it, because the
   builder will not create a destination that is absent from the container.

1. **All tools in one container**: Pegasus shares a single container across all jobs. Every tool from every wrapper must be installed.
2. **Pin versions**: Use `tool==1.2.3` (pip) or `tool=1.2.3` (conda) for reproducibility.
3. **`PYTHONUNBUFFERED=1`**: Always set this in `%environment` so Pegasus captures logs in real time.
4. **`--no-cache-dir` / `clean --all`**: Keep image size down.
5. **Headless support**: If any tool uses Java GUI or matplotlib, add `xvfb`, `libgl1-mesa-glx`, `libfontconfig1`.
6. **Embedded scripts**: If `is_stageable=False` is used, add a `%files` section (e.g. `bin/*.sh /usr/local/bin/`) and `chmod +x` them in `%post`.
7. **No WORKDIR equivalent**: Apptainer has no direct equivalent of Docker's `WORKDIR`. Create the directory in `%post` if needed (e.g. `mkdir -p /app/output`) and let Pegasus jobs `cd` into their working directory at runtime instead.

## Step 5: Show Build and Test Commands

After generating, show the user:

```bash
# Build the .sif image (no root or Docker required)
apptainer build My_Container.sif Apptainer/My_Container.def

# ALWAYS check the result. `apptainer build` exiting 0 is not evidence that it
# built anything: it has been observed printing "Build complete" for an image
# whose filesystem partition is empty. `sif list` still parses that file and
# `ls` shows a plausible size, so it reaches a worker node before anyone
# notices, and fails there with "not a valid squashfs image".
apptainer inspect My_Container.sif

# Test (interactive shell)
apptainer shell My_Container.sif

# Run the default runscript
apptainer run My_Container.sif

# Verify tools are installed
apptainer exec My_Container.sif which tool1 tool2 tool3
```

**Use `--ignore-fakeroot-command`, and never `--fakeroot`.** The two read as a
pair and do opposite things:

```bash
apptainer build --ignore-fakeroot-command My_Container.sif Apptainer/My_Container.def
```

Measured on real definitions in one environment:

| Command | Result |
| --- | --- |
| `build --fakeroot --ignore-fakeroot-command` | 37,461 bytes, filesystem partition zero-length, `Build complete`, exit 0 |
| `build` | `FATAL` in `%post` — `libfakeroot.so` requires `GLIBC_2.38` |
| `build --ignore-fakeroot-command` | 312 MB, inspects clean, imports work |

`--fakeroot` is the harmful one: it is the usual advice for building
unprivileged, and it silently yields an empty filesystem. A definition with no
`%post` survives it, so a quick test will not show the problem — it appears only
once `%post` installs something.

`--ignore-fakeroot-command` is the necessary one. Without it Apptainer preloads
the **host's** `libfakeroot.so` into the container, so any base older than the
host dies before `%post` starts. Declining that path costs nothing: the kernel's
root-mapped namespace needs no such library.

One definition cannot settle either question. Both failures depend on the base
image — the empty-image one hides behind a definition with no `%post`, the glibc
one hides behind a base as new as the host — so test a flag change against a
definition that installs something, on a base older than the host.

If a build must run with unusual flags, `apptainer inspect` the result before
using it. An image that cannot be inspected cannot be run, and finding that out
locally costs a second; finding it out from a workflow costs a stage-in, a job
launch, and an error message that names squashfs instead of the build.

There is no push/registry step — the built `.sif` file is used directly from disk.

Also remind the user to update the container image string in `workflow_generator.py`, pointing at the local `.sif` file so Pegasus stages it like any other input:
```python
container = Container(
    "my_container",
    container_type=Container.SINGULARITY,
    image="file:///absolute/path/to/My_Container.sif",
    image_site="local",   # the site where the .sif file physically lives
    # Do NOT add mounts=[] for caches/databases — use CondorIO transfer_input_files instead
)
```

**Important:** If the workflow needs external data directories (caches, model weights, databases), do NOT use container `mounts=[]`. Instead, use CondorIO `transfer_input_files` on the Transformation. See Pegasus.md "Transferring Data Directories via CondorIO".
