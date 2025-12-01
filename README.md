# nf-rest plugin

Nextflow executor plugin that sends each task as a JSON payload to the `nf-server` REST gateway, implementing the `rest` executor.

[nf-server repository](https://github.com/leoustc/nf-server)

`nf-server` is a gateway/proxy service that receives tasks from this plugin, queues them, and dispatches them to worker proxies that provision and monitor runs (OCI/Kubernetes). Proxies share a workdir (`/opt/bot`) and can run in different compartments/subnets; the gateway exposes the REST API your Nextflow jobs talk to.

<p align="center">
  <img src="nf-rest.jpg" alt="nf-rest architecture" width="200" height="200" />
</p>

<p align="center">
  <a href="https://www.youtube.com/watch?v=yhLFBJLs_zc" target="_blank">
    <img src="https://img.youtube.com/vi/yhLFBJLs_zc/0.jpg" alt="nf-rest video overview" width="600" />
  </a>
</p>

## Environment

From the repository root:

```bash
bash bootstrap.sh     # create the nf-gradle-env Conda environment
source environment    # activate it (conda activate nf-gradle-env)
```

Run all build and Nextflow commands inside this environment.

## Building and installing

From this directory (`nf-rest`), with the environment active:

```bash
make assemble
make install
```

This builds the plugin JAR and installs it into `~/.nextflow/plugins/nf-rest-<version>` (version comes from the `version` file).

## Using in Nextflow

In your `nextflow.config` or a profile config:

```groovy
plugins {
    id 'nf-rest@0.9.0'
}

process {
    executor = 'rest'
}

rest {
    endpoint = 'http://localhost:7011'
    api_key  = 'api-secret-token'
}
```

Ensure `nf-server` is running and reachable at the configured `endpoint` before starting your pipeline.

## Accelerators
Declare accelerators in your processes to drive shape selection by the gateway/proxy:

```groovy
process B {
    cpus 2
    memory '4 GB'
    accelerator 1, type: 'VM.GPU.A10.1'   // GPU shape
    publishDir params.outdir, mode: 'copy'
    input:
    val x
    output:
    path "b_${x}.txt"
    script:
    """
    echo "B got: ${x}" > b_${x}.txt
    """
}
```

- `accelerator <count>, type: '<shape>'` mirrors Nextflow’s accelerator directive.
- Use GPU shapes (e.g., `VM.GPU.A10.1`) or CPU shapes (e.g., `VM.Standard.E5.Flex`), and bare-metal shapes (`BM.*`) for larger workloads; the proxy picks the matching OCI/K8s runner.
- `accelerator` count can be greater than 1 (e.g., 2 or 3) to request multiple accelerators; the runner pool will scale accordingly, and multi-accelerator nodes can form a Slurm cluster for process-level parallelism when needed.
- The sample pipelines (`test/dev.nf`, `test/main.nf`) include both CPU and GPU examples.

## Scaled Accelerators [Preview]
- Requests like `accelerator 2, type: 'VM.GPU.A10.1'` ask for multiple accelerators; the scheduler places the task on a node with at least that many devices or on a small cluster if it needs to spread (for BM shapes, it provisions bare metal).
- For CPU-only scaling, you can combine higher `accelerator` counts with BM CPU shapes (e.g., `BM.Standard.E4.128`) to get large single-node capacity.
- Multi-accelerator requests can be backed by a transient Slurm cluster sized to the count, so the process can fan out internally while remaining a single Nextflow task.
- Keep `publishDir`/S3 staging enabled so outputs and logs are collected when the multi-accelerator run completes.

## Scaled Accelerators with RDMA [Coming soon]
- If the requested shape supports RDMA, nf-server will bring up an RDMA-enabled cluster for maximum throughput (see OCI HPC shapes: https://docs.oracle.com/en-us/iaas/Content/Compute/References/high-performance-compute.htm); otherwise a TCP/IP Slurm cluster is built.
- Slurm is provisioned on demand for the task and destroyed/cleaned after completion, so resources are only held while needed.

## Sample workflows (under `test/`)
- `main.nf` – primary demo pipeline (fan-out/fan-in).
- `dev.nf` – lighter development run.
- `rest.config.sample` – template config; copy to `rest.config` and fill S3/endpoint values.
- `Makefile` – `make prod` runs `main.nf` with `rest.config`.

Quick run:
```bash
cd nf-rest/test
cp rest.config.sample rest.config   # edit with your endpoint/bucket/api key
make prod                           # or: nextflow run main.nf -c rest.config
```

Prereqs: Nextflow installed, nf-rest plugin built/installed (`make assemble install`), and the nf-server gateway running (see `nf-server/README.md`).
