# nf-rest on OCI – Cloud-Native Nextflow Remote Executor

Remote executor stack for [Nextflow](https://www.nextflow.io/) that routes tasks to a REST gateway, provisions compute on demand (Terraform/Ansible), and tears it down after completion. The reference implementation targets Oracle Cloud Infrastructure (OCI) but the pattern is provider-neutral anywhere Terraform and S3-compatible storage are available.

<p align="center">
  <img src="nf-rest.jpg" alt="nf-rest architecture" width="200" height="200" />
</p>

<p align="center">
  <a href="https://www.youtube.com/watch?v=yhLFBJLs_zc" target="_blank">
    <img src="https://img.youtube.com/vi/yhLFBJLs_zc/0.jpg" alt="nf-rest video overview" width="600" />
  </a>
</p>

## Repo layout
- `nf-server/` – REST gateway + Docker Compose deployment. See `nf-server/README.md` for prerequisites, env vars, and run instructions.
- `nf-rest/` – Nextflow executor plugin (`rest` executor) plus example configs/pipelines. See `nf-rest/README.md` for build, install, and usage.

## Problem to solve
- Managed batch executors tie pipelines to a single cloud and bury config in provider-specific knobs.
- Operational spread across multiple services makes debugging and cost control harder.
- Hybrid and multi-cloud runs require different executors and operational models.
- Governance and quotas are fragmented when execution is bound to each provider.

## Design philosophy
- Vendor-neutral pattern: any Terraform target plus S3-compatible storage; OCI is the reference.
- Open tooling: Terraform for lifecycle, Ansible for provisioning/run control, systemd for robustness, S3 APIs for data sync.
- Dynamic, pay-as-you-go compute: shape, CPU, memory, disk, and accelerator hints flow from Nextflow to the gateway; workers are created and torn down automatically.
- Central REST gateway enables multi-tenant access, policy enforcement, and cost visibility.

## Quick start
- **Run the gateway:** `cd nf-server && cp env.sample .env && docker compose up -d --build` (details in `nf-server/README.md`).
- **Build/install plugin:** `cd nf-rest && make assemble install` (bootstrap helper available; see `nf-rest/README.md`).
- **Try sample pipelines:** `cd nf-rest/test && cp rest.config.sample rest.config && make prod` or run `main.nf`/`dev.nf` directly with `-c rest.config`.

## License
Apache 2.0 (`LICENSE`; mirrored in `nf-rest/LICENSE` and `nf-server/LICENSE`).

## Disclaimer
The resources, scripts, and guidance in this repository are furnished “as is” for informational purposes only. Oracle makes no warranties, express or implied, regarding the content, including warranties of merchantability, fitness for a particular purpose, title, or non-infringement. Use is at your sole risk. Oracle and its affiliates are not liable for any damages arising from or related to use of these resources. These resources are not official product patches or updates and are not supported under Oracle’s standard support services. Oracle may modify or withdraw them at any time and has no obligation to maintain or update them. You are responsible for evaluating appropriateness and for taking adequate backups and other precautions to protect your systems and data.
