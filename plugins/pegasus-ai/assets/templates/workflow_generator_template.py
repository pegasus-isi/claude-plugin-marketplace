#!/usr/bin/env python3

"""
Pegasus workflow generator for [WORKFLOW_NAME].

[CUSTOMIZE] Describe the pipeline and what it does.

Pipeline steps:
1. [step1] - [description]
2. [step2] - [description]
3. [step3] - [description]

Usage:
    ./workflow_generator.py [CUSTOMIZE: add usage examples]

Sites: the workflow names no scheduler. Jobs state cores, memory, a wall-clock
runtime and optional tags, and plan against a site named "compute". A hosted
site catalog (-s unity.yml, ...) defines it; otherwise custom_sites.py (copy
it next to this file) writes it to sites.yml as an HTCondor pool, or for Slurm
via --site-style slurm --queue --project. See PEGASUS.md "Portable Sites".
"""

import argparse
import logging
import os
import sys
from pathlib import Path

from Pegasus.api import *

# Site-catalog handling (assets/templates/custom_sites.py, copied next to this
# file). Keeps this generator free of scheduler details.
sys.path.insert(0, str(Path(__file__).parent.resolve()))
from custom_sites import (  # noqa: E402
    HOSTED_SITE, STYLES, ensure_sites_yml, hosted_catalog, is_batch_site, parse_profile,
    parse_tag_profile, worker_package_url,
)

# [CUSTOMIZE] Add any additional imports needed for your workflow
# Examples: json, csv, glob, datetime, requests, urllib.request

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# [CUSTOMIZE] Per-tool resource configuration — the ONLY resource statements
# the workflow makes. Portable on any site: memory, cores, gpus, runtime.
# runtime is a wall-clock budget in seconds; batch sites (Slurm) refuse or kill
# jobs without one, so it is mandatory — be generous. Anything
# scheduler-specific (partition, account, GPU model, ClassAds) belongs in the
# site catalog, keyed by tag: give tools with unusual needs a "tag" ("gpu",
# "bigmem", ...) and users tune it with --tag-profile TAG:NS:KEY=VALUE.
TOOL_CONFIGS = {
    "step1": {"memory": "2 GB", "cores": 1, "runtime": 1800},
    "step2": {"memory": "4 GB", "cores": 2, "runtime": 3600},
    "step3": {"memory": "2 GB", "cores": 1, "runtime": 1800},
    # "train": {"memory": "16 GB", "cores": 4, "gpus": 1, "runtime": 4 * 3600,
    #           "tag": "gpu"},
}

# [CUSTOMIZE] The container's OS, for the Pegasus worker package staged into
# it (see PEGASUS.md "Worker package in containers"). Must match the image's
# base, not the submit host: "x86_64_ubuntu_24" for ubuntu:24.04 (the
# Apptainer template's base), "x86_64_deb_13" for debian:trixie-slim /
# python:3.x-slim-trixie. An unsuffixed python:3.x-slim tag follows Debian's
# current release, so pin the suite. For a base older than any published
# package (e.g. python:3.8-slim, Debian 11), use "x86_64_rhel_8" (glibc 2.28).
CONTAINER_PLATFORM = "x86_64_ubuntu_24"


class MyWorkflow:
    """[CUSTOMIZE] Describe your workflow class."""

    wf = None
    tc = None
    rc = None
    props = None

    dagfile = None
    wf_dir = None
    shared_scratch_dir = None
    local_storage_dir = None
    wf_name = "my_workflow"  # [CUSTOMIZE] Workflow name
    # Set by main() from the site in use (see setup_site_catalog).
    worker_package_url = None
    bind_workflow_dir = False

    def __init__(self, dagfile="workflow.yml"):
        self.dagfile = dagfile
        self.wf_dir = str(Path(__file__).parent.resolve())
        self.shared_scratch_dir = os.path.join(self.wf_dir, "scratch")
        self.local_storage_dir = os.path.join(self.wf_dir, "output")

    def write(self):
        """Write all catalogs and workflow to files."""
        self.props.write()
        self.rc.write()
        self.tc.write()
        self.wf.write(file=self.dagfile)

    # ------------------------------------------------------------------
    # Properties — rarely needs changes
    # ------------------------------------------------------------------
    def create_pegasus_properties(self, sites_yml="sites.yml",
                                  bypass_input_staging=False,
                                  hosted_site_catalog=None):
        self.props = Properties()
        self.props["pegasus.transfer.threads"] = "16"
        if hosted_site_catalog:
            # A centrally hosted site catalog (pegasushub
            # pegasus-site-catalogs) defines the execution site; pegasus-plan
            # downloads and caches it, and merges sites.yml over it.
            self.props["pegasus.catalog.site.repo.file"] = hosted_site_catalog
        # Symlink rather than copy when an input already sits on the
        # execution site. A no-op otherwise, so always on.
        self.props["pegasus.transfer.links"] = "true"
        if bypass_input_staging:
            # Jobs read inputs (notably the .sif) straight from the submit
            # host's paths. Only valid where workers share a filesystem with
            # the submit host (a Slurm cluster) — never on a condor pool
            # staging over HTCondor file transfer.
            self.props["pegasus.transfer.bypass.input.staging"] = "true"
        if self.worker_package_url:
            # Stage the container-compatible worker package named in the TC
            # (pegasus::worker) and never download one from inside a job:
            # the image may lack curl/wget, workers may lack internet, and the
            # submit host's kickstart may need a newer glibc than the image.
            self.props["pegasus.transfer.worker.package"] = "true"
            self.props["pegasus.transfer.worker.package.strict"] = "false"
            self.props["pegasus.transfer.worker.package.autodownload"] = "false"
        if os.path.isfile(sites_yml):
            # Lets pegasus-plan find sites.yml from any directory.
            self.props["pegasus.catalog.site"] = "YAML"
            self.props["pegasus.catalog.site.file"] = os.path.abspath(sites_yml)
        # [CUSTOMIZE] Add any extra properties if needed

    # ------------------------------------------------------------------
    # Transformation Catalog
    # ------------------------------------------------------------------
    def create_transformation_catalog(self):
        """Containers and transformations. Nothing here names a site:
        stageable scripts live on "local" (the submit host) and are shipped
        to wherever the job runs."""
        self.tc = TransformationCatalog()

        # Container definition
        # image points at a local .sif built with `apptainer build` — Pegasus
        # stages it like any other input file. image_site is the site where the
        # .sif physically lives (usually "local", the submit host).
        container = Container(
            "my_container",  # [CUSTOMIZE] Container name
            container_type=Container.SINGULARITY,
            image="file:///absolute/path/to/My_Container.sif",  # [CUSTOMIZE] Image
            image_site="local",
        )
        if self.bind_workflow_dir:
            # Batch sites stage inputs as symlinks into the workflow
            # directory, and PegasusLite starts containers with --no-home, so
            # without this bind every job fails with kickstart "Unable to
            # execute the specified binary" (exit 127). Never on a condor
            # pool: the directory does not exist on its workers.
            container.add_pegasus_profile(
                container_arguments=f"--bind {self.wf_dir}")

        # [CUSTOMIZE] Register each wrapper script as a transformation.
        #
        # Pattern A: Stageable scripts on the submit host (most workflows).
        #   See: tnseq-workflow, earthquake-workflow, soilmoisture-workflow
        #
        #   tx = Transformation(
        #       "step_name",
        #       site="local",
        #       pfn=os.path.join(self.wf_dir, "bin/step_name.py"),
        #       is_stageable=True,
        #       container=container,
        #   ).add_pegasus_profile(memory="2 GB", cores=1, runtime=1800)
        #
        # Pattern B: Scripts baked into the container (is_stageable=False).
        #   See: mag-workflow
        #
        #   tx = Transformation(
        #       "step_name",
        #       site="local",
        #       pfn="/usr/local/bin/step_name.sh",
        #       is_stageable=False,
        #       container=container,
        #   ).add_pegasus_profile(memory="4 GB", cores=2, runtime=3600)

        transformations = []
        for tool_name, config in TOOL_CONFIGS.items():
            tx = Transformation(
                tool_name,
                site="local",
                pfn=os.path.join(self.wf_dir, f"bin/{tool_name}.py"),
                is_stageable=True,
                container=container,
            ).add_pegasus_profile(
                memory=config["memory"],
                cores=config.get("cores", 1),
                runtime=config["runtime"],
            )
            if config.get("gpus"):
                tx.add_pegasus_profile(gpus=config["gpus"])
            transformations.append(tx)

        # [CUSTOMIZE] Add mkdir if you need local directory creation
        # mkdir = Transformation(
        #     "mkdir", site="local", pfn="/bin/mkdir", is_stageable=False
        # )
        # transformations.append(mkdir)

        if self.worker_package_url:
            transformations.append(
                Transformation(
                    "worker",
                    namespace="pegasus",
                    site="local",
                    pfn=self.worker_package_url,
                    is_stageable=True,
                    arch=Arch.X86_64,
                    os_type=OS.LINUX,
                )
            )

        self.tc.add_containers(container)
        self.tc.add_transformations(*transformations)

    # ------------------------------------------------------------------
    # Replica Catalog
    # ------------------------------------------------------------------
    def create_replica_catalog(self):
        self.rc = ReplicaCatalog()

        # [CUSTOMIZE] Register input files.
        #
        # Pattern A: Local data files (tnseq-workflow)
        #   for sample in self.samples:
        #       path = os.path.join(self.data_dir, f"{sample}.fq.gz")
        #       self.rc.add_replica("local", f"{sample}.fq.gz",
        #                           "file://" + os.path.abspath(path))
        #
        # Pattern B: Support scripts called by wrappers (tnseq-workflow)
        #   jar_path = os.path.join(self.wf_dir, "bin/tool.jar")
        #   self.rc.add_replica("local", "tool.jar", "file://" + jar_path)
        #
        # Pattern C: Input is a static file at a URL — register the URL as the
        # PFN and Pegasus stages it (retries + optional checksum); no fetch job.
        # See PEGASUS.md "URL Inputs vs Fetch Jobs".
        #   self.rc.add_replica("web", "observations.csv",
        #                       "https://data.example.org/observations.csv")
        #
        # Pattern D: No input files — data fetched at runtime from an API.
        # Prefer fetching inside the consuming wrapper when one job needs it;
        # use a dedicated first fetch job (earthquake-workflow) only for
        # multi-consumer / multi-source / rate-limited cases.
        #   pass
        #
        # Pattern E: Config/catalog file generated at workflow creation time (airquality)
        #   self.rc.add_replica("local", "catalog.csv",
        #                       "file://" + os.path.join(self.wf_dir, "catalog.csv"))

    # ------------------------------------------------------------------
    # Workflow DAG
    # ------------------------------------------------------------------
    def create_workflow(self, args):
        """Create the workflow DAG.

        [CUSTOMIZE] Choose the right dependency mode:
          - Workflow(name, infer_dependencies=True)  — recommended for most
          - Workflow(name)  + explicit add_dependency() — when needed
        """
        self.wf = Workflow(self.wf_name, infer_dependencies=True)

        # [CUSTOMIZE] Choose your iteration pattern:
        #
        # Pattern A: Per-sample parallelism (tnseq-workflow)
        #   for sample in self.samples:
        #       self._add_sample_pipeline(sample)
        #
        # Pattern B: Per-region parallelism (earthquake-workflow, airquality)
        #   for region in args.regions:
        #       self._add_region_pipeline(region)
        #
        # Pattern C: Per-polygon / per-location (soilmoisture-workflow)
        #   for polygon_id in args.polygon_ids:
        #       self._add_polygon_pipeline(polygon_id)
        #
        # Pattern D: Single linear pipeline (simple workflows)
        #   self._add_pipeline(args)

        # Example: per-item parallelism
        for item in args.items:
            self._add_item_pipeline(item, args)

        # [CUSTOMIZE] Optional fan-in merge step (tnseq, airquality)
        # if len(result_files) > 1:
        #     file_args = " ".join([f"-i {f.lfn}" for f in result_files])
        #     merge_job = (
        #         Job("merge", _id="merge_all")
        #         .add_args(f"{file_args} -o merged_results.json")
        #         .add_inputs(*result_files)
        #         .add_outputs(merged, stage_out=True, register_replica=False)
        #     )
        #     self.wf.add_jobs(merge_job)

    def _add_item_pipeline(self, item, args):
        """Add jobs for a single item.

        [CUSTOMIZE] Replace with your actual pipeline logic.
        """
        # Output file declarations
        output1 = File(f"{item}_step1_output.csv")
        output2 = File(f"{item}_step2_output.json")
        output3 = File(f"{item}_step3_result.png")

        # Tools with a "tag" in TOOL_CONFIGS carry it on their jobs, so the
        # site catalog can route them (partition, GPU model, ...). Written
        # with add_profiles: add_pegasus_profile(tag=...) needs API >= 5.1.3.
        #   job.add_profiles(Namespace.PEGASUS, key="tag",
        #                    value=TOOL_CONFIGS["train"]["tag"])

        # Job 1: First step
        job1 = (
            Job("step1", _id=f"step1_{item}", node_label=f"step1_{item}")
            .add_args("--input", "input_data.csv", "--output", output1)
            # .add_inputs(input_file)  # [CUSTOMIZE] Add actual inputs
            .add_outputs(output1, stage_out=False, register_replica=False)
            .add_pegasus_profiles(label=item)
        )
        self.wf.add_jobs(job1)

        # Job 2: Second step — depends on Job 1 via shared File object
        job2 = (
            Job("step2", _id=f"step2_{item}", node_label=f"step2_{item}")
            .add_args("--input", output1, "--output", output2)
            .add_inputs(output1)
            .add_outputs(output2, stage_out=False, register_replica=False)
            .add_pegasus_profiles(label=item)
        )
        self.wf.add_jobs(job2)

        # Job 3: Final step — stage_out=True for user-facing results
        job3 = (
            Job("step3", _id=f"step3_{item}", node_label=f"step3_{item}")
            .add_args("--input", output2, "--output", output3)
            .add_inputs(output2)
            .add_outputs(output3, stage_out=True, register_replica=False)
            .add_pegasus_profiles(label=item)
        )
        self.wf.add_jobs(job3)


# ======================================================================
# main() — CLI argument parsing
# ======================================================================
def main():
    parser = argparse.ArgumentParser(
        description="[CUSTOMIZE] Workflow description",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --items foo bar --output workflow.yml
  %(prog)s --items foo -s unity.yml --project my_lab
  %(prog)s --items foo --site-style slurm --queue cpu --project my_lab
""",
    )

    # --- Standard Pegasus arguments (keep these) ---
    # Execution site. Every option has a default, so a zero-argument run (the
    # Pegasus Studio "Run" button) plans on "compute": the hosted catalog's
    # site when one is named, else an HTCondor pool written to sites.yml; the
    # rest tailor sites.yml for a batch cluster. dest "execution_site" is what
    # Studio matches to keep its "Where it runs" choice in sync.
    parser.add_argument(
        "-e",
        "--execution-site",
        "--execution-site-name",
        dest="execution_site",
        metavar="STR",
        type=str,
        default=HOSTED_SITE,
        help=f"Site to plan against (default: {HOSTED_SITE!r}, the name "
             "hosted catalogs give their site)",
    )
    parser.add_argument(
        "-s",
        "--hosted-site-catalog",
        metavar="FILE",
        help="Centrally hosted site catalog to plan against, e.g. unity.yml "
             "(github.com/pegasushub/pegasus-site-catalogs); written to "
             "pegasus.properties. Default: the one named in ~/.pegasusrc, "
             "if any.",
    )
    parser.add_argument(
        "--site-style",
        choices=("auto",) + STYLES + ("none",),
        default="auto",
        help="auto (default): keep a sites.yml entry or hosted catalog if one "
             "exists, else add an HTCondor site. condor/slurm: (re)write this "
             "site's entry. none: leave sites.yml alone.",
    )
    parser.add_argument("--queue", metavar="PARTITION",
                        help="Batch partition/queue jobs submit to")
    parser.add_argument("--project", metavar="ACCOUNT",
                        help="Allocation/account charged on a batch site")
    parser.add_argument("--site-scratch", metavar="DIR",
                        help="Slurm: shared scratch visible to workers and "
                             "the submit host (default: ./work)")
    parser.add_argument("--site-profile", action="append", default=[],
                        type=parse_profile, metavar="NS:KEY=VALUE",
                        help="Extra profile on the execution site; repeatable")
    parser.add_argument("--tag-profile", action="append", default=[],
                        type=parse_tag_profile, metavar="TAG:NS:KEY=VALUE",
                        help="Profile for jobs carrying a tag, e.g. "
                             "gpu:pegasus:queue=gpu; repeatable")
    parser.add_argument("--shared-filesystem", choices=("auto", "yes", "no"),
                        default="auto",
                        help="Let jobs read inputs directly from the submit "
                             "host. auto: on for Slurm sites, off for HTCondor.")
    parser.add_argument("--sites-yml", metavar="FILE", default="sites.yml",
                        help="Local site catalog (default: sites.yml)")
    parser.add_argument("--skip-sites-catalog", action="store_true",
                        help="Deprecated: same as --site-style none")
    parser.add_argument(
        "-o",
        "--output",
        metavar="STR",
        type=str,
        default="workflow.yml",
        help="Output file (default: workflow.yml)",
    )

    # --- [CUSTOMIZE] Workflow-specific arguments ---
    #
    # Pattern A: Explicit items (earthquake --regions, soilmoisture --polygon-ids)
    parser.add_argument(
        "--items",
        type=str,
        nargs="+",
        required=True,
        help="Items to process in parallel",
    )

    # Pattern B: Samplesheet input (mag-workflow)
    # parser.add_argument("--samplesheet", type=str, help="CSV samplesheet")

    # Pattern C: Test mode with auto-download (mag-workflow)
    # parser.add_argument("--test", action="store_true",
    #                     help="Download test data and run with minimal settings")

    # Pattern D: Date range (earthquake, soilmoisture, airquality)
    # parser.add_argument("--start-date", type=str, required=True)
    # parser.add_argument("--end-date", type=str, default=None)

    # Pattern E: Skip flags for conditional DAG (mag, airquality)
    # parser.add_argument("--skip-step2", action="store_true")
    # parser.add_argument("--skip-step3", action="store_true")

    args = parser.parse_args()

    # --- [CUSTOMIZE] Input validation ---
    # if not args.test and not args.samplesheet:
    #     print("Error: Either --test or --samplesheet must be provided")
    #     sys.exit(1)

    logger.info("=" * 70)
    logger.info("MY WORKFLOW GENERATOR")  # [CUSTOMIZE]
    logger.info("=" * 70)
    logger.info(f"Items: {args.items}")
    logger.info(f"Execution site: {args.execution_site}")
    logger.info(f"Output file: {args.output}")
    logger.info("=" * 70)

    try:
        workflow = MyWorkflow(dagfile=args.output)

        # --- Site catalog and the settings that depend on the site ---
        if args.skip_sites_catalog:
            args.site_style = "none"
        action, style = ensure_sites_yml(
            args.sites_yml, args.execution_site, workflow.wf_dir,
            style=args.site_style, hosted=args.hosted_site_catalog,
            queue=args.queue, project=args.project,
            scratch=args.site_scratch, profiles=args.site_profile,
            tag_profiles=args.tag_profile)
        hosted = hosted_catalog(args.hosted_site_catalog)
        logger.info(f"Site catalog: {args.sites_yml}: {action}"
                    + (f" (merged over hosted {hosted})" if hosted else ""))
        if (style is None and hosted and args.execution_site != "local"
                and args.execution_site != HOSTED_SITE):
            # Nothing was written for this site, so planning works only if
            # the hosted catalog happens to define it.
            logger.warning(
                f"{args.execution_site!r} is not defined in {args.sites_yml} "
                f"and hosted catalogs normally define only {HOSTED_SITE!r}: "
                f"pegasus-plan will fail unless {hosted} has it. Use "
                f"-e {HOSTED_SITE}, or --site-style condor/slurm to describe "
                f"{args.execution_site!r}.")
        if args.shared_filesystem == "auto":
            bypass = style is not None and style != "condor"
        else:
            bypass = args.shared_filesystem == "yes"
        workflow.bind_workflow_dir = bypass or is_batch_site(
            style, args.hosted_site_catalog)
        workflow.worker_package_url = worker_package_url(CONTAINER_PLATFORM)
        if not workflow.worker_package_url:
            logger.warning("pegasus-version not found: Pegasus will choose the "
                           "container's worker package itself (needs curl/wget "
                           "in the image and internet on the workers)")

        workflow.create_pegasus_properties(
            sites_yml=args.sites_yml, bypass_input_staging=bypass,
            hosted_site_catalog=args.hosted_site_catalog)
        workflow.create_transformation_catalog()
        workflow.create_replica_catalog()
        workflow.create_workflow(args)
        workflow.write()

        logger.info(f"\nWorkflow written to {args.output}")
        logger.info(
            f"Submit: pegasus-plan --submit "
            f"-s {args.execution_site} -o local {args.output}"
        )

    except Exception as e:
        logger.error(f"Failed to generate workflow: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
