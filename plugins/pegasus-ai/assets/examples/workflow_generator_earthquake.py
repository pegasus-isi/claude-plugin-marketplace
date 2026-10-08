#!/usr/bin/env python3

"""
Pegasus workflow generator for earthquake/seismic data analysis.

This script generates a Pegasus workflow for analyzing earthquake data from USGS:
1. Fetch earthquake data from USGS API
2. Analyze seismic patterns (magnitude distribution, depth profile, temporal trends)
3. Visualize earthquake data (maps, plots)
4. Detect seismic anomalies (swarms, aftershock sequences, rate changes)
5. Cluster earthquakes into seismic zones (DBSCAN, K-Means, or Hierarchical)
6. Predict aftershock probabilities using statistical and ML models
7. Visualize aftershock predictions (maps, probability charts, decay curves)
8. Assess seismic hazard using GMPEs (ground shaking probability)
9. Analyze seismic gaps (identify regions with anomalous quiescence)
10. Visualize seismic hazard (hazard maps, curves, risk distribution)
11. Visualize seismic gaps (gap maps, rate ratios, potential magnitudes)

Usage:
    # Zero-argument run — uses the default California 2000-2025 catalog
    ./workflow_generator.py

    ./workflow_generator.py --regions california japan \
                            --start-date 2024-01-01 \
                            --end-date 2024-01-31 \
                            --min-magnitude 4.0 \
                            --output workflow.yml

    # With custom clustering
    ./workflow_generator.py --regions california \
                            --start-date 2024-01-01 \
                            --cluster-method dbscan \
                            --cluster-eps 75 \
                            --cluster-min-samples 15 \
                            --output workflow.yml
"""

import argparse
import logging
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Pegasus imports
from Pegasus.api import *

# Site-catalog handling shared with the standalone custom_sites.py script.
sys.path.insert(0, str(Path(__file__).parent.resolve()))
from custom_sites import (  # noqa: E402
    HOSTED_SITE, STYLES, ensure_sites_yml, hosted_catalog, parse_profile,
)

# Configure logging
logging.basicConfig(level=logging.INFO,
                   format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Defaults for a zero-argument run (e.g. launching from Pegasus AI Studio).
# These are chosen so every one of the 11 analysis steps gets real data:
#   * ~12,200 events (USGS caps a single query at 20,000)
#   * ~1,200 events at M>=4.0, which is what assess_seismic_hazard uses
#   * ~90 events at M>=5.0, so predict_aftershocks finds real mainshocks
#   * a 26-year span, which covers the 20-year historical + 5-year recent
#     periods that analyze_seismic_gaps compares by default
DEFAULT_REGIONS = ["california"]
DEFAULT_START_DATE = "2000-01-01"
DEFAULT_END_DATE = "2025-12-31"

# Execution site when -e is not given: hosted catalogs (pegasushub
# pegasus-site-catalogs, named in ~/.pegasusrc) call their site HOSTED_SITE
# ("compute"); with no hosted catalog the generator adds an HTCondor one.
DEFAULT_SITE = "condorpool"

# Per-tool resources: (script in bin/, memory, wall-clock runtime in seconds).
# Batch sites (Slurm through glite) kill a job that exceeds its runtime, so
# the values are generous; condor pools ignore them. Everything else about
# where a job runs — scheduler, partition, account, scratch — belongs in the
# site catalog (see custom_sites.py).
TOOLS = {
    "fetch_earthquake_data": ("fetch_earthquake_data.py", "2 GB", 1800),
    "analyze_seismic_patterns": ("analyze_seismic_patterns.py", "2 GB", 1800),
    "visualize_earthquakes": ("visualize_earthquakes.py", "2 GB", 900),
    "detect_seismic_anomalies": ("detect_seismic_anomalies.py", "2 GB", 1800),
    "cluster_seismic_zones": ("cluster_seismic_zones.py", "2 GB", 1800),
    "predict_aftershocks": ("predict_aftershocks.py", "4 GB", 3600),
    "visualize_aftershock_predictions": (
        "visualize_aftershock_predictions.py", "2 GB", 900),
    # 35-55 min at the default 1.0° grid (HTCondor pool, Unity); each
    # halving of the grid step quadruples it, so raise this for 0.5°.
    "assess_seismic_hazard": ("assess_seismic_hazard.py", "2 GB", 7200),
    "analyze_seismic_gaps": ("analyze_seismic_gaps.py", "2 GB", 1800),
    "visualize_seismic_hazard": ("visualize_seismic_hazard.py", "2 GB", 900),
    "visualize_seismic_gaps": ("visualize_seismic_gaps.py", "2 GB", 900),
}

# Pegasus worker package (kickstart etc.) used *inside* the container, which
# is Debian 11 (python:3.8-slim) whatever the submit host runs. Pegasus 6.0
# publishes no deb_11 package; rhel_8 is built against glibc 2.28 and runs on
# Debian 11's 2.31 (it is also PegasusLite's own fallback). Change this with
# the container's base image.
WORKER_PACKAGE_PLATFORM = "x86_64_rhel_8"
WORKER_PACKAGE_URL = ("https://download.pegasus.isi.edu/pegasus/{v}/"
                      "pegasus-worker-{v}-" + WORKER_PACKAGE_PLATFORM + ".tar.gz")


def planner_version():
    """Version of the pegasus-plan that will plan this workflow, or None."""
    try:
        out = subprocess.run(["pegasus-version"], capture_output=True,
                             text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    version = out.stdout.strip()
    return version if out.returncode == 0 and version else None


class EarthquakeWorkflow:
    """Earthquake data analysis workflow generator."""

    wf = None
    tc = None
    rc = None
    props = None

    dagfile = None
    wf_dir = None
    wf_name = "earthquake"
    worker_package_url = None

    def __init__(self, dagfile="workflow.yml"):
        """Initialize workflow."""
        self.dagfile = dagfile
        self.wf_dir = str(Path(__file__).parent.resolve())

    def write(self):
        """Write all catalogs and workflow to files.

        sites.yml is not written here: custom_sites.ensure_sites_yml() owns it.
        """
        self.props.write()
        self.rc.write()
        self.tc.write()
        self.wf.write(file=self.dagfile)

    def create_pegasus_properties(self, sites_yml="sites.yml",
                                  bypass_input_staging=False):
        """Planner properties.

        The site catalog itself is custom_sites.py's business; naming an
        existing sites.yml here lets pegasus-plan find it from any directory.
        """
        self.props = Properties()
        self.props["pegasus.transfer.threads"] = "16"
        # Jobs run inside a Debian 11 container, whatever the submit host is.
        # Left alone, PegasusLite ships the submit host's worker package and,
        # on a mismatch, downloads another from inside the container — which
        # fails where the image has no curl/wget, and the submit host's
        # kickstart may need a newer glibc than Debian 11 has. So stage the
        # container-compatible package named in the transformation catalog
        # (create_transformation_catalog) and never download. strict=false
        # covers the host side, where that package is only used to transfer.
        if self.worker_package_url:
            self.props["pegasus.transfer.worker.package"] = "true"
            self.props["pegasus.transfer.worker.package.strict"] = "false"
            self.props["pegasus.transfer.worker.package.autodownload"] = "false"
        # Symlink rather than copy when an input already sits on the
        # execution site. A no-op otherwise, so always on.
        self.props["pegasus.transfer.links"] = "true"
        if bypass_input_staging:
            # Jobs read inputs (notably the .sif image) straight from the
            # submit host's paths instead of through the staging site. Only
            # valid where workers share a filesystem with the submit host —
            # a Slurm cluster, typically; not a condor pool staging over
            # HTCondor file transfer.
            self.props["pegasus.transfer.bypass.input.staging"] = "true"
        if os.path.isfile(sites_yml):
            self.props["pegasus.catalog.site"] = "YAML"
            self.props["pegasus.catalog.site.file"] = os.path.abspath(sites_yml)

    def create_transformation_catalog(
        self,
        container_sif="Apptainer/Earthquake_Container.sif",
        bind_workflow_dir=False,
    ):
        """Container and transformations; nothing here names a site.

        bind_workflow_dir: on a site that stages through its own filesystem
        (a Slurm cluster, Unity's hosted catalog) or with bypass staging,
        pegasus.transfer.links stages inputs as symlinks to absolute paths
        under the workflow directory. PegasusLite starts the container with
        --no-home and binds only the job directory, so those links dangle
        inside it and every job dies with kickstart "Unable to execute the
        specified binary" (exit 127). Binding the workflow directory at its
        own path makes them resolve. Never on a condor pool: inputs arrive
        there as copies and the directory does not exist on the workers, so
        the bind would fail every job.
        """
        logger.info("Creating transformation catalog")
        self.tc = TransformationCatalog()

        # Container - a local Apptainer .sif built with `apptainer build`.
        # Pegasus stages the file like any other input, so image_site is the
        # site where the .sif physically lives (the submit host = "local").
        sif_path = (
            container_sif
            if os.path.isabs(container_sif)
            else os.path.join(self.wf_dir, container_sif)
        )
        if not os.path.exists(sif_path):
            logger.warning(
                "Apptainer image not found at %s — build it first with: "
                "apptainer build %s Apptainer/Earthquake_Container.def",
                sif_path,
                sif_path,
            )
        earthquake_container = Container(
            "earthquake_container",
            container_type=Container.SINGULARITY,
            image="file://" + sif_path,
            image_site="local",
        )
        if bind_workflow_dir:
            earthquake_container.add_pegasus_profile(
                container_arguments=f"--bind {self.wf_dir}")
        self.tc.add_containers(earthquake_container)

        if self.worker_package_url:
            self.tc.add_transformations(
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

        # The scripts live on the submit host ("local") and are staged to
        # whichever execution site the planner is given.
        for name, (script, memory, runtime) in TOOLS.items():
            self.tc.add_transformations(
                Transformation(
                    name,
                    site="local",
                    pfn=os.path.join(self.wf_dir, "bin", script),
                    is_stageable=True,
                    container=earthquake_container,
                ).add_pegasus_profile(cores=1, memory=memory, runtime=runtime)
            )

    def create_replica_catalog(self):
        """Create replica catalog."""
        logger.info("Creating replica catalog")
        self.rc = ReplicaCatalog()
        # No input files needed - fetch_earthquake_data fetches from API

    def create_workflow(self, regions, start_date, end_date, min_magnitude,
                        cluster_method="dbscan", cluster_eps=50.0,
                        cluster_min_samples=10, cluster_n_clusters=5,
                        aftershock_threshold=5.0, aftershock_time_windows=[1, 7, 30],
                        hazard_grid_resolution=1.0, hazard_pga_thresholds=[0.1, 0.2, 0.4],
                        gap_historical_years=20, gap_recent_years=5, gap_rate_threshold=0.3):
        """Create the workflow DAG."""
        logger.info("Creating workflow DAG")
        self.wf = Workflow(self.wf_name, infer_dependencies=True)

        for region in regions:
            self._add_region_jobs(region, start_date, end_date, min_magnitude,
                                 cluster_method, cluster_eps,
                                 cluster_min_samples, cluster_n_clusters,
                                 aftershock_threshold, aftershock_time_windows,
                                 hazard_grid_resolution, hazard_pga_thresholds,
                                 gap_historical_years, gap_recent_years, gap_rate_threshold)

    def _add_region_jobs(self, region, start_date, end_date, min_magnitude,
                        cluster_method, cluster_eps, cluster_min_samples,
                        cluster_n_clusters, aftershock_threshold, aftershock_time_windows,
                        hazard_grid_resolution, hazard_pga_thresholds,
                        gap_historical_years, gap_recent_years, gap_rate_threshold):
        """Add jobs for a single region."""
        logger.info(f"Adding jobs for region: {region}")

        # Output files
        catalog_file = File(f"{region}_catalog.csv")
        patterns_file = File(f"{region}_patterns.json")
        visualization_file = File(f"{region}_visualization.png")
        anomalies_file = File(f"{region}_anomalies.json")
        zones_file = File(f"{region}_zones.json")
        aftershock_file = File(f"{region}_aftershock_predictions.json")
        aftershock_viz_file = File(f"{region}_aftershock_visualization.png")
        hazard_file = File(f"{region}_seismic_hazard.json")
        gaps_file = File(f"{region}_seismic_gaps.json")
        hazard_viz_file = File(f"{region}_hazard_visualization.png")
        gaps_viz_file = File(f"{region}_gaps_visualization.png")

        # Job 1: Fetch earthquake data
        fetch_job = (
            Job(
                "fetch_earthquake_data",
                _id=f"fetch_{region}",
                node_label=f"fetch_{region}",
            )
            .add_args(
                "--region", region,
                "--start-date", start_date,
                "--end-date", end_date,
                "--min-magnitude", str(min_magnitude),
                "--output", catalog_file
            )
            .add_outputs(catalog_file, stage_out=True, register_replica=False)
            .add_pegasus_profiles(label=region)
        )
        self.wf.add_jobs(fetch_job)

        # Job 2: Analyze seismic patterns
        analyze_job = (
            Job(
                "analyze_seismic_patterns",
                _id=f"analyze_{region}",
                node_label=f"analyze_{region}",
            )
            .add_args(
                "--input", catalog_file,
                "--output", patterns_file
            )
            .add_inputs(catalog_file)
            .add_outputs(patterns_file, stage_out=True, register_replica=False)
            .add_pegasus_profiles(label=region)
        )
        self.wf.add_jobs(analyze_job)

        # Job 3: Visualize earthquakes
        # Use underscores in title to avoid argument splitting issues
        title = f"{region.title()}_Earthquakes"
        visualize_job = (
            Job(
                "visualize_earthquakes",
                _id=f"visualize_{region}",
                node_label=f"visualize_{region}",
            )
            .add_args(
                "--input", catalog_file,
                "--output", visualization_file,
                "--title", title
            )
            .add_inputs(catalog_file)
            .add_outputs(visualization_file, stage_out=True, register_replica=False)
            .add_pegasus_profiles(label=region)
        )
        self.wf.add_jobs(visualize_job)

        # Job 4: Detect seismic anomalies
        anomalies_job = (
            Job(
                "detect_seismic_anomalies",
                _id=f"anomalies_{region}",
                node_label=f"anomalies_{region}",
            )
            .add_args(
                "--input", catalog_file,
                "--output", anomalies_file
            )
            .add_inputs(catalog_file)
            .add_outputs(anomalies_file, stage_out=True, register_replica=False)
            .add_pegasus_profiles(label=region)
        )
        self.wf.add_jobs(anomalies_job)

        # Job 5: Cluster seismic zones
        cluster_args = [
            "--input", catalog_file,
            "--output", zones_file,
            "--method", cluster_method
        ]
        if cluster_method == "dbscan":
            cluster_args.extend(["--eps", str(cluster_eps),
                                "--min-samples", str(cluster_min_samples)])
        elif cluster_method == "kmeans":
            cluster_args.extend(["--n-clusters", str(cluster_n_clusters)])
        elif cluster_method == "hierarchical":
            cluster_args.extend(["--n-clusters", str(cluster_n_clusters)])

        cluster_job = (
            Job(
                "cluster_seismic_zones",
                _id=f"cluster_{region}",
                node_label=f"cluster_{region}",
            )
            .add_args(*cluster_args)
            .add_inputs(catalog_file)
            .add_outputs(zones_file, stage_out=True, register_replica=False)
            .add_pegasus_profiles(label=region)
        )
        self.wf.add_jobs(cluster_job)

        # Job 6: Predict aftershocks
        aftershock_args = [
            "--input", catalog_file,
            "--output", aftershock_file,
            "--mainshock-threshold", str(aftershock_threshold),
            "--time-windows"
        ]
        aftershock_args.extend([str(w) for w in aftershock_time_windows])

        aftershock_job = (
            Job(
                "predict_aftershocks",
                _id=f"aftershock_{region}",
                node_label=f"aftershock_{region}",
            )
            .add_args(*aftershock_args)
            .add_inputs(catalog_file)
            .add_outputs(aftershock_file, stage_out=True, register_replica=False)
            .add_pegasus_profiles(label=region)
        )
        self.wf.add_jobs(aftershock_job)

        # Job 7: Visualize aftershock predictions
        aftershock_title = f"{region.title()}_Aftershock_Predictions"
        aftershock_viz_job = (
            Job(
                "visualize_aftershock_predictions",
                _id=f"aftershock_viz_{region}",
                node_label=f"aftershock_viz_{region}",
            )
            .add_args(
                "--input", aftershock_file,
                "--catalog", catalog_file,
                "--output", aftershock_viz_file,
                "--title", aftershock_title
            )
            .add_inputs(aftershock_file, catalog_file)
            .add_outputs(aftershock_viz_file, stage_out=True, register_replica=False)
            .add_pegasus_profiles(label=region)
        )
        self.wf.add_jobs(aftershock_viz_job)

        # Job 8: Assess seismic hazard
        hazard_args = [
            "--input", catalog_file,
            "--output", hazard_file,
            "--grid-resolution", str(hazard_grid_resolution),
            "--pga-thresholds"
        ]
        hazard_args.extend([str(t) for t in hazard_pga_thresholds])

        hazard_job = (
            Job(
                "assess_seismic_hazard",
                _id=f"hazard_{region}",
                node_label=f"hazard_{region}",
            )
            .add_args(*hazard_args)
            .add_inputs(catalog_file)
            .add_outputs(hazard_file, stage_out=True, register_replica=False)
            .add_pegasus_profiles(label=region)
        )
        self.wf.add_jobs(hazard_job)

        # Job 9: Analyze seismic gaps
        gaps_job = (
            Job(
                "analyze_seismic_gaps",
                _id=f"gaps_{region}",
                node_label=f"gaps_{region}",
            )
            .add_args(
                "--input", catalog_file,
                "--output", gaps_file,
                "--historical-years", str(gap_historical_years),
                "--recent-years", str(gap_recent_years),
                "--rate-threshold", str(gap_rate_threshold)
            )
            .add_inputs(catalog_file)
            .add_outputs(gaps_file, stage_out=True, register_replica=False)
            .add_pegasus_profiles(label=region)
        )
        self.wf.add_jobs(gaps_job)

        # Job 10: Visualize seismic hazard
        hazard_viz_title = f"{region.title()}_Seismic_Hazard"
        hazard_viz_job = (
            Job(
                "visualize_seismic_hazard",
                _id=f"hazard_viz_{region}",
                node_label=f"hazard_viz_{region}",
            )
            .add_args(
                "--input", hazard_file,
                "--catalog", catalog_file,
                "--output", hazard_viz_file,
                "--title", hazard_viz_title
            )
            .add_inputs(hazard_file, catalog_file)
            .add_outputs(hazard_viz_file, stage_out=True, register_replica=False)
            .add_pegasus_profiles(label=region)
        )
        self.wf.add_jobs(hazard_viz_job)


        # Job 11: Visualize seismic gaps
        gaps_viz_title = f"{region.title()}_Seismic_Gaps"
        gaps_viz_job = (
            Job(
                "visualize_seismic_gaps",
                _id=f"gaps_viz_{region}",
                node_label=f"gaps_viz_{region}",
            )
            .add_args(
                "--input", gaps_file,
                "--catalog", catalog_file,
                "--output", gaps_viz_file,
                "--title", gaps_viz_title
            )
            .add_inputs(gaps_file, catalog_file)
            .add_outputs(gaps_viz_file, stage_out=True, register_replica=False)
            .add_pegasus_profiles(label=region)
        )
        self.wf.add_jobs(gaps_viz_job)

def parse_date(date_str: str) -> datetime:
    """Parse date string."""
    return datetime.strptime(date_str, "%Y-%m-%d")


def setup_site_catalog(args, wf_dir):
    """Ensure the site catalog can plan args.execution_site; return its style.

    Defaults work untouched (an HTCondor site is added if nothing defines
    the requested one), a sites.yml or hosted catalog someone provided wins,
    and --site-style/--queue/--project/... tailor it for a batch cluster.
    """
    action, style = ensure_sites_yml(
        args.sites_yml, args.execution_site, wf_dir,
        style=args.site_style, queue=args.queue, project=args.project,
        scratch=args.site_scratch, profiles=args.site_profile)
    hosted = hosted_catalog()
    logger.info(f"Site catalog: {args.sites_yml}: {action}"
                + (f" (merged over hosted {hosted})" if hosted else ""))
    if style is None and hosted:
        logger.info(f"  The hosted catalog {hosted} decides how "
                    f"{args.execution_site!r} submits; hosted catalogs name "
                    "their site 'compute'.")
        if args.execution_site != HOSTED_SITE:
            # Nothing was written for this site, so planning works only if
            # the hosted catalog happens to define it.
            logger.warning(
                f"  {args.execution_site!r} is not defined in {args.sites_yml} "
                f"and hosted catalogs normally define only {HOSTED_SITE!r}: "
                f"pegasus-plan will fail unless {hosted} has it. Use -e "
                f"{HOSTED_SITE}, or --site-style condor/slurm to describe "
                f"{args.execution_site!r}.")
    return style


def main():
    parser = argparse.ArgumentParser(
        description="Generate Pegasus workflow for earthquake data analysis",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # No arguments — California, 2000-01-01 to 2025-12-31, M3.0+
  %(prog)s

  # Single region
  %(prog)s --regions california --start-date 2024-01-01 --end-date 2024-01-31

  # Multiple regions
  %(prog)s --regions california japan indonesia --start-date 2024-01-01

  # Higher magnitude threshold
  %(prog)s --regions pacific_ring --start-date 2024-01-01 --min-magnitude 5.0

Available regions:
  - pacific_ring: Pacific Ring of Fire
  - california: California, USA
  - japan: Japanese archipelago
  - indonesia: Indonesian archipelago
  - turkey: Turkey and surroundings
  - chile: Chile
  - worldwide: Global (no bounding box)
        """
    )

    # --- Execution site. The workflow states only cores/memory/runtime;
    # these options shape the site catalog (custom_sites.py).
    parser.add_argument(
        "-e",
        "--execution-site",
        "--execution-site-name",
        dest="execution_site",
        metavar="STR",
        type=str,
        default=None,
        help="Site to plan against (default: 'compute' when ~/.pegasusrc "
             "names a hosted catalog such as Unity, which call their site "
             "that; otherwise 'condorpool')",
    )
    parser.add_argument(
        "--site-style",
        choices=("auto",) + STYLES + ("none",),
        default="auto",
        help="How the execution site is described in sites.yml. auto (default): "
             "keep a sites.yml entry or hosted catalog if one exists, else add "
             "an HTCondor site. condor/slurm: (re)write that site's entry. "
             "none: leave sites.yml alone.",
    )
    parser.add_argument(
        "--queue",
        metavar="PARTITION",
        help="Batch partition/queue jobs submit to (required for "
             "--site-style slurm without a hosted catalog)",
    )
    parser.add_argument(
        "--project",
        metavar="ACCOUNT",
        help="Allocation/account charged on a batch site",
    )
    parser.add_argument(
        "--site-scratch",
        metavar="DIR",
        help="Slurm only: shared scratch visible to workers and the submit "
             "host (default: ./work)",
    )
    parser.add_argument(
        "--site-profile",
        action="append",
        default=[],
        type=parse_profile,
        metavar="NS:KEY=VALUE",
        help="Extra profile on the execution site, e.g. "
             "pegasus:glite.arguments=--constraint=avx512; repeatable",
    )
    parser.add_argument(
        "--shared-filesystem",
        choices=("auto", "yes", "no"),
        default="auto",
        help="Let jobs read inputs (incl. the container image) directly from "
             "the submit host instead of via staging. auto (default): on for a "
             "Slurm site, off for HTCondor, which stages over file transfer.",
    )
    parser.add_argument(
        "--sites-yml",
        metavar="FILE",
        type=str,
        default="sites.yml",
        help="Local site catalog (default: sites.yml). Named in the generated "
             "properties, so pegasus-plan finds it from any directory.",
    )
    parser.add_argument(
        "-s",
        "--skip-sites-catalog",
        action="store_true",
        help="Deprecated: same as --site-style none",
    )
    parser.add_argument(
        "-o",
        "--output",
        metavar="STR",
        type=str,
        default="workflow.yml",
        help="Output file (default: workflow.yml)",
    )
    parser.add_argument(
        "--regions",
        type=str,
        nargs="+",
        default=DEFAULT_REGIONS,
        help="Region names (pacific_ring, california, japan, indonesia, "
             f"turkey, chile, worldwide) (default: {' '.join(DEFAULT_REGIONS)})"
    )
    parser.add_argument(
        "--start-date",
        type=str,
        default=None,
        help=f"Start date (YYYY-MM-DD) (default: {DEFAULT_START_DATE})"
    )
    parser.add_argument(
        "--end-date",
        type=str,
        default=None,
        help="End date (YYYY-MM-DD). Defaults to start_date + 30 days, or to "
             f"{DEFAULT_END_DATE} when --start-date is also left at its default"
    )
    parser.add_argument(
        "--min-magnitude",
        type=float,
        default=3.0,
        help="Minimum magnitude (default: 3.0)"
    )

    # Clustering parameters
    parser.add_argument(
        "--cluster-method",
        type=str,
        choices=["dbscan", "kmeans", "hierarchical"],
        default="dbscan",
        help="Clustering method (default: dbscan)"
    )
    parser.add_argument(
        "--cluster-eps",
        type=float,
        default=50.0,
        help="DBSCAN: Max distance (km) between samples (default: 50)"
    )
    parser.add_argument(
        "--cluster-min-samples",
        type=int,
        default=10,
        help="DBSCAN: Min samples for core points (default: 10)"
    )
    parser.add_argument(
        "--cluster-n-clusters",
        type=int,
        default=5,
        help="K-Means/Hierarchical: Number of clusters (default: 5)"
    )

    # Aftershock prediction parameters
    parser.add_argument(
        "--aftershock-threshold",
        type=float,
        default=5.0,
        help="Minimum magnitude for mainshock identification (default: 5.0)"
    )
    parser.add_argument(
        "--aftershock-time-windows",
        type=int,
        nargs="+",
        default=[1, 7, 30],
        help="Time windows in days for aftershock predictions (default: 1 7 30)"
    )

    # Seismic hazard assessment parameters
    parser.add_argument(
        "--hazard-grid-resolution",
        type=float,
        default=1.0,
        help="Grid resolution for hazard analysis in degrees (default: 1.0)"
    )
    parser.add_argument(
        "--hazard-pga-thresholds",
        type=float,
        nargs="+",
        default=[0.1, 0.2, 0.4],
        help="PGA thresholds in g for exceedance probability (default: 0.1 0.2 0.4)"
    )

    # Seismic gap analysis parameters
    parser.add_argument(
        "--gap-historical-years",
        type=int,
        default=20,
        help="Historical period for gap analysis in years (default: 20)"
    )
    parser.add_argument(
        "--gap-recent-years",
        type=int,
        default=5,
        help="Recent period for gap analysis in years (default: 5)"
    )
    parser.add_argument(
        "--gap-rate-threshold",
        type=float,
        default=0.3,
        help="Rate ratio threshold for gap detection (default: 0.3)"
    )
    parser.add_argument(
        "--container-sif",
        default="Apptainer/Earthquake_Container.sif",
        help="Path to the Apptainer .sif image, absolute or relative to the "
             "workflow directory (default: Apptainer/Earthquake_Container.sif)"
    )

    args = parser.parse_args()
    if args.execution_site is None:
        args.execution_site = HOSTED_SITE if hosted_catalog() else DEFAULT_SITE

    # Parse dates. --start-date defaults to None rather than to
    # DEFAULT_START_DATE so that "left alone" can be told apart from
    # "explicitly given the default value"; only the former pairs with
    # DEFAULT_END_DATE. Passing --start-date 2000-01-01 by hand still means
    # start + 30 days, as documented.
    start_date_given = args.start_date is not None
    if not start_date_given:
        args.start_date = DEFAULT_START_DATE

    start_date = parse_date(args.start_date)
    if args.end_date:
        end_date = parse_date(args.end_date)
    elif not start_date_given:
        end_date = parse_date(DEFAULT_END_DATE)
    else:
        end_date = start_date + timedelta(days=30)

    # Validate regions
    valid_regions = ['pacific_ring', 'california', 'japan', 'indonesia',
                    'turkey', 'chile', 'worldwide']
    for region in args.regions:
        if region not in valid_regions:
            logger.error(f"Invalid region: {region}. Valid regions: {valid_regions}")
            sys.exit(1)

    logger.info("=" * 70)
    logger.info("EARTHQUAKE WORKFLOW GENERATOR")
    logger.info("=" * 70)
    logger.info(f"Regions: {', '.join(args.regions)}")
    logger.info(f"Date range: {start_date.date()} to {end_date.date()}")
    logger.info(f"Minimum magnitude: {args.min_magnitude}")
    logger.info(f"Clustering: {args.cluster_method}")
    logger.info(f"Aftershock threshold: M{args.aftershock_threshold}")
    logger.info(f"Hazard grid resolution: {args.hazard_grid_resolution}°")
    logger.info(f"Gap analysis: historical={args.gap_historical_years}yr, recent={args.gap_recent_years}yr")
    logger.info(f"Execution site: {args.execution_site}")
    logger.info(f"Output file: {args.output}")
    logger.info("=" * 70)

    try:
        # Create workflow
        workflow = EarthquakeWorkflow(dagfile=args.output)

        if args.skip_sites_catalog:
            args.site_style = "none"
        style = setup_site_catalog(args, workflow.wf_dir)
        if args.shared_filesystem == "auto":
            bypass = style is not None and style != "condor"
        else:
            bypass = args.shared_filesystem == "yes"
        # A site that is not a condor pool stages through its own filesystem
        # (an unknown style over a hosted catalog counts: hosted catalogs are
        # batch sites), and then staged inputs are symlinks into wf_dir.
        batch_site = (style not in (None, "condor")
                      or (style is None and hosted_catalog() is not None))
        bind_wf = batch_site or bypass
        logger.info("Input staging: "
                    + ("bypassed (shared filesystem)" if bypass
                       else "via staging site")
                    + (f"; container binds {workflow.wf_dir}" if bind_wf else ""))
        version = planner_version()
        if version:
            workflow.worker_package_url = WORKER_PACKAGE_URL.format(v=version)
            logger.info(f"Worker package: {WORKER_PACKAGE_PLATFORM} for Pegasus "
                        f"{version} (staged into the container, no in-job "
                        "download)")
        else:
            logger.warning("pegasus-version not found; Pegasus will pick the "
                           "container's worker package itself (needs curl/wget "
                           "in the image and internet on the workers)")

        logger.info("Creating workflow properties...")
        workflow.create_pegasus_properties(
            sites_yml=args.sites_yml, bypass_input_staging=bypass)

        logger.info("Creating transformation catalog...")
        workflow.create_transformation_catalog(
            container_sif=args.container_sif, bind_workflow_dir=bind_wf
        )

        logger.info("Creating replica catalog...")
        workflow.create_replica_catalog()

        logger.info("Creating earthquake workflow DAG...")
        workflow.create_workflow(
            regions=args.regions,
            start_date=args.start_date,
            end_date=end_date.strftime("%Y-%m-%d"),
            min_magnitude=args.min_magnitude,
            cluster_method=args.cluster_method,
            cluster_eps=args.cluster_eps,
            cluster_min_samples=args.cluster_min_samples,
            cluster_n_clusters=args.cluster_n_clusters,
            aftershock_threshold=args.aftershock_threshold,
            aftershock_time_windows=args.aftershock_time_windows,
            hazard_grid_resolution=args.hazard_grid_resolution,
            hazard_pga_thresholds=args.hazard_pga_thresholds,
            gap_historical_years=args.gap_historical_years,
            gap_recent_years=args.gap_recent_years,
            gap_rate_threshold=args.gap_rate_threshold
        )

        workflow.write()

        logger.info("\n" + "=" * 70)
        logger.info("WORKFLOW GENERATION COMPLETE")
        logger.info("=" * 70)
        logger.info("\nNext steps:")
        logger.info(f"  1. Review workflow: {args.output}")
        logger.info(f"  2. Submit workflow: pegasus-plan --submit -s {args.execution_site} -o local {args.output}")
        logger.info(f"  3. Monitor status: pegasus-status <submit_dir>")
        logger.info("=" * 70 + "\n")

    except Exception as e:
        logger.error(f"Failed to generate workflow: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
