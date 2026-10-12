#!/usr/bin/env python3

"""
MAG (Metagenome-Assembled Genomes) Workflow Generator for Pegasus WMS

This script generates a Pegasus workflow for metagenomic assembly, binning,
and annotation - equivalent to the nf-core/mag Nextflow pipeline.

Pipeline steps:
1. Quality Control (FastQC, fastp)
2. Assembly (MEGAHIT or SPAdes)
3. Assembly QC (QUAST)
4. Gene Prediction (Prodigal)
5. Binning (MetaBAT2)
6. Bin Quality Assessment (CheckM2)
7. Taxonomic Classification (GTDB-Tk)
8. Genome Annotation (Prokka)
9. Report Generation (MultiQC)

Usage:
    ./workflow_generator.py --samplesheet samples.csv --output workflow.yml

    # A centrally hosted site catalog, or a plain HTCondor pool:
    ./workflow_generator.py --samplesheet samples.csv --hosted-site-catalog unity.yml
    ./workflow_generator.py --test -e condorpool

Sites follow pegasus-isi/pegasus-gromacs: jobs run on a site named "compute",
defined by a centrally hosted site catalog (--hosted-site-catalog unity.yml,
...; https://github.com/pegasushub/pegasus-site-catalogs) or by one in
~/.pegasusrc. The generator writes no site catalog and never submits; it
prints the pegasus-plan command. MAG-Workflow.ipynb drives the same class
interactively.
"""

import argparse
import csv
import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Pegasus imports
try:
    from Pegasus.api import (
        Directory, Job, File, FileServer, Operation, PegasusClientError,
        Properties, Site, SiteCatalog, Transformation, TransformationCatalog,
        Container, ReplicaCatalog, Workflow
    )
except ImportError:
    print("Error: Pegasus Python API not found.")
    print("Install with: pip install pegasus-wms.api")
    sys.exit(1)


# Default container image
# Local Apptainer image, relative to this file's directory. Build it with
# `apptainer build` (see Apptainer/MAG_Container.def); Pegasus stages the .sif
# like any other input file.
DEFAULT_CONTAINER = "Apptainer/MAG_Container.sif"

# Test data configuration
TEST_DATA_BASE_URL = "https://github.com/nf-core/test-datasets/raw/mag/test_data"
TEST_SAMPLES = [
    {
        "sample": "test_minigut",
        "group": "minigut",
        "fastq_1": f"{TEST_DATA_BASE_URL}/test_minigut_R1.fastq.gz",
        "fastq_2": f"{TEST_DATA_BASE_URL}/test_minigut_R2.fastq.gz",
    },
    {
        "sample": "test_minigut_sample2",
        "group": "minigut",
        "fastq_1": f"{TEST_DATA_BASE_URL}/test_minigut_sample2_R1.fastq.gz",
        "fastq_2": f"{TEST_DATA_BASE_URL}/test_minigut_sample2_R2.fastq.gz",
    },
]

# Tool configurations, with memory as "<n> GB" (the API converts that to MB;
# "16GB" is passed through and the planner rejects it as non-numeric). These
# are production-scale needs (GTDB-Tk and SPAdes need more than a 16 GB node);
# on small worker nodes cap them with --max-memory-gb / --max-cores
# (apply_resource_caps). runtime is set only for tools that run longer than
# the ~2 h wall-clock hosted batch catalogs give a job by default.
TOOL_CONFIGS = {
    "fastqc": {"memory": "2 GB", "cores": 2},
    "fastp": {"memory": "4 GB", "cores": 4},
    "megahit": {"memory": "16 GB", "cores": 8, "runtime": 4 * 3600},
    "spades": {"memory": "32 GB", "cores": 16, "runtime": 8 * 3600},
    "quast": {"memory": "4 GB", "cores": 4},
    "prodigal": {"memory": "4 GB", "cores": 1},
    "metabat2": {"memory": "8 GB", "cores": 4},
    "checkm2": {"memory": "16 GB", "cores": 8},
    "gtdbtk": {"memory": "64 GB", "cores": 8, "runtime": 8 * 3600},
    "prokka": {"memory": "8 GB", "cores": 4},
    "multiqc": {"memory": "4 GB", "cores": 2},
}


def parse_samplesheet(samplesheet_path: str) -> List[Dict]:
    """
    Parse input samplesheet CSV.

    Expected format:
    sample,fastq_1,fastq_2,group
    sample1,/path/to/sample1_R1.fastq.gz,/path/to/sample1_R2.fastq.gz,group1
    """
    samples = []
    with open(samplesheet_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            sample = {
                'id': row.get('sample', row.get('id', '')),
                'fastq_1': row.get('fastq_1', row.get('R1', '')),
                'fastq_2': row.get('fastq_2', row.get('R2', '')),
                'group': row.get('group', 'default'),
                'single_end': row.get('single_end', 'false').lower() == 'true'
            }
            if sample['id'] and sample['fastq_1']:
                samples.append(sample)
    return samples


def download_test_data(output_dir: str) -> Tuple[List[Dict], str]:
    """
    Download nf-core/mag test data and generate a samplesheet.

    Args:
        output_dir: Directory to download test data to

    Returns:
        Tuple of (samples list, samplesheet path)
    """
    import urllib.request

    test_data_dir = os.path.join(output_dir, "test_data")
    os.makedirs(test_data_dir, exist_ok=True)

    print(f"Downloading nf-core/mag test data to: {test_data_dir}")
    print("-" * 60)

    downloaded_samples = []

    for sample in TEST_SAMPLES:
        sample_name = sample["sample"]
        print(f"\nSample: {sample_name}")

        # Download R1
        r1_filename = os.path.basename(sample["fastq_1"])
        r1_path = os.path.join(test_data_dir, r1_filename)
        if not os.path.exists(r1_path):
            print(f"  Downloading {r1_filename}...")
            try:
                urllib.request.urlretrieve(sample["fastq_1"], r1_path)
            except Exception as e:
                print(f"  Error downloading R1: {e}")
                continue
        else:
            print(f"  [SKIP] {r1_filename} already exists")

        # Download R2
        r2_filename = os.path.basename(sample["fastq_2"])
        r2_path = os.path.join(test_data_dir, r2_filename)
        if not os.path.exists(r2_path):
            print(f"  Downloading {r2_filename}...")
            try:
                urllib.request.urlretrieve(sample["fastq_2"], r2_path)
            except Exception as e:
                print(f"  Error downloading R2: {e}")
                continue
        else:
            print(f"  [SKIP] {r2_filename} already exists")

        downloaded_samples.append({
            'id': sample_name,
            'fastq_1': r1_path,
            'fastq_2': r2_path,
            'group': sample["group"],
            'single_end': False
        })

    # Generate samplesheet
    samplesheet_path = os.path.join(output_dir, "test_samplesheet.csv")
    with open(samplesheet_path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=["sample", "fastq_1", "fastq_2", "group"])
        writer.writeheader()
        for sample in downloaded_samples:
            writer.writerow({
                "sample": sample['id'],
                "fastq_1": sample['fastq_1'],
                "fastq_2": sample['fastq_2'],
                "group": sample['group'],
            })

    print(f"\nTest samplesheet written to: {samplesheet_path}")
    print("-" * 60)

    return downloaded_samples, samplesheet_path


def apply_resource_caps(max_memory_gb: Optional[int] = None,
                        max_cores: Optional[int] = None) -> None:
    """Cap every tool's memory/cores (small worker nodes, test-scale data)."""
    for cfg in TOOL_CONFIGS.values():
        if max_memory_gb:
            gb = int(cfg["memory"].split()[0])
            cfg["memory"] = f"{min(gb, max_memory_gb)} GB"
        if max_cores:
            cfg["cores"] = min(cfg["cores"], max_cores)


def create_properties(hosted_site_catalog: Optional[str] = None) -> Properties:
    """Pegasus properties."""
    props = Properties()
    props["pegasus.transfer.threads"] = "16"
    if hosted_site_catalog:
        # Use one of Pegasus' centrally hosted site catalogs instead of a
        # locally generated one. pegasus-plan downloads and caches the named
        # file from the catalog repository at plan time.
        # https://pegasus.isi.edu/documentation/reference-guide/catalogs.html#centrally-hosted-site-catalogs
        props["pegasus.catalog.site.repo.file"] = hosted_site_catalog
    return props


def create_sites_catalog(wf_dir: str,
                         exec_site_name: str = "compute") -> SiteCatalog:
    """Self-contained site catalog: local + an HTCondor execution site.

    Not used by the CLI — pegasus-plan resolves the site catalog from a
    centrally hosted one instead (see --hosted-site-catalog). Kept for
    notebook use when a locally generated HTCondor site catalog is wanted.
    """
    sc = SiteCatalog()
    scratch = os.path.join(wf_dir, "scratch")
    storage = os.path.join(wf_dir, "output")
    local = Site("local").add_directories(
        Directory(Directory.SHARED_SCRATCH, scratch)
        .add_file_servers(FileServer("file://" + scratch, Operation.ALL)),
        Directory(Directory.LOCAL_STORAGE, storage)
        .add_file_servers(FileServer("file://" + storage, Operation.ALL)),
    )
    exec_site = (
        Site(exec_site_name)
        .add_condor_profile(universe="vanilla")
        .add_pegasus_profile(style="condor")
    )
    sc.add_sites(local, exec_site)
    return sc


def create_transformation_catalog(
    container_image: str,
    exec_site_name: str = "compute",
) -> Tuple[TransformationCatalog, Container]:
    """Create Pegasus transformation catalog with container.

    The tool scripts live inside the container, registered on the execution
    site; the .sif lives on "local" (the submit host) and is staged.
    """
    tc = TransformationCatalog()

    # A path ending in .sif (the default) is a locally built Apptainer image.
    # Pegasus stages the file like any other input, so image_site is the site
    # where the .sif physically lives (the submit host = "local"). A full URL
    # (docker://, https://) is passed through unchanged, and a bare name still
    # means Docker Hub. The .sif suffix is the discriminator on purpose — a bare
    # registry reference like "kthare10/mag-workflow:latest" also contains a
    # slash, so testing for a path separator would misread it as a local file.
    if "://" in container_image:
        image_url = container_image
        image_site = {"http": "web", "https": "web", "file": "local"}.get(
            container_image.split("://", 1)[0], "docker_hub")
    elif not container_image.endswith(".sif"):
        image_url = "docker://" + container_image
        image_site = "docker_hub"
    else:
        sif_path = container_image if os.path.isabs(container_image) else \
            os.path.join(os.path.dirname(os.path.abspath(__file__)), container_image)
        if not os.path.exists(sif_path):
            print(f"Warning: Apptainer image not found at {sif_path} — build it "
                  f"first with: cd mag-workflow && apptainer build {sif_path} "
                  f"Apptainer/MAG_Container.def")
        image_url = "file://" + sif_path
        image_site = "local"

    # Create container
    container = Container(
        "mag_container",
        Container.SINGULARITY,
        image=image_url,
        image_site=image_site,
    )
    tc.add_containers(container)

    # Define transformations for each tool
    tools = [
        "fastqc", "fastp", "megahit", "spades", "quast",
        "prodigal", "metabat2", "checkm2", "gtdbtk", "prokka", "multiqc"
    ]

    for tool in tools:
        config = TOOL_CONFIGS.get(tool, {"memory": "4 GB", "cores": 2})
        tx = Transformation(
            tool,
            site=exec_site_name,
            pfn=f"/usr/local/bin/{tool}.sh",
            is_stageable=False,  # Scripts are inside container, don't stage from submit host
            container=container
        )
        tx.add_pegasus_profile(memory=config["memory"], cores=config["cores"])
        if "runtime" in config:
            tx.add_pegasus_profile(runtime=config["runtime"])
        # MultiQC (click) needs a UTF-8 locale; set on the tools so it holds
        # on any site catalog.
        tx.add_env(LANG="en_US.UTF-8")
        tc.add_transformations(tx)

    return tc, container


def create_replica_catalog(samples: List[Dict]) -> ReplicaCatalog:
    """Create replica catalog with input files."""
    rc = ReplicaCatalog()

    for sample in samples:
        # Add forward reads
        if sample['fastq_1'] and os.path.exists(sample['fastq_1']):
            rc.add_replica(
                "local",
                f"{sample['id']}_R1.fastq.gz",
                f"file://{os.path.abspath(sample['fastq_1'])}"
            )

        # Add reverse reads (if paired-end)
        if not sample['single_end'] and sample['fastq_2'] and os.path.exists(sample['fastq_2']):
            rc.add_replica(
                "local",
                f"{sample['id']}_R2.fastq.gz",
                f"file://{os.path.abspath(sample['fastq_2'])}"
            )

    return rc


def create_workflow(
    samples: List[Dict],
    assembler: str = "megahit",
    skip_binning: bool = False,
    skip_taxonomy: bool = False,
    skip_annotation: bool = False,
    skip_fastqc: bool = False,
    gtdbtk_db: Optional[str] = None,
    checkm2_db: Optional[str] = None
) -> Workflow:
    """
    Create the MAG Pegasus workflow.

    Workflow DAG:

    Input FASTQ files
         |
         v
    [FastQC] -----> QC Reports (optional)
         |
         v
    [fastp] -----> Trimmed reads
         |
         v
    [MEGAHIT/SPAdes] -----> Contigs
         |
         v
    [QUAST] -----> Assembly QC
         |
         v
    [Prodigal] -----> Gene predictions
         |
         v
    [MetaBAT2] -----> Genome bins
         |
         v
    [CheckM2] -----> Bin quality
         |
         v
    [GTDB-Tk] -----> Taxonomy
         |
         v
    [Prokka] -----> Annotations
         |
         v
    [MultiQC] -----> Final report
    """
    wf = Workflow("mag-workflow")

    # Track all QC files for MultiQC
    all_qc_files = []
    all_bin_dirs = []

    for sample in samples:
        sample_id = sample['id']
        is_paired = not sample['single_end']

        # Input files
        r1_input = File(f"{sample_id}_R1.fastq.gz")
        r2_input = File(f"{sample_id}_R2.fastq.gz") if is_paired else None

        # ============================================================
        # Step 1: Quality Control - FastQC (raw reads)
        # ============================================================
        if not skip_fastqc:
            fastqc_r1_html = File(f"{sample_id}_R1_fastqc.html")
            fastqc_r1_zip = File(f"{sample_id}_R1_fastqc.zip")

            fastqc_job = Job("fastqc")
            fastqc_job.add_args("--outdir", ".", "--threads", str(TOOL_CONFIGS["fastqc"]["cores"]))
            fastqc_job.add_inputs(r1_input)
            # The input FASTQ must also be on the command line: FastQC
            # with no file arguments starts its GUI and dies headless.
            fastqc_job.add_args(r1_input)
            fastqc_job.add_outputs(fastqc_r1_html, fastqc_r1_zip, stage_out=True)

            if is_paired:
                fastqc_r2_html = File(f"{sample_id}_R2_fastqc.html")
                fastqc_r2_zip = File(f"{sample_id}_R2_fastqc.zip")
                fastqc_job.add_inputs(r2_input)
                fastqc_job.add_args(r2_input)
                fastqc_job.add_outputs(fastqc_r2_html, fastqc_r2_zip, stage_out=True)
                all_qc_files.extend([fastqc_r1_zip, fastqc_r2_zip])
            else:
                all_qc_files.append(fastqc_r1_zip)

            wf.add_jobs(fastqc_job)

        # ============================================================
        # Step 2: Read Trimming - fastp
        # ============================================================
        trimmed_r1 = File(f"{sample_id}_trimmed_R1.fastq.gz")
        fastp_json = File(f"{sample_id}_fastp.json")
        fastp_html = File(f"{sample_id}_fastp.html")

        fastp_job = Job("fastp")
        fastp_job.add_args(
            "-i", r1_input,
            "-o", trimmed_r1,
            "--json", fastp_json,
            "--html", fastp_html,
            "--thread", str(TOOL_CONFIGS["fastp"]["cores"]),
            "--qualified_quality_phred", "20",
            "--length_required", "50"
        )
        fastp_job.add_inputs(r1_input)
        fastp_job.add_outputs(trimmed_r1, fastp_json, fastp_html, stage_out=True)

        if is_paired:
            trimmed_r2 = File(f"{sample_id}_trimmed_R2.fastq.gz")
            fastp_job.add_args("-I", r2_input, "-O", trimmed_r2)
            fastp_job.add_inputs(r2_input)
            fastp_job.add_outputs(trimmed_r2, stage_out=True)
        else:
            trimmed_r2 = None

        all_qc_files.append(fastp_json)
        wf.add_jobs(fastp_job)

        # ============================================================
        # Step 3: Assembly - MEGAHIT or SPAdes
        # ============================================================
        contigs = File(f"{sample_id}_contigs.fa")
        assembly_log = File(f"{sample_id}_assembly.log")

        if assembler == "megahit":
            assembly_job = Job("megahit")
            if is_paired:
                assembly_job.add_args(
                    "-1", trimmed_r1,
                    "-2", trimmed_r2,
                    "-o", f"{sample_id}_megahit",
                    "-t", str(TOOL_CONFIGS["megahit"]["cores"]),
                    "--min-contig-len", "1000"
                )
                assembly_job.add_inputs(trimmed_r1, trimmed_r2)
            else:
                assembly_job.add_args(
                    "-r", trimmed_r1,
                    "-o", f"{sample_id}_megahit",
                    "-t", str(TOOL_CONFIGS["megahit"]["cores"]),
                    "--min-contig-len", "1000"
                )
                assembly_job.add_inputs(trimmed_r1)
        else:  # spades
            assembly_job = Job("spades")
            if is_paired:
                assembly_job.add_args(
                    "-1", trimmed_r1,
                    "-2", trimmed_r2,
                    "-o", f"{sample_id}_spades",
                    "-t", str(TOOL_CONFIGS["spades"]["cores"]),
                    "--meta"
                )
                assembly_job.add_inputs(trimmed_r1, trimmed_r2)
            else:
                assembly_job.add_args(
                    "-s", trimmed_r1,
                    "-o", f"{sample_id}_spades",
                    "-t", str(TOOL_CONFIGS["spades"]["cores"]),
                    "--meta"
                )
                assembly_job.add_inputs(trimmed_r1)

        assembly_job.add_outputs(contigs, assembly_log, stage_out=True)
        # add_profiles passes the value through unconverted, and the planner
        # wants MB.
        assembly_job.add_profiles(
            Namespace.PEGASUS, key="memory",
            value=str(int(TOOL_CONFIGS[assembler]["memory"].split()[0]) * 1024))
        wf.add_jobs(assembly_job)

        # ============================================================
        # Step 4: Assembly QC - QUAST
        # ============================================================
        quast_report = File(f"{sample_id}_quast_report.tsv")
        quast_html = File(f"{sample_id}_quast_report.html")

        quast_job = Job("quast")
        quast_job.add_args(
            contigs,
            "-o", f"{sample_id}_quast",
            "--min-contig", "1000",
            "--threads", str(TOOL_CONFIGS["quast"]["cores"])
        )
        quast_job.add_inputs(contigs)
        quast_job.add_outputs(quast_report, quast_html, stage_out=True)
        wf.add_jobs(quast_job)

        all_qc_files.append(quast_report)

        # ============================================================
        # Step 5: Gene Prediction - Prodigal
        # ============================================================
        genes_faa = File(f"{sample_id}_genes.faa")
        genes_gff = File(f"{sample_id}_genes.gff")

        prodigal_job = Job("prodigal")
        prodigal_job.add_args(
            "-i", contigs,
            "-a", genes_faa,
            "-o", genes_gff,
            "-f", "gff",
            "-p", "meta"
        )
        prodigal_job.add_inputs(contigs)
        prodigal_job.add_outputs(genes_faa, genes_gff, stage_out=True)
        wf.add_jobs(prodigal_job)

        # ============================================================
        # Step 6: Binning - MetaBAT2
        # ============================================================
        if not skip_binning:
            bins_dir = File(f"{sample_id}_bins")
            depth_file = File(f"{sample_id}_depth.txt")

            # Calculate depth
            depth_job = Job("metabat2")
            depth_job.add_args(
                "jgi_summarize_bam_contig_depths",
                "--outputDepth", depth_file,
                contigs
            )
            depth_job.add_inputs(contigs)
            depth_job.add_outputs(depth_file, stage_out=True)
            wf.add_jobs(depth_job)

            # Run MetaBAT2
            metabat_job = Job("metabat2")
            metabat_job.add_args(
                "-i", contigs,
                "-a", depth_file,
                "-o", f"{sample_id}_bins/bin",
                "-m", "1500",
                "-t", str(TOOL_CONFIGS["metabat2"]["cores"])
            )
            metabat_job.add_inputs(contigs, depth_file)
            metabat_job.add_outputs(bins_dir, stage_out=True)
            wf.add_jobs(metabat_job)

            all_bin_dirs.append(bins_dir)

            # ============================================================
            # Step 7: Bin Quality - CheckM2
            # ============================================================
            checkm2_report = File(f"{sample_id}_checkm2_quality.tsv")

            checkm2_job = Job("checkm2")
            checkm2_job.add_args(
                "predict",
                "--input", bins_dir,
                "--output-directory", f"{sample_id}_checkm2",
                "--threads", str(TOOL_CONFIGS["checkm2"]["cores"])
            )
            if checkm2_db:
                checkm2_job.add_args("--database_path", checkm2_db)
            checkm2_job.add_inputs(bins_dir)
            checkm2_job.add_outputs(checkm2_report, stage_out=True)
            wf.add_jobs(checkm2_job)

            all_qc_files.append(checkm2_report)

            # ============================================================
            # Step 8: Taxonomy - GTDB-Tk
            # ============================================================
            if not skip_taxonomy:
                gtdbtk_summary = File(f"{sample_id}_gtdbtk.summary.tsv")

                gtdbtk_job = Job("gtdbtk")
                gtdbtk_job.add_args(
                    "classify_wf",
                    "--genome_dir", bins_dir,
                    "--out_dir", f"{sample_id}_gtdbtk",
                    "--extension", "fa",
                    "--cpus", str(TOOL_CONFIGS["gtdbtk"]["cores"])
                )
                if gtdbtk_db:
                    gtdbtk_job.add_args("--gtdbtk_data_path", gtdbtk_db)
                gtdbtk_job.add_inputs(bins_dir, checkm2_report)
                gtdbtk_job.add_outputs(gtdbtk_summary, stage_out=True)
                gtdbtk_job.add_profiles(Namespace.PEGASUS, key="memory",
                                        value=TOOL_CONFIGS["gtdbtk"]["memory"])
                wf.add_jobs(gtdbtk_job)

            # ============================================================
            # Step 9: Annotation - Prokka
            # ============================================================
            if not skip_annotation:
                prokka_gff = File(f"{sample_id}_prokka.gff")
                prokka_gbk = File(f"{sample_id}_prokka.gbk")
                prokka_faa = File(f"{sample_id}_prokka.faa")

                prokka_job = Job("prokka")
                prokka_job.add_args(
                    "--outdir", f"{sample_id}_prokka",
                    "--prefix", sample_id,
                    "--metagenome",
                    "--cpus", str(TOOL_CONFIGS["prokka"]["cores"]),
                    bins_dir
                )
                prokka_job.add_inputs(bins_dir)
                prokka_job.add_outputs(prokka_gff, prokka_gbk, prokka_faa, stage_out=True)
                wf.add_jobs(prokka_job)

    # ============================================================
    # Step 10: MultiQC Report
    # ============================================================
    multiqc_report = File("multiqc_report.html")
    multiqc_data = File("multiqc_data.json")

    multiqc_job = Job("multiqc")
    multiqc_job.add_args(
        ".",
        "-o", "multiqc_output",
        "--force"
    )
    for qc_file in all_qc_files:
        multiqc_job.add_inputs(qc_file)
    multiqc_job.add_outputs(multiqc_report, multiqc_data, stage_out=True)
    wf.add_jobs(multiqc_job)

    return wf


# Import Namespace for profiles
from Pegasus.api import Namespace


class MagWorkflow:
    """The MAG workflow: catalogs + DAG, shared by the CLI and the notebook."""

    def __init__(self, samples: List[Dict], dagfile: str = "workflow.yml",
                 container_image: str = DEFAULT_CONTAINER,
                 assembler: str = "megahit", skip_binning: bool = False,
                 skip_taxonomy: bool = False, skip_annotation: bool = False,
                 skip_fastqc: bool = False, gtdbtk_db: Optional[str] = None,
                 checkm2_db: Optional[str] = None):
        self.samples = samples
        self.dagfile = dagfile
        self.wf_dir = str(Path(__file__).parent.resolve())
        self.container_image = container_image
        self.assembler = assembler
        self.skip_binning = skip_binning
        self.skip_taxonomy = skip_taxonomy
        self.skip_annotation = skip_annotation
        self.skip_fastqc = skip_fastqc
        self.gtdbtk_db = gtdbtk_db
        self.checkm2_db = checkm2_db
        self.props = self.sc = self.tc = self.rc = self.wf = None

    def create_pegasus_properties(self, hosted_site_catalog=None):
        self.props = create_properties(hosted_site_catalog)

    # Not used by the CLI — see create_sites_catalog() above.
    def create_sites_catalog(self, exec_site_name="compute"):
        self.sc = create_sites_catalog(self.wf_dir, exec_site_name)

    def create_transformation_catalog(self, exec_site_name="compute"):
        self.tc, _ = create_transformation_catalog(
            self.container_image, exec_site_name)

    def create_replica_catalog(self):
        self.rc = create_replica_catalog(self.samples)

    def create_workflow(self):
        self.wf = create_workflow(
            samples=self.samples,
            assembler=self.assembler,
            skip_binning=self.skip_binning,
            skip_taxonomy=self.skip_taxonomy,
            skip_annotation=self.skip_annotation,
            skip_fastqc=self.skip_fastqc,
            gtdbtk_db=self.gtdbtk_db,
            checkm2_db=self.checkm2_db,
        )

    def write(self):
        if self.sc is not None:
            self.sc.write()
        self.props.write()
        self.tc.write("transformations.yml")
        self.rc.write("replicas.yml")
        self.wf.add_transformation_catalog(self.tc)
        self.wf.add_replica_catalog(self.rc)
        self.wf.write(self.dagfile)

    # Plan / run / monitor (thin wrappers over the Pegasus API Workflow
    # object, for interactive use e.g. from a Jupyter notebook)
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


def main():
    parser = argparse.ArgumentParser(
        description="MAG Workflow Generator for Pegasus WMS",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic usage with samplesheet
  %(prog)s --samplesheet samples.csv --output workflow.yml

  # Run with nf-core/mag test data (auto-downloads)
  %(prog)s --test --output workflow.yml

  # Quick test (skip resource-intensive steps)
  %(prog)s --test --skip-taxonomy --skip-annotation

  # Use SPAdes assembler with custom databases
  %(prog)s --samplesheet samples.csv --assembler spades \\
      --gtdbtk-db /path/to/gtdbtk_db --checkm2-db /path/to/checkm2_db

  # Skip taxonomy and annotation steps
  %(prog)s --samplesheet samples.csv --skip-taxonomy --skip-annotation

  # A centrally hosted site catalog, or a plain HTCondor pool (no catalog)
  %(prog)s --samplesheet samples.csv --hosted-site-catalog unity.yml
  %(prog)s --test -e condorpool

Writes the workflow and its catalogs; it does not plan or submit. Plan with
the command it prints, or from MAG-Workflow.ipynb (plan_submit()).

Samplesheet format (CSV):
  sample,fastq_1,fastq_2,group
  sample1,/path/to/sample1_R1.fastq.gz,/path/to/sample1_R2.fastq.gz,group1
  sample2,/path/to/sample2_R1.fastq.gz,/path/to/sample2_R2.fastq.gz,group1
        """
    )

    # Test mode
    parser.add_argument(
        "--test", "-t",
        action="store_true",
        help="Use nf-core/mag test data (auto-downloads ~10MB)"
    )

    # Input/Output arguments
    parser.add_argument(
        "--samplesheet", "-s",
        type=str,
        help="Input samplesheet CSV with sample information (not required with --test)"
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default="workflow.yml",
        help="Output workflow YAML file (default: workflow.yml)"
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="./output",
        help="Directory for downloaded --test data (default: ./output)"
    )

    # Assembly options
    parser.add_argument(
        "--assembler",
        type=str,
        choices=["megahit", "spades"],
        default="megahit",
        help="Assembler to use (default: megahit)"
    )

    # Pipeline control
    parser.add_argument(
        "--skip-binning",
        action="store_true",
        help="Skip genome binning steps"
    )
    parser.add_argument(
        "--skip-taxonomy",
        action="store_true",
        help="Skip GTDB-Tk taxonomy classification"
    )
    parser.add_argument(
        "--skip-annotation",
        action="store_true",
        help="Skip Prokka annotation"
    )
    parser.add_argument(
        "--skip-fastqc",
        action="store_true",
        help="Skip FastQC QC reports"
    )

    # Database paths
    parser.add_argument(
        "--gtdbtk-db",
        type=str,
        help="Path to GTDB-Tk database"
    )
    parser.add_argument(
        "--checkm2-db",
        type=str,
        help="Path to CheckM2 database"
    )

    # Execution site. -s is --samplesheet here, so the hosted site catalog
    # has no short form.
    parser.add_argument(
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
    # --execution-site is kept as an alias: earlier releases used that name.
    parser.add_argument(
        "-e", "--execution-site-name", "--execution-site",
        dest="execution_site_name",
        metavar="STR",
        type=str,
        default="compute",
        help="Execution site name (default: compute; condorpool on a plain "
        "HTCondor pool with no site catalog)",
    )
    parser.add_argument(
        "--container-image",
        type=str,
        default=DEFAULT_CONTAINER,
        help=f"Container image to use (default: {DEFAULT_CONTAINER})"
    )

    parser.add_argument(
        "--max-memory-gb",
        type=int,
        default=None,
        help="Cap every job's memory profile at this many GB (for pools "
             "with small worker nodes; test-scale data needs far less than "
             "the production profiles)"
    )
    parser.add_argument(
        "--max-cores",
        type=int,
        default=None,
        help="Cap every job's cores profile (for small worker nodes)"
    )

    args = parser.parse_args()

    # Apply small-pool resource caps before any jobs are built.
    apply_resource_caps(args.max_memory_gb, args.max_cores)

    # Validate input: either --test or --samplesheet must be provided
    if not args.test and not args.samplesheet:
        print("Error: Either --test or --samplesheet must be provided")
        parser.print_help()
        sys.exit(1)

    # Create output directory first (needed for test data download)
    output_dir = os.path.abspath(args.output_dir)
    os.makedirs(output_dir, exist_ok=True)

    # Handle test mode vs samplesheet mode
    if args.test:
        print("=" * 60)
        print("RUNNING WITH nf-core/mag TEST DATA")
        print("=" * 60)
        samples, samplesheet_path = download_test_data(output_dir)
        if not samples:
            print("Error: Failed to download test data")
            sys.exit(1)
    else:
        # Validate samplesheet exists
        if not os.path.exists(args.samplesheet):
            print(f"Error: Samplesheet not found: {args.samplesheet}")
            sys.exit(1)

        # Parse samplesheet
        print(f"Parsing samplesheet: {args.samplesheet}")
        samples = parse_samplesheet(args.samplesheet)

    if not samples:
        print("Error: No valid samples found")
        sys.exit(1)

    print(f"\nFound {len(samples)} samples:")
    for sample in samples:
        print(f"  - {sample['id']} ({'single-end' if sample['single_end'] else 'paired-end'})")

    print("\nCreating Pegasus catalogs...")
    workflow = MagWorkflow(
        samples,
        dagfile=args.output,
        container_image=args.container_image,
        assembler=args.assembler,
        skip_binning=args.skip_binning,
        skip_taxonomy=args.skip_taxonomy,
        skip_annotation=args.skip_annotation,
        skip_fastqc=args.skip_fastqc,
        gtdbtk_db=args.gtdbtk_db,
        checkm2_db=args.checkm2_db,
    )
    workflow.create_pegasus_properties(
        hosted_site_catalog=args.hosted_site_catalog)
    workflow.create_transformation_catalog(
        exec_site_name=args.execution_site_name)
    workflow.create_replica_catalog()
    print(f"\nCreating MAG workflow with {args.assembler} assembler...")
    workflow.create_workflow()
    workflow.write()

    print(f"\nWorkflow generated successfully!")
    print(f"  Workflow: {args.output}")
    print("  Transformation catalog: transformations.yml")
    print("  Replica catalog: replicas.yml")
    print(f"  Execution site: {args.execution_site_name}")
    print(f"  Hosted site catalog: {args.hosted_site_catalog or '(none — supply your own site catalog)'}")
    # --output-dir: no site catalog defines "local", so Pegasus's built-in
    # local site would otherwise stage outputs to ./wf-output.
    output_dir = os.path.join(workflow.wf_dir, "output")
    print(f"\nTo plan and submit the workflow:")
    print(f"  pegasus-plan --dir submit -s {args.execution_site_name} -o local "
          f"--output-dir {output_dir} --submit {args.output}")


if __name__ == "__main__":
    main()
