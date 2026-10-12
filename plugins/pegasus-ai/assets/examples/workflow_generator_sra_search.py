#!/usr/bin/env python3

"""
Pegasus workflow generator for searching the SRA database.

For each SRA ID in a list: download the reads (fasterq-dump, at most 20 at a
time), align them against a reference indexed once with bowtie2-build, then
merge every BAM into one results.tar.gz through an upside-down tree of merge
jobs (at most 25 inputs per merge).

Usage:
    ./sra-search.py --sra-id-list examples/1/sra_ids.txt \
                    --reference examples/1/crassphage.fna

Sites follow pegasus-isi/pegasus-gromacs: jobs run on a site named "compute",
defined by a centrally hosted site catalog (-s access-pegasus.yml, ...;
https://github.com/pegasushub/pegasus-site-catalogs) or by one in
~/.pegasusrc. On a plain HTCondor pool with no site catalog, use
-e condorpool. The generator writes no site catalog and never submits: it
writes the workflow and catalogs and prints the pegasus-plan command.

This module is importable (the notebook SRA-Search-Workflow.ipynb uses it);
sra-search.py is the command-line entry point.
"""

import argparse
import logging
import os
import sys
from pathlib import Path

from Pegasus.api import *

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# Per-tool resource configuration for the transformation catalog.
TOOL_CONFIGS = {
    "bowtie2-build": {"memory": "1 GB"},
    "fasterq-dump": {"memory": "1 GB"},
    "bowtie2": {"memory": "2 GB"},
    "merge": {"memory": "1 GB"},
}


def add_merge_jobs(wf, parents):
    '''
    an upside down triangle of merge jobs to merge a set of bam
    files into a final tarball.
    parents is a list of jobs, for which all outputs will be
    in the resulting tarball
    '''

    max_parents = 25
    final_job = False
    level = 1
    while len(parents) >= 1:
        children = []
        if len(parents) <= max_parents:
            final_job = True
        chunks = [parents[i:i + max_parents] for i in range(0, len(parents), max_parents)]
        job_count = 0
        for chunk in chunks:
            job_count += 1
            j = Job('merge')
            wf.add_jobs(j)
            # outputs
            out_file = File('results-l{}-j{}.tar.gz'.format(level, job_count))
            if final_job:
                out_file = File('results.tar.gz')
            j.add_outputs(out_file, stage_out=final_job)
            j.add_args(out_file)
            # inputs and parent deps
            for parent in chunk:
                j.add_inputs(*parent.get_outputs())
                j.add_args(*parent.get_outputs())
            wf.add_dependency(j, parents=chunk)
            if not final_job:
                children.append(j)
        # next round
        level += 1
        parents = children


class SraSearchWorkflow:
    """Pegasus workflow for searching SRA reads against a reference."""

    wf = None
    sc = None
    tc = None
    rc = None
    props = None

    dagfile = None
    wf_dir = None
    shared_scratch_dir = None
    local_storage_dir = None
    wf_name = "sra-search"

    def __init__(self, sra_id_list, reference, dagfile="workflow.yml"):
        self.sra_id_list = sra_id_list
        self.reference = reference
        self.dagfile = dagfile
        self.wf_dir = str(Path(__file__).parent.resolve())
        self.shared_scratch_dir = os.path.join(self.wf_dir, "scratch")
        self.local_storage_dir = os.path.join(self.wf_dir, "output")

    def write(self):
        """Write all catalogs and workflow to files."""
        if self.sc is not None:
            self.sc.write()
        self.props.write()
        self.rc.write()
        self.tc.write()
        self.wf.write(file=self.dagfile)

    # ------------------------------------------------------------------
    # Plan / run / monitor (thin wrappers over the Pegasus API Workflow
    # object, for interactive use e.g. from a Jupyter notebook)
    # ------------------------------------------------------------------
    def plan_submit(self, exec_site_name="compute", raise_errors=False):
        try:
            self.wf.plan(
                dir="submit",
                sites=[exec_site_name],
                output_sites=["local"],
                cleanup="none",
                verbose=1,
                submit=True,
            )
        except PegasusClientError as e:
            print(e)
            if raise_errors:
                raise

    def status(self):
        try:
            self.wf.status(long=True)
        except PegasusClientError as e:
            print(e)

    def wait(self):
        try:
            self.wf.wait()
        except PegasusClientError as e:
            print(e)

    def statistics(self):
        try:
            self.wf.statistics()
        except PegasusClientError as e:
            print(e)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------
    def create_pegasus_properties(self, hosted_site_catalog=None):
        self.props = Properties()
        self.props["pegasus.transfer.threads"] = "16"
        # Limit the number of concurrent downloads (the fasterq-dump jobs
        # carry dagman category "fasterq-dump").
        self.props["dagman.fasterq-dump.maxjobs"] = "20"
        # Send some extra usage data to the Pegasus developers.
        self.props["pegasus.catalog.workflow.amqp.url"] = (
            "amqp://friend:donatedata@msgs.pegasus.isi.edu:5672/prod/workflows"
        )
        if hosted_site_catalog:
            # Use one of Pegasus' centrally hosted site catalogs instead of
            # a locally generated one. pegasus-plan downloads and caches the
            # named file from the catalog repository at plan time.
            # https://pegasus.isi.edu/documentation/reference-guide/catalogs.html#centrally-hosted-site-catalogs
            self.props["pegasus.catalog.site.repo.file"] = hosted_site_catalog

    # ------------------------------------------------------------------
    # Site Catalog
    #
    # Not used by the CLI below by default — pegasus-plan resolves the site
    # catalog from a centrally hosted one instead (see -s/--hosted-site-catalog
    # and create_pegasus_properties above). Kept for programmatic/notebook use
    # when a self-contained, locally generated HTCondor site catalog is wanted.
    # ------------------------------------------------------------------
    def create_sites_catalog(self, exec_site_name="compute"):
        self.sc = SiteCatalog()

        local = Site("local").add_directories(
            Directory(
                Directory.SHARED_SCRATCH, self.shared_scratch_dir
            ).add_file_servers(
                FileServer("file://" + self.shared_scratch_dir, Operation.ALL)
            ),
            Directory(
                Directory.LOCAL_STORAGE, self.local_storage_dir
            ).add_file_servers(
                FileServer("file://" + self.local_storage_dir, Operation.ALL)
            ),
        )

        exec_site = (
            Site(exec_site_name)
            .add_condor_profile(universe="vanilla")
            .add_pegasus_profile(style="condor")
        )

        self.sc.add_sites(local, exec_site)

    # ------------------------------------------------------------------
    # Transformation Catalog
    # ------------------------------------------------------------------
    def create_transformation_catalog(self, exec_site_name="compute"):
        self.tc = TransformationCatalog()

        # A local .sif built with `apptainer build` (container/sra.def).
        # Pegasus stages it like any other input; image_site is where the
        # .sif physically lives (the submit host).
        container = Container(
            "sra-search",
            container_type=Container.SINGULARITY,
            image=f"file://{self.wf_dir}/container/sra.sif",
            image_site="local",
        )

        # bowtie2-build is installed inside the image (not staged), so its
        # site is Pegasus's reserved "incontainer": the executable lives in
        # the container wherever the job runs.
        bowtie2_build = Transformation(
            "bowtie2-build",
            site="incontainer",
            container=container,
            pfn="/opt/bowtie2/bowtie2-build",
            is_stageable=False,
        ).add_pegasus_profile(memory=TOOL_CONFIGS["bowtie2-build"]["memory"])

        # The wrappers are stageable scripts on the submit host, registered
        # on the execution site and shipped to the job.
        bowtie2 = Transformation(
            "bowtie2",
            site=exec_site_name,
            container=container,
            pfn=os.path.join(self.wf_dir, "executables/bowtie2_wrapper"),
            is_stageable=True,
        ).add_pegasus_profile(memory=TOOL_CONFIGS["bowtie2"]["memory"])

        fasterq_dump = Transformation(
            "fasterq-dump",
            site=exec_site_name,
            container=container,
            pfn=os.path.join(self.wf_dir, "executables/fasterq_dump_wrapper"),
            is_stageable=True,
        ).add_pegasus_profile(memory=TOOL_CONFIGS["fasterq-dump"]["memory"])
        # this one is used to limit the number of concurrent downloads
        fasterq_dump.add_profiles(Namespace.DAGMAN, key="category", value="fasterq-dump")

        merge = Transformation(
            "merge",
            site=exec_site_name,
            container=container,
            pfn=os.path.join(self.wf_dir, "executables/merge"),
            is_stageable=True,
        ).add_pegasus_profile(memory=TOOL_CONFIGS["merge"]["memory"])

        self.tc.add_containers(container)
        self.tc.add_transformations(bowtie2_build, bowtie2, fasterq_dump, merge)

    # ------------------------------------------------------------------
    # Replica Catalog
    # ------------------------------------------------------------------
    def create_replica_catalog(self):
        self.rc = ReplicaCatalog()
        self.rc.add_replica(
            "local", "reference.fna", "file://" + os.path.abspath(self.reference)
        )

    # ------------------------------------------------------------------
    # Workflow DAG
    # ------------------------------------------------------------------
    def create_workflow(self):
        self.wf = Workflow(self.wf_name)

        # keep track of bam files, so we can merge them into a single tarball at
        # the end
        to_merge = []

        # set up reference file and what files needs to be generated by the index job
        ref_main = File("reference.fna")
        ref_files = []
        for filename in ["reference.1.bt2", "reference.2.bt2", "reference.3.bt2", "reference.4.bt2",
                         "reference.rev.1.bt2", "reference.rev.2.bt2"]:
            ref_files.append(File(filename))

        # index the reference file
        index_job = Job("bowtie2-build")
        index_job.add_args("reference.fna", "reference")
        index_job.add_inputs(ref_main)
        index_job.add_outputs(*ref_files, stage_out=False)
        self.wf.add_jobs(index_job)

        # create jobs for each SRA ID
        for sra_id in read_sra_ids(self.sra_id_list):
            # files for this id
            fastq_1 = File("{}_1.fastq".format(sra_id))
            fastq_2 = File("{}_2.fastq".format(sra_id))

            # download job
            j = Job("fasterq-dump")
            j.add_args("--split-files", sra_id)
            j.add_outputs(fastq_1, fastq_2, stage_out=False)
            self.wf.add_jobs(j)

            # bowtie2 job
            bam = File("{}.bam".format(sra_id))
            bam_index = File("{}.bam.bai".format(sra_id))
            j = Job("bowtie2")
            j.add_args(sra_id)
            j.add_inputs(*ref_files, fastq_1, fastq_2)
            j.add_outputs(bam, bam_index, stage_out=False)
            self.wf.add_jobs(j)

            # keep track of jobs and outputs for merging
            to_merge.append(j)

        add_merge_jobs(self.wf, to_merge)


def read_sra_ids(sra_id_list):
    """SRA IDs from a file with one ID per line (lines under 5 chars skipped)."""
    ids = []
    with open(sra_id_list) as fh:
        for line in fh:
            sra_id = line.strip()
            if len(sra_id) < 5:
                continue
            ids.append(sra_id)
    return ids


# ======================================================================
# main() — CLI argument parsing
# ======================================================================
def main():
    parser = argparse.ArgumentParser(
        description="Generate the sra-search Pegasus workflow",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --sra-id-list examples/1/sra_ids.txt --reference examples/1/crassphage.fna
  %(prog)s ... -s access-pegasus.yml
  %(prog)s ... -e condorpool     # plain HTCondor pool, no site catalog

Writes the workflow and its catalogs; it does not plan or submit. Plan with
the command it prints, or from the notebook (plan_submit()).
""",
    )
    parser.add_argument("--sra-id-list", dest="sra_id_list", required=True,
                        help="Specifies list of SRA IDs to include in the search")
    parser.add_argument("--reference", dest="reference", required=True,
                        help="Specifies the fasta file to use as a reference for the search")

    # --- Standard Pegasus arguments ---
    parser.add_argument(
        "-s",
        "--hosted-site-catalog",
        metavar="FILE",
        type=str,
        default=None,
        help="Name of a Pegasus centrally hosted site catalog to plan against "
        "(e.g. access-pegasus.yml), instead of a locally generated one. Sets "
        "pegasus.catalog.site.repo.file; see "
        "https://pegasus.isi.edu/documentation/reference-guide/catalogs.html"
        "#centrally-hosted-site-catalogs",
    )
    parser.add_argument(
        "-e",
        "--execution-site-name",
        metavar="STR",
        type=str,
        default="compute",
        help="Execution site name (default: compute; condorpool on a plain "
        "HTCondor pool with no site catalog)",
    )
    parser.add_argument(
        "-o",
        "--output",
        metavar="STR",
        type=str,
        default="workflow.yml",
        help="Output file (default: workflow.yml)",
    )
    args = parser.parse_args(sys.argv[1:])

    for path, label in ((args.sra_id_list, "SRA ID list"), (args.reference, "reference")):
        if not os.path.isfile(path):
            logger.error(f"{label} not found: {path}")
            sys.exit(1)

    logger.info(f"SRA IDs: {len(read_sra_ids(args.sra_id_list))} from {args.sra_id_list}")
    logger.info(f"Reference: {args.reference}")
    logger.info(f"Execution site: {args.execution_site_name}")
    logger.info(
        f"Hosted site catalog: {args.hosted_site_catalog or '(none — supply your own site catalog)'}"
    )

    try:
        workflow = SraSearchWorkflow(args.sra_id_list, args.reference, dagfile=args.output)

        workflow.create_pegasus_properties(hosted_site_catalog=args.hosted_site_catalog)
        workflow.create_transformation_catalog(exec_site_name=args.execution_site_name)
        workflow.create_replica_catalog()
        workflow.create_workflow()
        workflow.write()

        logger.info(f"Workflow written to {args.output}")
        # --output-dir: with no site catalog defining "local", Pegasus's
        # built-in local site would stage outputs to ./wf-output instead.
        logger.info(
            f"Plan and submit: pegasus-plan --dir submit "
            f"-s {args.execution_site_name} -o local "
            f"--output-dir {workflow.local_storage_dir} --submit {args.output}"
        )

    except Exception as e:
        logger.error(f"Failed to generate workflow: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
