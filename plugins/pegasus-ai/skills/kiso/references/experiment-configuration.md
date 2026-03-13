# Kiso Experiment Configuration Reference

Kiso is a framework for running reproducible experiments on cloud/edge testbeds. An
`experiment.yml` has four top-level sections: `sites`, `software`, `deployment`,
and `experiments`. Labels are the glue — names you invent (e.g. `submit`, `execute`,
`central-manager`) that connect machines defined in `sites` to software, deployment
roles, and experiment targets.

## Top-level structure

```yaml
name: my-experiment          # optional but recommended

sites:      [...]            # required: what machines to provision
software:   {...}            # optional: software to install
deployment: {...}            # optional: cluster software (HTCondor)
experiments: [...]           # required: what to run
```

---

## Sites

### Vagrant (local VMs — good for development/testing)

```yaml
sites:
  - kind: vagrant
    backend: virtualbox
    box: bento/rockylinux-9
    user: vagrant
    config_extra: 'config.vm.synced_folder ".", "/vagrant", disabled: true'
    resources:
      machines:
        - labels:
            - submit
          flavour: "large"    # tiny | small | medium | large | xlarge
          number: 1
        - labels:
            - execute
          flavour: "medium"
          number: 2
      networks:
        - labels:
            - r1
          cidr: "172.16.42.0/16"
```

Install: `pip install kiso[vagrant]`

### Chameleon KVM (cloud VMs)

```yaml
sites:
  - kind: chameleon
    walltime: "04:00:00"
    lease_name: my-lease
    rc_file: secrets/chi-tacc-app-cred-openrc.sh
    key_name: my-ssh-key
    image: CC-Ubuntu22.04
    resources:
      machines:
        - labels:
            - submit
            - central-manager
          flavour: compute_zen3
          number: 1
        - labels:
            - execute
          flavour: compute_zen3
          number: 4
      networks:
        - sharednet1
```

Install: `pip install kiso[chameleon]`

### Chameleon Edge (edge devices / containers)

```yaml
sites:
  - kind: chameleon-edge
    walltime: "04:00:00"
    lease_name: edge-lease
    rc_file: secrets/chi-edge-app-cred-openrc.sh
    resources:
      machines:
        - labels:
            - edge-execute
          machine_name: raspberrypi4-64
          count: 2
          container:
            name: execute
            image: rockylinux:8
```

Install: `pip install kiso[chameleon]`

### FABRIC testbed

```yaml
sites:
  - kind: fabric
    rc_file: secrets/fabric_rc
    walltime: "02:00:00"
    resources:
      machines:
        - labels:
            - submit
          site: TACC
          image: default_rocky_8
          flavour: m1.large
          number: 1
        - labels:
            - execute
          site: TACC
          image: default_rocky_8
          flavour: m1.large
          number: 2
      networks:
        - labels:
            - v4
          kind: FABNetv4
          site: TACC
          nic:
            kind: SharedNIC
            model: ConnectX-6
```

Install: `pip install kiso[fabric]`

### Multi-site (combine cloud + edge)

```yaml
sites:
  - kind: chameleon-edge
    walltime: "04:00:00"
    lease_name: edge-lease
    rc_file: secrets/chi-edge-openrc.sh
    resources:
      machines:
        - labels:
            - edge-execute
          machine_name: raspberrypi4-64
          count: 1
          container:
            name: execute
            image: pegasus/myapp

  - kind: chameleon
    walltime: "04:00:00"
    lease_name: cloud-lease
    rc_file: secrets/chi-tacc-openrc.sh
    key_name: my-key
    image: CC-Ubuntu22.04
    resources:
      machines:
        - labels:
            - central-manager
            - submit
            - cloud-execute
          flavour: compute_zen3
          number: 1
      networks:
        - sharednet1
```

---

## Software

### Apptainer (Singularity)

```yaml
software:
  apptainer:
    labels:
      - execute
```

### Docker

```yaml
software:
  docker:
    labels:
      - execute
```

### Ollama (LLM serving)

```yaml
software:
  ollama:
    - labels:
        - llm-node
      models:
        - llama3:8b
      environment:
        OLLAMA_MAX_QUEUE: 512
```

---

## Deployment

### HTCondor

HTCondor kinds: `central-manager`, `submit`, `execute`, `personal`

- `central-manager`: the scheduler/negotiator node (one per cluster)
- `submit`: where users submit jobs (where Pegasus runs)
- `execute`: worker nodes that run jobs
- `personal`: single-node all-in-one (useful for testing)

```yaml
deployment:
  htcondor:
    - kind: central-manager
      labels:
        - central-manager

    - kind: submit
      labels:
        - submit
      # config_file: config/submit-condor_config   # optional custom config

    - kind: execute
      labels:
        - execute
      # config_file: config/exec-condor_config     # optional

    # OR for single-node testing:
    # - kind: personal
    #   labels:
    #     - submit
```

**Rule**: The `submit_node_labels` in every `pegasus` experiment must match labels
configured as `submit` or `personal` HTCondor nodes.

---

## Experiments

### Pegasus workflow experiment

```yaml
experiments:
  - kind: pegasus
    name: my-workflow
    description: Run my Pegasus workflow
    count: 1                          # number of times to run (default: 1)
    main: bin/workflow_generator.py   # script to generate+submit the workflow
    submit_node_labels:
      - submit                        # must be an HTCondor submit or personal node

    # Optional: copy files to remote nodes before running
    inputs:
      - labels:
          - execute
        src: data/reference.fa        # local path
        dst: ~kiso/my-workflow/       # remote path (~kiso expands to kiso user home)

    # Optional: run setup scripts before the experiment
    setup:
      - labels:
          - submit
        script: |
          #!/bin/bash
          chmod +x bin/workflow_generator.py
          pip install pegasus-wms

    # Optional: run scripts after the experiment completes
    post_scripts:
      - labels:
          - submit
        script: |
          #!/bin/bash
          echo "Workflow complete"

    # Optional: copy output files back to local machine
    outputs:
      - labels:
          - submit
        src: ~kiso/my-workflow/output/results.txt
        dst: ./results/
```

**The `main` script** must generate and submit the Pegasus workflow. It should:
- Call `workflow_generator.py` (or similar) to build the DAG
- Call `pegasus-plan` to plan the workflow
- Either call `pegasus-run` to submit it, or use the Python API with `wf.run()`

Kiso detects the submit directory by parsing output for patterns like:
- `pegasus-run <submit-dir>`
- `submit_dir: "<submit-dir>"`

### Shell experiment

```yaml
experiments:
  - kind: shell
    name: hello-world
    description: Run a simple shell script
    scripts:
      - labels:
          - submit
        script: |
          #!/bin/bash
          echo "Hello from Kiso!" | tee output/hello.txt
    inputs:
      - labels:
          - submit
        src: data/input.txt
        dst: ~kiso/
    outputs:
      - labels:
          - submit
        src: output/hello.txt
        dst: ./output/
```

---

## Complete example: Pegasus workflow on Vagrant (local testing)

```yaml
name: tnseq-experiment

sites:
  - kind: vagrant
    backend: virtualbox
    box: bento/rockylinux-9
    user: vagrant
    config_extra: 'config.vm.synced_folder ".", "/vagrant", disabled: true'
    resources:
      machines:
        - labels:
            - submit
          flavour: "large"
          number: 1
        - labels:
            - execute
          flavour: "medium"
          number: 2
      networks:
        - labels:
            - r1
          cidr: "172.16.42.0/16"

software:
  apptainer:
    labels:
      - execute

deployment:
  htcondor:
    - kind: central-manager
      labels:
        - submit
    - kind: submit
      labels:
        - submit
    - kind: execute
      labels:
        - execute

experiments:
  - kind: pegasus
    name: tnseq-workflow
    description: TnSeq bioinformatics pipeline
    count: 1
    main: bin/workflow_generator.py
    submit_node_labels:
      - submit
    inputs:
      - labels:
          - submit
        src: data/
        dst: ~kiso/tnseq-workflow/
    setup:
      - labels:
          - submit
        script: |
          #!/bin/bash
          pip install pegasus-wms pyyaml
          chmod +x bin/workflow_generator.py
    outputs:
      - labels:
          - submit
        src: ~kiso/tnseq-workflow/output/
        dst: ./output/
```

## Complete example: Multi-site Pegasus on Chameleon (cloud + edge)

See `kiso-plankifier-experiment.yml` pattern — two sites (chameleon + chameleon-edge),
Apptainer on cloud execute nodes, HTCondor spanning both, Pegasus experiment submitting
from cloud submit node.

---

## Label consistency rules

1. Every label used in `software`, `deployment`, and `experiments` must be defined in
   `sites`.
2. `submit_node_labels` in `pegasus` experiments must reference labels that are
   configured as `submit` or `personal` in `deployment.htcondor`.
3. A single machine can have multiple labels (e.g., one VM can be both
   `central-manager` and `submit`).

## Kiso CLI

```sh
kiso check [experiment.yml]   # validate the configuration
kiso up [experiment.yml]      # provision infrastructure
kiso run [experiment.yml]     # run the experiments
kiso down [experiment.yml]    # destroy infrastructure
```

Default config file: `experiment.yml` in the current directory.
