#!/usr/bin/env python3

"""[CUSTOMIZE] Description of what this pipeline step does.

This wrapper script is invoked by Pegasus as a job. It:
1. Parses arguments matching what workflow_generator.py passes via add_args()
2. Creates output directories as needed
3. Runs the underlying tool via subprocess (or calls a Python library directly)
4. Propagates exit codes so Pegasus can detect failures
5. On ANY failure, leaves an empty file at every declared output before
   exiting non-zero (see fail() below) — otherwise HTCondor HOLDS the job
   instead of failing it, and the error message is lost

References:
  - tnseq-workflow/bin/clip.py — subprocess wrapper calling a Java tool
  - earthquake-workflow/bin/fetch_earthquake_data.py — API fetch wrapper
  - soilmoisture-workflow/bin/analyze_moisture.py — pure-Python analysis
"""

import argparse
import logging
import os
import subprocess
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Every file this job declares with add_outputs() in workflow_generator.py.
# Set right after parsing arguments, so fail() and the crash handler at the
# bottom know what to leave behind.
DECLARED_OUTPUTS: list[str] = []


def leave_empty_outputs() -> None:
    """Create an empty file at each declared output that does not exist.

    HTCondor transfers a job's declared outputs back *before* Pegasus looks at
    the exit code. If one is missing, the transfer fails and the job is HELD
    ("Transfer output files failure … No such file or directory"), its stdout
    and stderr never come back, and the run hangs until the hold times out.
    With an empty file in place the transfer succeeds, the non-zero exit marks
    the job failed, and pegasus-analyzer shows the real error. The empty file is
    never staged out: a failed job's outputs are not used.
    """
    for path in DECLARED_OUTPUTS:
        if path and not os.path.exists(path):
            out_dir = os.path.dirname(path)
            if out_dir:
                os.makedirs(out_dir, exist_ok=True)
            open(path, "a").close()


def fail(message: str, code: int = 1) -> None:
    """Report an error and exit non-zero — the only way this script exits early.

    Use it instead of a bare sys.exit(1) anywhere before the outputs are
    written (argument checks, missing inputs, empty data, a failed tool).
    """
    logger.error(message)
    leave_empty_outputs()
    sys.exit(code)


def main():
    parser = argparse.ArgumentParser(description="[CUSTOMIZE] Step description")

    # [CUSTOMIZE] Arguments must match what workflow_generator.py passes
    # in the Job's add_args() call.
    parser.add_argument("--input", required=True, help="Input file")
    parser.add_argument("--output", required=True, help="Output file")
    parser.add_argument("--threads", type=int, default=1, help="Thread count")

    # [CUSTOMIZE] For fan-in jobs that accept multiple files:
    # parser.add_argument("--input", action="append", required=True,
    #                     help="Input file (can be specified multiple times)")

    # [CUSTOMIZE] For API-fetching jobs:
    # parser.add_argument("--region", required=True, help="Region name")
    # parser.add_argument("--start-date", required=True, help="Start date")

    args = parser.parse_args()

    # [CUSTOMIZE] List EVERY output the generator declares for this job.
    DECLARED_OUTPUTS.extend([args.output])

    # Validate before doing work — and fail through fail(), never sys.exit():
    # if not os.path.isfile(args.input):
    #     fail(f"Input not found: {args.input}")

    # Log inputs for debugging via pegasus-analyzer
    logger.info(f"Input: {args.input}")
    logger.info(f"Output: {args.output}")

    # Create output directory if needed (Pegasus job dirs are flat)
    out_dir = os.path.dirname(args.output)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    # ==================================================================
    # [CUSTOMIZE] Choose your execution pattern:
    # ==================================================================

    # --- Pattern A: subprocess call to an external tool ---
    # (See tnseq-workflow/bin/clip.py, bwa_mem.py)
    cmd = [
        "mytool",
        "--input", args.input,
        "--output", args.output,
        "--threads", str(args.threads),
    ]

    logger.info(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    print(result.stdout)
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        fail(f"mytool exited {result.returncode}", result.returncode)

    # --- Pattern B: shell command with pipes ---
    # (See tnseq-workflow/bin/genomecov.py)
    # cmd = f"tool1 {args.input} | tool2 > {args.output}"
    # result = subprocess.run(cmd, shell=True, capture_output=True, text=True)

    # --- Pattern C: API fetch (no subprocess) ---
    # (See earthquake-workflow/bin/fetch_earthquake_data.py)
    # import requests
    # response = requests.get(api_url, params=params, timeout=60)
    # response.raise_for_status()
    # with open(args.output, "w") as f:
    #     f.write(response.text)

    # --- Pattern D: Pure Python analysis ---
    # (See soilmoisture-workflow/bin/analyze_moisture.py)
    # import pandas as pd
    # df = pd.read_csv(args.input)
    # results = analyze(df)
    # results.to_json(args.output)

    # --- Pattern E: Support file in working directory ---
    # Pegasus stages support files (R scripts, JARs) into the job's cwd
    # when they are added to the Replica Catalog + job inputs.
    # (See tnseq-workflow/bin/clip.py — je_jar, tab_generate.py — tab.R)
    # script_path = os.path.join(os.getcwd(), "analysis.R")

    # Verify output was created. fail(), not sys.exit(1): exiting with the
    # output missing is exactly what makes HTCondor hold the job.
    if not os.path.exists(args.output):
        fail(f"Expected output not found: {args.output}")

    logger.info(f"Output: {args.output}")


if __name__ == "__main__":
    try:
        main()
    except SystemExit as e:
        # Any stray sys.exit() lands here too. An argparse error does as well,
        # but before DECLARED_OUTPUTS is known, so it still holds the job:
        # keep this script's flags in step with the generator's add_args().
        if e.code not in (0, None):
            leave_empty_outputs()
        raise
    except Exception:
        # An unexpected crash: log the traceback, leave the outputs, fail.
        logger.exception("Step failed")
        leave_empty_outputs()
        sys.exit(1)
