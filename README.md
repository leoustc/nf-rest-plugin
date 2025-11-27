# nf-rest on OCI – Cloud‑Native Nextflow Remote Executor

<p align="center">
  <img src="nf-rest.jpg" alt="nf-rest architecture" width="200" height="200" />
</p>

<p align="center">
  <a href="https://www.youtube.com/watch?v=yhLFBJLs_zc" target="_blank">
    <img src="https://img.youtube.com/vi/yhLFBJLs_zc/0.jpg" alt="nf-rest video overview" width="600" />
  </a>
</p>

Remote executor stack for [Nextflow](https://www.nextflow.io/) that sends tasks to a REST gateway (`nf-server`) which provisions compute dynamically (via Terraform and Ansible on OCI or any Terraform‑capable environment), executes the work, and tears resources down again.

This repository contains:

- **nf-server** – REST gateway and orchestration service.
- **nf-rest** – Nextflow executor plugin implementing the `rest` executor. Example configs and pipelines now live under `nf-rest/test`.

The design is vendor‑neutral and cloud‑native, with a first‑class implementation on Oracle Cloud Infrastructure (OCI).

## 1. Project Description: nf-rest – Dynamic Nextflow Resource Provisioning

### 1.1 Overview

**nf-rest** is a vendor‑neutral, cloud‑native Nextflow executor plugin and gateway stack. Instead of sending tasks directly to a provider‑specific batch service, Nextflow submits jobs to a lightweight REST gateway. The gateway then:

- Provisions compute resources dynamically via Terraform.
- Uses Ansible and systemd to launch and monitor workload execution on worker VMs.
- Synchronizes data via S3‑compatible APIs.
- Cleans up infrastructure after tasks complete.

Everything is built on open tooling:

- **Terraform** – manages infrastructure lifecycle.
- **Ansible** – handles provisioning, job launch, and monitoring.
- **systemd** – keeps long‑running jobs robust on worker VMs.
- **S3 APIs** – provide vendor‑neutral input/output synchronization.

While the reference implementation here targets **OCI**, the architecture is compatible with any environment that Terraform and S3‑compatible storage can reach.

### 1.2 Problem to Solve

Nextflow uses pluggable executors to separate pipeline logic from execution. Traditional cloud executors (managed batch services provided by cloud vendors) are powerful but have important drawbacks that nf-rest aims to address:

1. **Strong vendor lock‑in**  
   Each executor is provider‑specific and requires deep knowledge of cloud‑specific options, quotas, and limits.

2. **Operational complexity**  
   Managed batch services add complexity and spread configuration across multiple services, which complicates debugging and cost management.

3. **Hybrid / multi‑cloud friction**  
   Running the same pipelines across clouds or on‑prem is difficult when each environment needs a different executor and operational model.

4. **Limited centralized governance**  
   It is hard to centralize policies, quotas, and cost visibility across teams when execution is tied directly to provider‑specific services.

### 1.3 Project Goal and Solution

The main goal of nf-rest is to give Nextflow users the **convenience of cloud executors without binding them to a single vendor**.

#### 1.3.1 Vendor neutrality and open tooling

- nf-rest is designed to be vendor‑neutral: it works with any environment Terraform can target plus an S3‑compatible storage layer.
- Infrastructure is managed as code (Terraform/Ansible) rather than opaque batch services.
- Although this repo includes first‑class OCI support, the pattern is portable.

#### 1.3.2 Dynamic, pay‑as‑you‑go resource provisioning

- Nextflow pipelines request resource hints (CPU, RAM, disk, optional GPU) per process.
- The nf-rest plugin forwards these requirements to nf-server.
- nf-server generates Terraform variables and applies Terraform to create VMs matching requested shapes.
- When jobs complete, Terraform and Ansible destroy or recycle worker VMs, returning the system to an idle, low‑cost state.

#### 1.3.3 Operational transparency and simplicity

- Nextflow remains responsible for **pipeline logic**.
- nf-server, Terraform, and Ansible are responsible for **infrastructure orchestration**.
- Everything is declarative and visible:
  - Terraform plans and modules define infrastructure.
  - Ansible playbooks and systemd units define job lifecycle and behavior.

#### 1.3.4 Centralized control and cost visibility

- A central REST gateway enables **multi‑tenant** operation:
  - Apply global or per‑project limits and policies.
  - Aggregate metrics and costs by gateway, project, or profile.
- On OCI, transparent pricing combined with explicit Terraform modules makes resource usage easy to understand and audit.

## 2. Repository Layout

- `nf-server/`
  - `docker-compose.yml` – runs the REST executor service and MySQL.
  - `env.sample` – template for environment variables consumed by `docker-compose.yml`.
  - `src/app.py` – FastAPI app implementing `/jobs`, job queueing, and worker threads.
  - `src/oci/` – Terraform and Ansible content used by `autorun.sh` to provision/teardown remote instances.
  - `mysql-data/` – MySQL volume (generated at runtime).
- `nf-rest/`
  - Gradle-based Nextflow plugin implementing the `rest` executor (PF4J plugin), installed into `~/.nextflow/plugins/nf-rest-<version>`.
  - `bootstrap.sh` / `environment` – optional helper to create and activate a local build environment.
  - `src/` – plugin sources.
  - `build/` – generated build outputs.
  - `test/` – example Nextflow configs and pipelines (`rest.config`, `main.nf`, `dev.nf`, `gpu.nf`, `Makefile`) under `nf-rest/test/`. This is where the test assets live after the move.

## 3. Prerequisites

- Docker and Docker Compose
- Nextflow (tested with 25.10.0)
- Access to an S3‑compatible bucket (MinIO or a cloud vendor’s S3‑compatible service) matching `nf-rest/test/rest.config`
- OCI tenancy and network setup compatible with Terraform in `nf-server/src/oci` (for real remote runs)

## 4. Starting the REST Executor (nf-server)

From the `nf-server` directory:

```bash
cd nf-server
make fresh      # or: make all
```

This will:

- Build the `rest-executor` Docker image.
- Start:
  - `rest-executor-0` on `http://localhost:7011`
  - `mysql` with a persistent volume in `nf-server/mysql-data`
- Initialize the MySQL schema and start background worker threads.

Check logs with:

```bash
cd nf-server
make logs
```

The REST API exposes:

- `POST /jobs` – submit a job
- `GET /jobs/{id}` – query status and logs
- `POST /jobs/{id}/kill` – request termination

The service expects an API key header (`api-secret-token` by default) and uses MySQL for durable job tracking.

## 5. Building and Installing the Nextflow Plugin

From `nf-rest/`:

```bash
cd nf-rest
bash bootstrap.sh     # optional helper to create the nf-gradle-env Conda env
source environment    # activate helper env if you used bootstrap.sh
make assemble
make install
```

This builds the plugin JAR (version from `build.gradle`, currently `0.7.0`) and installs it into `~/.nextflow/plugins/nf-rest-<version>`. Run `make test` in the same directory to execute plugin unit tests.

## 6. Nextflow Configuration

The example config now lives at `nf-rest/test/rest.config` (with a templated `rest.config.sample`). Key parts:

- S3 / MinIO settings:
  - `aws { region, accessKey, secretKey, client { endpoint, s3PathStyleAccess } }`
- Plugin loading:
  - `plugins { id 'nf-rest@0.7.0'; id 'nf-amazon@3.4.1' }`
- Executor wiring:
  - `process { executor = 'rest' }`
  - `rest { endpoint = 'http://localhost:7011'; api_key = 'api-secret-token' }`
  - `executor { rest { pollInterval = '20 sec' } }` (default polling interval)

Copy `rest.config.sample` to `rest.config` and fill in bucket credentials and endpoints that match your environment. Add your own `profiles` block if you want separate dev/prod behavior.

## 7. Example Pipelines

Example pipelines are under `nf-rest/test/`:

- `main.nf` – fan‑out / fan‑in structure with processes `A`, `B`, `C`, `D`, `E`; uses `publishDir params.outdir` for selected processes and `tag` labels for easier log correlation.
- `dev.nf` – lighter development workflow.
- `gpu.nf` – GPU‑oriented example (if your environment supports it).

## 8. Running Pipelines via Makefile

From `nf-rest/test`:

```bash
cd nf-rest/test

# Copy and customize config
cp rest.config.sample rest.config

# Primary example (main.nf)
make prod

# Or run variants directly
nextflow run dev.nf -c rest.config
nextflow run gpu.nf -c rest.config --resume

```

These targets:

- Use `-c rest.config` to load the example config.
- Expect the nf-rest plugin to already be installed (from `nf-rest/make install`).
- Use `--resume` where appropriate to reuse cached work in the configured `workDir`.

## 9. Execution Flow and Lifecycle

High‑level flow:

1. **Submission from Nextflow**  
   The nf-rest plugin converts each Nextflow task into a JSON payload and POSTs it to `nf-server /jobs`.
2. **Job persistence and queueing**  
   nf-server stores job metadata in MySQL and marks it `queued`.
3. **Worker execution**  
   Background worker threads:
   - Claim queued jobs from MySQL.
   - Create a per‑job directory under `/opt/bot/.botXXXXXX`.
   - Build `tfvars.json` based on job metadata, resources, and environment.
   - Copy Terraform/Ansible files from `nf-server/src/oci`.
   - Run `oci/autorun.sh apply`.
4. **Terraform + Ansible lifecycle**
   - `autorun.sh`:
     - Runs `terraform init` with retries.
     - Applies a bootstrap target (`null_resource.bootstrap_submit`) with retries.
     - Applies the main Terraform (which triggers Ansible and polling) with retries.
   - Ansible playbooks and systemd:
     - Provision the VM.
     - Sync S3 workdir data.
     - Run the Nextflow task (`bash .command.run`).
     - Sync back results.
5. **Completion and teardown**
   - `autorun.sh` exits with the Terraform result.
   - nf-server records stdout/stderr and marks the job as finished or failed.
   - A best‑effort `destroy` is launched in the background to tear down resources.
6. **Polling from Nextflow**
   - The plugin polls `/jobs/{id}` at the configured `pollInterval` until the job is done.

## 10. Caching and `-resume`

nf-rest does **not** change how Nextflow computes cache keys or handles `-resume`:

- Cache keys are derived from:
  - Process script and configuration.
  - Inputs and parameters.
  - Selected executor‑relevant settings.
- Cached results are stored under the configured `workDir` for the run (or per profile, if you define profiles).
- When you rerun with `--resume` and the same `workDir`, Nextflow:
  - Skips re‑submitting unchanged tasks to nf-server.
  - Reuses outputs from previous runs.

For production‑style runs, use:

```bash
nextflow run nf-rest/test/main.nf -c nf-rest/test/rest.config --resume
```

with a stable `workDir`.

## 11. Notes and Caveats

- The Terraform/OCI configuration in `nf-server/src/oci` assumes specific networking, IAM, and image setup; adjust for your tenancy and security requirements.
- MySQL data is persisted under `nf-server/mysql-data`. Deleting it wipes job history; nf-server will recreate schema and wait for MySQL to become healthy.
- Poll intervals that are too aggressive can increase load on nf-server and MySQL; tune `pollInterval` per profile.
- This codebase is intended as a reference implementation and starting point; hard‑coded values (compartment IDs, shapes, S3 bucket names, etc.) must be customized before production use.

## 12. Troubleshooting

If you encounter issues:

- **Check nf-server logs**
  - `cd nf-server && make logs`
- **Check Nextflow logs**
  - `nf-rest/test/.nextflow.log`
- **Verify REST endpoint**
  - `curl -v http://localhost:7011/jobs`  
    (should return HTTP 405 for GET, which confirms the service is reachable).

Then adjust:

- `nf-rest/test/rest.config` (endpoint, workDir, cloud‑vendor / MinIO settings), and/or
- Terraform/Ansible content under `nf-server/src/oci`

to match your environment.

## 13. Oracle Workaround “As Is” Disclaimer

The resources, scripts, and guidance provided in this repository are furnished “as is” and for informational purposes only. Oracle makes no warranties, express or implied, regarding the content, including without limitation any warranties of merchantability, fitness for a particular purpose, title, or non-infringement.

The implementation and use of these resources are at your sole discretion and risk. Oracle and its affiliates shall not be liable for any damages, direct or indirect, arising from or related to the use of these resources, including, but not limited to, damages for loss of business profits, business interruption, loss of data, or any other pecuniary loss, even if Oracle has been advised of the possibility of such damages.

These resources are not official product patches or updates and are not supported under Oracle’s standard support services or agreements. Oracle may, at its sole discretion, modify or withdraw these resources at any time and bears no obligation to maintain or update them.

You are solely responsible for evaluating the appropriateness of using these resources in your environment and for taking adequate backup and other precautionary measures to protect your systems and data.
