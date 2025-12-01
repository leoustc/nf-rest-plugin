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
