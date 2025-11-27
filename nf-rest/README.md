# nf-rest plugin

Nextflow executor plugin that sends each task as a JSON payload to the `nf-server` REST gateway, implementing the `rest` executor.

<p align="center">
  <img src="../nf-rest.jpg" alt="nf-rest architecture" width="200" height="200" />
</p>

<p align="center">
  <a href="https://www.youtube.com/watch?v=yhLFBJLs_zc" target="_blank">
    <img src="https://img.youtube.com/vi/yhLFBJLs_zc/0.jpg" alt="nf-rest video overview" width="600" />
  </a>
</p>

## 1. Environment

From the repository root:

```bash
bash bootstrap.sh     # create the nf-gradle-env Conda environment
source environment    # activate it (conda activate nf-gradle-env)
```

Run all build and Nextflow commands inside this environment.

## 2. Building and installing

From this directory (`nf-rest`), with the environment active:

```bash
make assemble
make install
```

This builds the plugin JAR and installs it into `~/.nextflow/plugins/nf-rest-0.2.0` (or whatever `version` is set to in `build.gradle`).

## 3. Using in Nextflow

In your `nextflow.config` or a profile config (for example `test/res.config` in this repo):

```groovy
plugins {
    id 'nf-rest@0.7.0'
}

process {
    executor = 'rest'
}

rest {
    endpoint = 'http://localhost:7011'
    api_key  = 'api-secret-token'
}
```

Make sure `nf-server` is running and reachable at the configured `endpoint` before starting your pipeline.
