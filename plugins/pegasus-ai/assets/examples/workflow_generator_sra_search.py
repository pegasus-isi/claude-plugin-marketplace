#!/usr/bin/python3

'''
Sample Pegasus workflow for searching the SRA database

The site catalog (sites.yml) is managed by custom_sites.py: a sites.yml or
hosted catalog you provide is kept, and only missing entries are added.
'''

import argparse
import logging
import os
import sys

from Pegasus.api import *

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# Site-catalog handling shared with the standalone custom_sites.py script.
sys.path.insert(0, BASE_DIR)
from custom_sites import (  # noqa: E402
    HOSTED_SITE, STYLES, ensure_sites_yml, hosted_catalog, parse_profile,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Execution site when -e is not given: Pegasus' HTCondor pool, unless
# ~/.pegasusrc names a hosted catalog (pegasushub pegasus-site-catalogs), whose
# one site is HOSTED_SITE ("compute").
DEFAULT_SITE = 'condorpool'

# Per-tool resources. runtime is the wall-clock budget in seconds: batch sites
# (Slurm through glite) require it and kill a job that exceeds it; condor
# pools ignore it. Raise it for large SRA runs or references. Everything else
# about where a job runs (scheduler, partition, account, scratch) belongs in
# the site catalog (custom_sites.py).
TOOL_CONFIGS = {
    'bowtie2-build': {'memory': '1 GB', 'runtime': 3600},
    'fasterq-dump': {'memory': '1 GB', 'runtime': 3600},
    'bowtie2': {'memory': '2 GB', 'runtime': 3600},
    'merge': {'memory': '1 GB', 'runtime': 1800},
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


def write_properties(sites_yml='sites.yml', condor_site=False,
                     bypass_input_staging=False):
    '''
    Writes pegasus.properties. The site catalog itself is custom_sites.py's
    business; naming an existing sites.yml here lets pegasus-plan find it
    from any directory.
    condor_site: the execution site is an HTCondor pool, so stage over
    HTCondor file transfer (condorio). Other sites set their own data
    configuration in the site catalog.
    bypass_input_staging: jobs read inputs (wrappers, reference, the .sif
    image) straight from the submit host's paths. Only valid where workers
    share a filesystem with the submit host, typically a Slurm cluster.
    '''

    # set the concurrency limit for the download jobs, and send some extra usage
    # data to the Pegasus developers
    props = Properties()
    if condor_site:
        props['pegasus.data.configuration'] = 'condorio'
    props['dagman.fasterq-dump.maxjobs'] = '20'
    props['pegasus.catalog.workflow.amqp.url'] = 'amqp://friend:donatedata@msgs.pegasus.isi.edu:5672/prod/workflows'
    # Symlink rather than copy when an input already sits on the execution
    # site. A no-op otherwise, so always on.
    props['pegasus.transfer.links'] = 'true'
    if bypass_input_staging:
        props['pegasus.transfer.bypass.input.staging'] = 'true'
    if os.path.isfile(sites_yml):
        props['pegasus.catalog.site'] = 'YAML'
        props['pegasus.catalog.site.file'] = os.path.abspath(sites_yml)
    props.write()


def build_workflow(sra_id_list, reference, bind_workflow_dir=False):
    '''
    Builds and returns (wf, tc, rc) for the sra-search workflow. Nothing here
    names an execution site; that is the site catalog's job.
    sra_id_list: path to a file containing one SRA ID per line
    reference: path to the reference FASTA file
    bind_workflow_dir: on a site that stages through its own filesystem (a
    Slurm cluster, a hosted catalog) or with bypass staging,
    pegasus.transfer.links stages inputs as symlinks to absolute paths under
    the workflow directory. PegasusLite starts the container with --no-home
    and binds only the job directory, so those links dangle inside it and
    every job dies with kickstart "Unable to execute the specified binary"
    (exit 127). Binding the workflow directory at its own path makes them
    resolve. Never on a condor pool: inputs arrive there as copies and the
    directory does not exist on the workers, so the bind would fail every job.
    '''

    wf = Workflow('sra-search')
    tc = TransformationCatalog()
    rc = ReplicaCatalog()

    # --- Transformations -----------------------------------------------------

    container = Container(
                   'sra-search',
                   Container.SINGULARITY,
                   f"file://{BASE_DIR}/container/sra.sif",
                   image_site="local"
                )
    if bind_workflow_dir:
        container.add_pegasus_profile(container_arguments=f"--bind {BASE_DIR}")
    tc.add_containers(container)

    bowtie2_build = Transformation(
                       'bowtie2-build',
                       site='incontainer',
                       container=container,
                       pfn='/opt/bowtie2/bowtie2-build',
                       is_stageable=False
                    )
    tc.add_transformations(bowtie2_build)

    bowtie2 = Transformation(
                  'bowtie2',
                  site='local',
                  container=container,
                  pfn=f"{BASE_DIR}/executables/bowtie2_wrapper",
                  is_stageable=True
              )
    tc.add_transformations(bowtie2)

    fasterq_dump = Transformation(
                      'fasterq-dump',
                       site='local',
                       container=container,
                       pfn=f"{BASE_DIR}/executables/fasterq_dump_wrapper",
                       is_stageable=True
                     )
    # this one is used to limit the number of concurrent downloads
    fasterq_dump.add_profiles(Namespace.DAGMAN, key='category', value='fasterq-dump')
    tc.add_transformations(fasterq_dump)

    merge = Transformation(
                'merge',
                site='local',
                container=container,
                pfn=f"{BASE_DIR}/executables/merge",
                is_stageable=True
            )
    tc.add_transformations(merge)

    # memory maps to request_memory on HTCondor and --mem on Slurm
    for tx in (bowtie2_build, bowtie2, fasterq_dump, merge):
        config = TOOL_CONFIGS[tx.name]
        tx.add_pegasus_profile(memory=config['memory'],
                               runtime=str(config['runtime']))

    # --- Workflow -----------------------------------------------------

    # keep track of bam files, so we can merge them into a single tarball at
    # the end
    to_merge = []

    # set up reference file and what files needs to be generated by the index job
    ref_main = File('reference.fna')
    rc.add_replica('local', 'reference.fna', os.path.abspath(reference))
    ref_files = []
    for filename in ['reference.1.bt2', 'reference.2.bt2', 'reference.3.bt2', 'reference.4.bt2',
                     'reference.rev.1.bt2', 'reference.rev.2.bt2']:
        ref_files.append(File(filename))

    # index the reference file
    index_job = Job('bowtie2-build')
    index_job.add_args('reference.fna', 'reference')
    index_job.add_inputs(ref_main)
    index_job.add_outputs(*ref_files, stage_out=False)
    wf.add_jobs(index_job)

    # create jobs for each SRA ID
    with open(sra_id_list) as fh:
        for line in fh:
            sra_id = line.strip()
            if len(sra_id) < 5:
                continue

            # files for this id
            fastq_1 = File('{}_1.fastq'.format(sra_id))
            fastq_2 = File('{}_2.fastq'.format(sra_id))

            # download job
            j = Job('fasterq-dump')
            j.add_args('--split-files', sra_id)
            j.add_outputs(fastq_1, fastq_2, stage_out=False)
            wf.add_jobs(j)

            # bowtie2 job
            bam = File('{}.bam'.format(sra_id))
            bam_index = File('{}.bam.bai'.format(sra_id))
            j = Job('bowtie2')
            j.add_args(sra_id)
            j.add_inputs(*ref_files, fastq_1, fastq_2)
            j.add_outputs(bam, bam_index, stage_out=False)
            wf.add_jobs(j)

            # keep track of jobs and outputs for merging
            to_merge.append(j)

    add_merge_jobs(wf, to_merge)

    wf.add_transformation_catalog(tc)
    wf.add_replica_catalog(rc)

    return wf, tc, rc


def setup_site_catalog(args):
    '''
    Ensures the site catalog can plan args.execution_site; returns its style.

    Defaults work untouched (an HTCondor site is added if nothing defines
    the requested one), a sites.yml or hosted catalog someone provided wins,
    and --site-style/--queue/--project/... tailor it for a batch cluster.
    '''
    profiles = list(args.site_profile)
    if args.site_style != 'slurm':
        # Any HTCondor site written here runs the jobs in HTCondor's container
        # universe, as Pegasus' auto-created condorpool used to (set first, so
        # a --site-profile can override it). Not applied to an entry that
        # already exists or comes from a hosted catalog.
        profiles.insert(0, ('condor', 'universe', 'container'))
    action, style = ensure_sites_yml(
        args.sites_yml, args.execution_site, BASE_DIR,
        style=args.site_style, queue=args.queue, project=args.project,
        scratch=args.site_scratch, profiles=profiles)
    hosted = hosted_catalog()
    logger.info(f"Site catalog: {args.sites_yml}: {action}"
                + (f" (merged over hosted {hosted})" if hosted else ""))
    if style is None and hosted and args.execution_site != 'local':
        logger.info(f"The hosted catalog {hosted} decides how "
                    f"{args.execution_site!r} submits; hosted catalogs name "
                    f"their site {HOSTED_SITE!r}.")
        if args.execution_site != HOSTED_SITE:
            # Nothing was written for this site, so planning works only if
            # the hosted catalog happens to define it.
            logger.warning(
                f"{args.execution_site!r} is not defined in {args.sites_yml} "
                f"and hosted catalogs normally define only {HOSTED_SITE!r}: "
                f"pegasus-plan will fail unless {hosted} has it. Use "
                f"-e {HOSTED_SITE}, or --site-style condor/slurm to describe "
                f"{args.execution_site!r}.")
    return style


def main():
    parser = argparse.ArgumentParser(
        description="generate a pegasus workflow",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f'''
Examples:
  %(prog)s --sra-id-list examples/1/sra_ids.txt --reference examples/1/crassphage.fna
  %(prog)s ... -e condorpool                      # HTCondor pool (default)
  %(prog)s ... --site-style slurm --project my_lab  # hosted catalog ({HOSTED_SITE!r})
  %(prog)s ... -e compute --site-style slurm --queue cpu --project my_lab
''')
    parser.add_argument('--sra-id-list', dest='sra_id_list', default=None, required=True,
                        help='Specifies list of SRA IDs to include in the search')
    parser.add_argument('--reference', dest='reference', default=None, required=True,
                        help='Specifies the fasta file to use as a reference for the search')

    # Execution site. The workflow states only memory/runtime; these options
    # shape the site catalog (custom_sites.py).
    parser.add_argument('-e', '--execution-site', dest='execution_site', default=None,
                        help=f"Site to plan against (default: {HOSTED_SITE!r} when "
                             "~/.pegasusrc names a hosted catalog, which call their "
                             f"site that; otherwise {DEFAULT_SITE!r})")
    parser.add_argument('--site-style', choices=('auto',) + STYLES + ('none',),
                        default='auto',
                        help="How the execution site is described in sites.yml. "
                             "auto (default): keep a sites.yml entry or hosted "
                             "catalog if one exists, else add an HTCondor site. "
                             "condor/slurm: (re)write that site's entry. none: "
                             "leave sites.yml alone.")
    parser.add_argument('--queue', metavar='PARTITION',
                        help='Batch partition/queue jobs submit to (required for '
                             '--site-style slurm without a hosted catalog)')
    parser.add_argument('--project', metavar='ACCOUNT',
                        help='Allocation/account charged on a batch site')
    parser.add_argument('--site-scratch', metavar='DIR',
                        help='Slurm only: shared scratch visible to workers and '
                             'the submit host (default: ./work)')
    parser.add_argument('--site-profile', action='append', default=[],
                        type=parse_profile, metavar='NS:KEY=VALUE',
                        help='Extra profile on the execution site, e.g. '
                             'pegasus:glite.arguments=--constraint=avx512; '
                             'repeatable')
    parser.add_argument('--shared-filesystem', choices=('auto', 'yes', 'no'),
                        default='auto',
                        help='Let jobs read inputs (incl. the container image) '
                             'directly from the submit host instead of via '
                             'staging. auto (default): on for a Slurm site, off '
                             'for HTCondor, which stages over file transfer.')
    parser.add_argument('--sites-yml', metavar='FILE', default='sites.yml',
                        help='Local site catalog (default: sites.yml). Named in '
                             'the generated properties, so pegasus-plan finds it '
                             'from any directory.')
    args = parser.parse_args(sys.argv[1:])
    if args.execution_site is None:
        args.execution_site = HOSTED_SITE if hosted_catalog() else DEFAULT_SITE

    try:
        style = setup_site_catalog(args)
    except ValueError as exc:
        parser.error(str(exc))

    if args.shared_filesystem == 'auto':
        bypass = style is not None and style != 'condor'
    else:
        bypass = args.shared_filesystem == 'yes'
    # A site that is not a condor pool stages through its own filesystem (an
    # unknown style over a hosted catalog counts: hosted catalogs are batch
    # sites), and then staged inputs are symlinks into BASE_DIR.
    batch_site = args.execution_site != 'local' and (
        style not in (None, 'condor')
        or (style is None and hosted_catalog() is not None))
    bind_wf = batch_site or bypass
    logger.info(f"Execution site: {args.execution_site} ({style or 'style not stated'})")
    logger.info("Input staging: "
                + ("bypassed (shared filesystem)" if bypass else "via staging site")
                + (f"; container binds {BASE_DIR}" if bind_wf else ""))

    write_properties(args.sites_yml, condor_site=(style == 'condor'),
                     bypass_input_staging=bypass)
    wf, tc, rc = build_workflow(args.sra_id_list, args.reference,
                                bind_workflow_dir=bind_wf)
    wf.plan(sites=[args.execution_site], output_sites=['local'], submit=True)


if __name__ == '__main__':
    main()
