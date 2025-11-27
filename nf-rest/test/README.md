# nf-rest test workflows

Sample Nextflow pipelines and configs to exercise the `nf-rest` executor.

## Contents
- `main.nf` – primary demo pipeline (fan-out/fan-in).
- `dev.nf` – lighter development run.
- `gpu.nf` – GPU-oriented variant.
- `rest.config.sample` – template config; copy to `rest.config` and fill S3/endpoint values.
- `Makefile` – convenience target `make prod` runs `main.nf` with `rest.config`.

## Quick run
```bash
cd nf-rest/test
cp rest.config.sample rest.config   # edit with your endpoint/bucket/api key
make prod                           # or: nextflow run main.nf -c rest.config
```

Prereqs: Nextflow installed, nf-rest plugin built/installed (`cd nf-rest && make assemble install`), and the nf-server gateway running (see `nf-server/README.md`).
