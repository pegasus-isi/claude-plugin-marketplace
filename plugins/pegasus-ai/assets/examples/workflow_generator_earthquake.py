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

    # A plain HTCondor pool with no site catalog
    ./workflow_generator.py -e condorpool

Sites follow pegasus-isi/pegasus-gromacs: jobs run on a site named "compute",
defined by a centrally hosted site catalog (-s FILE, or one in ~/.pegasusrc;
https://github.com/pegasushub/pegasus-site-catalogs). The generator writes no
site catalog and never submits: it prints the pegasus-plan command, and the
notebook (Access-Earthquake-workflow.ipynb) submits from an explicit cell.
"""

import argparse
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Pegasus imports
from Pegasus.api import *

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


# Per-tool resources: (script in bin/, memory).
TOOLS = {
    "fetch_earthquake_data": ("fetch_earthquake_data.py", "2 GB"),
    "analyze_seismic_patterns": ("analyze_seismic_patterns.py", "2 GB"),
    "visualize_earthquakes": ("visualize_earthquakes.py", "2 GB"),
    "detect_seismic_anomalies": ("detect_seismic_anomalies.py", "2 GB"),
    "cluster_seismic_zones": ("cluster_seismic_zones.py", "2 GB"),
    "predict_aftershocks": ("predict_aftershocks.py", "4 GB"),
    "visualize_aftershock_predictions": (
        "visualize_aftershock_predictions.py", "2 GB"),
    # 35-55 min at the default 1.0° grid; each halving of the grid step
    # quadruples it. Hosted batch catalogs default to 2 h per job — at 0.5°
    # add add_pegasus_profile(runtime=...) to this tool.
    "assess_seismic_hazard": ("assess_seismic_hazard.py", "2 GB"),
    "analyze_seismic_gaps": ("analyze_seismic_gaps.py", "2 GB"),
    "visualize_seismic_hazard": ("visualize_seismic_hazard.py", "2 GB"),
    "visualize_seismic_gaps": ("visualize_seismic_gaps.py", "2 GB"),
}


class EarthquakeWorkflow:
    """Earthquake data analysis workflow generator."""

    wf = None
    sc = None
    tc = None
    rc = None
    props = None

    dagfile = None
    wf_dir = None
    shared_scratch_dir = None
    local_storage_dir = None
    wf_name = "earthquake"

    def __init__(self, dagfile="workflow.yml"):
        """Initialize workflow."""
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
    def create_transformation_catalog(
        self,
        exec_site_name="compute",
        container_sif="Apptainer/Earthquake_Container.sif",
    ):
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
        self.tc.add_containers(earthquake_container)

        for name, (script, memory) in TOOLS.items():
            self.tc.add_transformations(
                Transformation(
                    name,
                    site=exec_site_name,
                    pfn=os.path.join(self.wf_dir, "bin", script),
                    is_stageable=True,
                    container=earthquake_container,
                ).add_pegasus_profile(cores=1, memory=memory)
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
            # Retry infrastructure transients; the script itself retries the
            # USGS request with backoff.
            .add_dagman_profile(retry="2")
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

  # A hosted site catalog / a plain HTCondor pool with no site catalog
  %(prog)s -s access-pegasus.yml
  %(prog)s -e condorpool

Writes the workflow and its catalogs; it does not plan or submit. Plan with
the command it prints, or from the notebook (plan_submit()).

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
    logger.info(f"Execution site: {args.execution_site_name}")
    logger.info(
        f"Hosted site catalog: {args.hosted_site_catalog or '(none — supply your own site catalog)'}"
    )
    logger.info(f"Output file: {args.output}")
    logger.info("=" * 70)

    try:
        # Create workflow
        workflow = EarthquakeWorkflow(dagfile=args.output)

        logger.info("Creating workflow properties...")
        workflow.create_pegasus_properties(hosted_site_catalog=args.hosted_site_catalog)

        logger.info("Creating transformation catalog...")
        workflow.create_transformation_catalog(
            exec_site_name=args.execution_site_name,
            container_sif=args.container_sif,
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
        # --output-dir: no site catalog defines "local", so Pegasus's built-in local
        # site would otherwise stage outputs to ./wf-output.
        logger.info(f"  2. Plan and submit: pegasus-plan --dir submit -s {args.execution_site_name} -o local "
                    f"--output-dir {workflow.local_storage_dir} --submit {args.output}")
        logger.info(f"  3. Monitor status: pegasus-status <submit_dir>")
        logger.info("=" * 70 + "\n")

    except Exception as e:
        logger.error(f"Failed to generate workflow: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
