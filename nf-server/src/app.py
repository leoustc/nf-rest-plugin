#!/usr/bin/env python3
import asyncio
import json
import logging
import math
import os
import signal
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional, List, Tuple
import shutil
import threading

from fastapi import Depends, FastAPI, HTTPException, Header
from pydantic import BaseModel
import uvicorn
import subprocess
import pymysql
from pymysql.cursors import DictCursor

logger = logging.getLogger("rest-executor")
logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(message)s")

app = FastAPI(title="Nextflow REST Executor Service")


def log(message: str) -> None:
    logger.info(message)


class ResourceSpec(BaseModel):
    cpu: Optional[int] = None
    ram: Optional[int] = None
    gpu: Optional[int] = None
    shape: Optional[str] = None
    disk: Optional[int] = None

    class Config:
        extra = "allow"


class StorageConfig(BaseModel):
    endpoint: Optional[str] = None
    region: Optional[str] = None
    bucket: Optional[str] = None
    accessKey: Optional[str] = None
    secretKey: Optional[str] = None
    s3_workdir: Optional[str] = None


class JobSubmit(BaseModel):
    # For Nextflow integration, you'd likely pass these:
    command: str                # shell command, e.g. "bash .command.run"
    workdir: str                # working directory path (local or remote)
    env: Dict[str, str] = {}    # environment vars
    metadata: Dict[str, Any] = {}   # workflowId, taskId, process name, etc.
    resources: Optional[ResourceSpec] = None
    storage: Optional[StorageConfig] = None   # S3/minio endpoint, region, and user-defined param per job


class JobStatus(BaseModel):
    job_id: str
    status: str              # queued | running | finished | failed | killed
    returncode: Optional[int]
    stdout: Optional[str]
    stderr: Optional[str]
    metadata: Dict[str, Any]
    resources: Optional[ResourceSpec] = None


class TFVarConfig(BaseModel):
    tenancy_ocid: str
    user_ocid: str
    fingerprint: str
    private_key_path: str
    region: str
    compartment_id: str
    subnet_id: str
    shape: str
    ocpus: int
    memory_gbs: int
    image_boot_size: int
    cmd_script: str
    env_vars: str
    ssh_authorized_key: str
    bastion_host: str
    bastion_user: str
    bastion_private_key_path: str
    vm_private_key_path: str
    name: str


DB_HOST = os.getenv("DB_HOST", "mysql")
DB_PORT = int(os.getenv("DB_PORT", "3306"))
DB_USER = os.getenv("DB_USER", "rest")
DB_PASSWORD = os.getenv("DB_PASSWORD", "restpass")
DB_NAME = os.getenv("DB_NAME", "rest_executor")
_raw_keys = [os.getenv("API_KEYS", ""), os.getenv("NXF_RES_AUTH_API_KEY", "")]
API_KEYS = {
    t.strip()
    for raw in _raw_keys
    for t in raw.split(",")
    if t and t.strip()
}

WORKERS: List[Any] = []


def require_api_key(
    api_key: Optional[str] = Header(
        default=None, alias="api_key", convert_underscores=False
    ),
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
) -> Optional[str]:
    """
    Require clients to pass API keys via the api_key header when configured.
    """
    if not API_KEYS:
        return None
    provided = api_key or x_api_key
    if not provided or provided not in API_KEYS:
        raise HTTPException(status_code=401, detail="invalid api key")
    return provided


def get_db_connection():
    return pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        autocommit=True,
        cursorclass=DictCursor,
    )


def init_db() -> None:
    """
    Initialize the jobs table, retrying until the DB is reachable.
    """
    max_attempts = int(os.getenv("DB_INIT_RETRIES", "30"))
    delay = float(os.getenv("DB_INIT_DELAY", "1.0"))
    for attempt in range(1, max_attempts + 1):
        try:
            conn = get_db_connection()
            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS jobs (
                            job_id VARCHAR(64) PRIMARY KEY,
                            status VARCHAR(32) NOT NULL,
                            command TEXT NOT NULL,
                            workdir TEXT NOT NULL,
                            env TEXT,
                            metadata TEXT,
                            resources TEXT,
                            returncode INT NULL,
                            stdout LONGTEXT,
                            stderr LONGTEXT,
                            pid INT NULL,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                        )
                        """
                    )
            log("[db] jobs table is ready")
            return
        except Exception as e:
            log(f"[db] init attempt {attempt} failed: {e}")
            if attempt == max_attempts:
                log("[db] giving up initializing database")
                raise
            time.sleep(delay)


def reset_running_jobs_to_failed() -> int:
    """
    On startup, mark any jobs left in 'running' as 'failed'.
    Returns the number of rows updated.
    """
    conn = get_db_connection()
    affected = 0
    with conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE jobs SET status = %s WHERE status = %s",
                ("failed", "running"),
            )
            affected = cur.rowcount or 0
    if affected:
        log(f"[db] reset {affected} running jobs to failed on startup")
    return affected


def get_job_status_counts() -> Dict[str, int]:
    """
    Return the number of jobs in each major status plus worker count.
    Keys: running, queued, finished, failed, workers.
    """
    counts: Dict[str, int] = {
        "running": 0,
        "queued": 0,
        "finished": 0,
        "failed": 0,
        "workers": 0,
    }

    conn = get_db_connection()
    with conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT status, COUNT(*) AS cnt FROM jobs GROUP BY status"
            )
            for row in cur.fetchall():
                status = row.get("status")
                if status in counts:
                    counts[status] = int(row.get("cnt") or 0)

    u_worker_env = os.getenv("UVICORN_WORKERS")
    e_worker_env = os.getenv("EXECUTOR_WORKERS")
    worker_env = int(u_worker_env) * int(e_worker_env)

    try:
        if worker_env:
            counts["workers"] = int(worker_env)
    except ValueError:
        counts["workers"] = 0

    return counts


def _insert_job(job_id: str, submit: JobSubmit) -> None:
    conn = get_db_connection()
    with conn:
        with conn.cursor() as cur:
            # merge storage config into metadata so workers/VMs can see per-job S3 info
            metadata: Dict[str, Any] = dict(submit.metadata or {})
            if submit.storage:
                metadata.setdefault("storage", submit.storage.dict(exclude_none=True))
            cur.execute(
                """
                INSERT INTO jobs (job_id, status, command, workdir, env, metadata, resources)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    job_id,
                    "queued",
                    submit.command,
                    submit.workdir,
                    json.dumps(submit.env or {}),
                    json.dumps(metadata),
                    json.dumps(submit.resources.dict() if submit.resources else {}),
                ),
            )


def _fetch_job(job_id: str) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    with conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM jobs WHERE job_id = %s", (job_id,))
            row = cur.fetchone()
            return row


def _claim_next_job_id() -> Optional[str]:
    """
    Atomically claim the next queued job by switching it to running.
    """
    conn = get_db_connection()
    with conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT job_id FROM jobs WHERE status = %s ORDER BY created_at LIMIT 1",
                ("queued",),
            )
            row = cur.fetchone()
            if not row:
                return None
            job_id = row["job_id"]
            cur.execute(
                "UPDATE jobs SET status = %s WHERE job_id = %s AND status = %s",
                ("running", job_id, "queued"),
            )
            if cur.rowcount == 0:
                return None
            return job_id


def _claim_and_run_next_job(work_id: int) -> bool:
    """
    Claim the next queued job and run it synchronously in the same thread.
    Returns True if a job was claimed and run, False if no job was available.
    """
    job_id = _claim_next_job_id()
    if not job_id:
        return False
    returncode, stdout, stderr = _run_job_sync(work_id, job_id)
    status = "finished" if returncode == 0 else "failed"
    _update_job_after_run(job_id, returncode, stdout, stderr, status)
    log(f"[executor] job {job_id} finished status={status}")
    return True

def _run_job_sync(work_id: int, job_id: str) -> Tuple[int, str, str]:
    """
    Synchronous job runner executed in a worker thread, backed by MySQL.
    """
    row = _fetch_job(job_id)
    if not row:
        err = f"[executor] job {job_id} not found in DB"
        log(err)
        return 1, "", err

    # Locate autorun script
    name = f"{work_id:05d}-{job_id[:8]}"
    script_path = Path(__file__).resolve().parent / "oci" / "autorun.sh"
    if not script_path.exists():
        err = f"[executor] autorun script not found at {script_path}"
        log(err)
        return 1, "", err

    # Unique per-job run directory (base dir configurable via BOT_RUN_BASE_DIR)
    run_base = Path(os.getenv("BOT_RUN_BASE_DIR", "/opt/bot"))
    run_dir = run_base / f".bot{name}"
    run_dir.mkdir(parents=True, exist_ok=True)

    # Build tfvars.json for autorun.sh inside the run directory
    tfvars = build_tfvars(job_id, row, name)
    tfvars_path = run_dir / "tfvars.json"
    tfvars_path.write_text(json.dumps(tfvars, indent=2))

    # Copy all Terraform files that live alongside autorun.sh into the run directory
    for tf_file in script_path.parent.glob("*.tf"):
        shutil.copy2(tf_file, run_dir / tf_file.name)
    for yml_file in script_path.parent.glob("*.yml"):
        shutil.copy2(yml_file, run_dir / yml_file.name)

    # Write the generated command script into run_dir/cmd_script.sh
    cmd_script_content = tfvars.get("cmd_script") or ""
    cmd_script_path = run_dir / "cmd_script.sh"
    if cmd_script_content:
        if not cmd_script_content.endswith("\n"):
            cmd_script_content = f"{cmd_script_content}\n"
        cmd_script_path.write_text(cmd_script_content)
        # cmd_script_path.chmod(0o750)
        log(f"[executor] job {job_id} wrote cmd_script.sh to {cmd_script_path}")
    else:
        log(f"[executor] job {job_id} has empty cmd_script; no cmd_script.sh written")

    log(f"[executor] job {job_id} cmd_script:\n{cmd_script_content}")

    # Prepare buffers for stdout/stderr aggregation
    stdout_parts: List[str] = []
    stderr_parts: List[str] = []

    stdout_parts.append(f"[executor] job {job_id}\ncmd_script:\n{cmd_script_content}")
    stderr_parts.append(f"[executor] job {job_id}\ncmd_script:\n{cmd_script_content}")
    
    # Start the job (Terraform apply only)
    apply_cmd = ["bash", str(script_path), str(run_dir), "apply", str(tfvars_path)]
    log(
        f"[executor] job {job_id} applying infra via {apply_cmd}\n{cmd_script_content}"
    )
    apply_proc = subprocess.run(
        apply_cmd,
        cwd=str(script_path.parent),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    stdout_parts.append(apply_proc.stdout or "")

    success = apply_proc.returncode == 0
    status = "finished" if success else "failed"
    if not success:
        stderr_parts.append(
            f"[executor] autorun apply failed (code {apply_proc.returncode})\n"
        )
    
    log(f"[executor] job {job_id} autorun apply {status}")

    # Best-effort destroy: launch in background so it doesn't block next jobs
    destroy_cmd = ["bash", str(script_path), str(run_dir), "destroy", str(tfvars_path)]
    try:
        subprocess.Popen(
            destroy_cmd,
            cwd=str(script_path.parent),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        log(f"[executor] job {job_id} started background destroy via {destroy_cmd}")
    except Exception as e:
        log(f"[executor] job {job_id} destroy encountered error: {e}")

    return (0 if success else 1), "".join(stdout_parts), "".join(stderr_parts)


def _update_job_after_run(
    job_id: str, returncode: int, stdout: str, stderr: str, status: str
) -> None:
    conn = get_db_connection()
    with conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE jobs
                SET returncode = %s, stdout = %s, stderr = %s, status = %s
                WHERE job_id = %s
                """,
                (returncode, stdout, stderr, status, job_id),
            )
    log(f"job {job_id} status changed {status}")


def worker_loop(worker_id: int) -> None:
    """
    Background worker that pulls jobs from the DB and runs them.
    Synchronous implementation: claim and run in the same thread.
    """
    log(f"[worker-{worker_id}] started")
    while True:
        try:
            processed = _claim_and_run_next_job(worker_id)
        except Exception as e:
            log(f"[worker-{worker_id}] exception: {e}")
            processed = False
        if not processed:
            time.sleep(5.0)

@app.post("/jobs", response_model=JobStatus)
async def submit_job(
    submit: JobSubmit, api_key: Optional[str] = Depends(require_api_key)
):
    """
    Submit a job: run a shell command in a given workdir with env.
    Returns a job_id you can poll later.
    """
    log(f"[api] raw payload: {submit.model_dump()}")
    normalized_resources = normalize_resources(submit.resources)
    submit = submit.copy(update={"resources": normalized_resources})
    if submit.resources:
        log(
            f"[api] resources cpu={submit.resources.cpu} "
            f"ram={submit.resources.ram} gpu={submit.resources.gpu} "
            f"gpushape={submit.resources.shape}"
        )
    job_id = str(uuid.uuid4())
    log(f"[api] submitting job {job_id}: {submit.command} @ {submit.workdir}")

    # Persist job record in MySQL
    await asyncio.to_thread(_insert_job, job_id, submit)

    return JobStatus(
        job_id=job_id,
        status="queued",
        returncode=None,
        stdout=None,   # not ready yet
        stderr=None,
        metadata=submit.metadata,
        resources=submit.resources,
    )


async def _get_job_status(job_id: str) -> JobStatus:
    row = await asyncio.to_thread(_fetch_job, job_id)
    if not row:
        raise HTTPException(status_code=404, detail="Job not found")

    status = row.get("status") or "queued"
    stdout = row.get("stdout") if status in ("finished", "failed", "killed") else None
    stderr = row.get("stderr") if status in ("finished", "failed", "killed") else None

    rc_raw = row.get("returncode")
    returncode = int(rc_raw) if rc_raw is not None else None

    try:
        metadata: Dict[str, Any] = json.loads(row.get("metadata") or "{}")
    except Exception:
        metadata = {}

    resources_dict: Optional[Dict[str, Any]] = None
    raw_resources = row.get("resources")
    if raw_resources:
        try:
            resources_dict = json.loads(raw_resources)
        except Exception:
            resources_dict = None

    resources = normalize_resources(resources_dict) if resources_dict else None

    log(f"[api] status request for job {job_id[:8]}, status {status}, gateway: {get_job_status_counts()}")

    return JobStatus(
        job_id=job_id,
        status=status,
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
        metadata=metadata,
        resources=resources,
    )


@app.get("/jobs/{job_id}", response_model=JobStatus)
async def get_job(job_id: str, api_key: Optional[str] = Depends(require_api_key)):
    """
    Check job status, get stdout/stderr when finished.
    """
    return await _get_job_status(job_id)


@app.post("/jobs/{job_id}/kill", response_model=JobStatus)
async def kill_job(
    job_id: str, api_key: Optional[str] = Depends(require_api_key)
):
    """
    Kill a running job via SIGTERM.
    """
    log(f"[api] kill request for job {job_id}")

    row = await asyncio.to_thread(_fetch_job, job_id)
    if not row:
        raise HTTPException(status_code=404, detail="Job not found")

    pid_raw = row.get("pid")
    if pid_raw:
        try:
            pid = int(pid_raw)
            os.kill(pid, signal.SIGTERM)
            conn = get_db_connection()
            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE jobs SET status = %s WHERE job_id = %s",
                        ("killed", job_id),
                    )
        except Exception as e:
            prev_err = (row.get("stderr") or "") + f"\n[kill] exception: {e}"
            conn = get_db_connection()
            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE jobs SET status = %s, stderr = %s WHERE job_id = %s",
                        ("failed", prev_err, job_id),
                    )

    return await _get_job_status(job_id)


def normalize_resources(resources: Optional[ResourceSpec]) -> Optional[ResourceSpec]:
    """
    Allow alternate field names (acceleratornum, acceleratorshape) and coerce into ResourceSpec.
    """
    if resources is None:
        return None

    data = resources.dict() if isinstance(resources, ResourceSpec) else dict(resources)

    def get_first(keys):
        for key in keys:
            if key in data and data[key] is not None:
                return data[key]
        return None

    gpu = data.get("gpu") if data.get("gpu") is not None else data.get("acceleratornum")
    shape = get_first(
        ("shape", "gpushape", "acceleratorshape", "accelerator_shape")
    )
    disk = get_first(
        (
            "disk",
            "disk_size",
            "disk_gb",
            "image_boot_size",
            "boot_disk",
            "bootdisk",
            "bootdisk_size",
        )
    )

    return ResourceSpec(
        cpu=data.get("cpu"),
        ram=data.get("ram"),
        gpu=gpu,
        shape=shape,
        disk=disk,
    )


def normalize_ram_gb(value: Optional[Any]) -> Optional[int]:
    """
    Convert memory values expressed in bytes (as emitted by Nextflow) to whole GB.
    """
    if value is None:
        return None
    try:
        ram = float(value)
    except (TypeError, ValueError):
        return None
    if ram <= 0:
        return None
    if ram > 1_000_000:
        ram = math.ceil(ram / (1024 ** 3))
    return int(ram)


def build_tfvars(job_id: str, row: Dict[str, Any], name: str) -> Dict[str, Any]:
    """
    Assemble tfvars payload for autorun/terraform apply using TFVarConfig.
    Values come from:
    - Global environment (populated by entry.sh) for OCI/bastion/SSH defaults
    - Per-job env (S3 + NXF_* passed in `env`)
    - Per-job resources (cpu/ram/shape/disk)
    """
    try:
        raw_meta = row.get("metadata") or "{}"
        metadata: Dict[str, Any] = json.loads(raw_meta)
    except Exception:
        metadata = {}

    storage: Dict[str, Any] = metadata.get("storage") or {}

    resources_obj: Optional[ResourceSpec] = None
    raw_resources = row.get("resources")
    if raw_resources:
        try:
            resources_dict = json.loads(raw_resources)
            resources_obj = normalize_resources(resources_dict)
        except Exception as exc:
            log(f"[executor] unable to parse resources for job {job_id}: {exc}")

    def as_int(val: Optional[Any], fallback: int) -> int:
        try:
            return int(val)
        except Exception:
            return fallback

    tenancy = os.getenv("TF_VAR_tenancy_ocid", "")
    user = os.getenv("TF_VAR_user_ocid", "")
    fingerprint = os.getenv("TF_VAR_fingerprint", "")
    region = os.getenv("TF_VAR_region", "")
    key_file = os.getenv("TF_VAR_private_key_path", "")

    shape_default = os.getenv("DEFAULT_SHAPE", "VM.Standard.E3.Flex")
    cpu_default = int(os.getenv("DEFAULT_OCPU", "1"))
    ram_default = int(os.getenv("DEFAULT_MEMORY_IN_GB", "2"))
    boot_default = int(os.getenv("DEFAULT_BOOTDISK_IN_GB", "1024"))

    if resources_obj is not None:
        shape = resources_obj.shape or shape_default
        ram_norm = normalize_ram_gb(resources_obj.ram)
        ram = as_int(ram_norm, ram_default)
        cpu = as_int(resources_obj.cpu, cpu_default)
        boot = as_int(resources_obj.disk, boot_default)
    else:
        shape = shape_default
        cpu = cpu_default
        ram = ram_default
        boot = boot_default

    s3_bucket = str(storage.get("bucket") or "")
    s3_workdir = str(storage.get("s3_workdir") or row.get("workdir") or "")
    s3_endpoint = str(storage.get("endpoint") or "")
    s3_region = str(storage.get("region") or "us-east-1")
    s3_access = str(storage.get("accessKey") or "")
    s3_secret = str(storage.get("secretKey") or "")
    nxf_command = str(row.get("command") or "bash .command.run")
    nxf_workdir = str(row.get("workdir") or "/opt/nxf-work")
    nxf_s3_uri = f"s3:/{s3_workdir}"

    log(
        f"[executor] job {job_id} resources shape={shape} cpu={cpu} ram={ram} boot={boot}"
    )
    log(
        f"[executor] job {job_id} storage: endpoint={s3_endpoint} region={s3_region} "
        f"bucket={s3_bucket} s3_workdir={s3_workdir}"
    )

    env_vars = "\n".join(
        [
            f'export S3_ENDPOINT="{s3_endpoint}"',
            f'export S3_REGION="{s3_region}"',
            f'export S3_BUCKET="{s3_bucket}"',
            f'export S3_ACCESS_KEY="{s3_access}"',
            f'export S3_SECRET_KEY="{s3_secret}"',
            f'export S3_WORKDIR="{s3_workdir}"',
            f'export NXF_COMMAND="{nxf_command}"',
            f'export NXF_WORKDIR="{nxf_workdir}"',
            f'export NXF_S3_URI="{nxf_s3_uri}"',
        ]
    )

    if s3_endpoint != "" and s3_bucket != "":
        s3_url = f"s3:/{s3_workdir}"
        localdir = f"{s3_workdir}"
        cmd_script = f"""
#!/bin/bash
set -euo pipefail
{env_vars}
export AWS_ACCESS_KEY_ID={s3_access}
export AWS_SECRET_ACCESS_KEY={s3_secret}
export AWS_DEFAULT_REGION={s3_region}
export AWS_S3_FORCE_PATH_STYLE=1
mkdir -p {localdir}
cd {localdir}
aws --endpoint-url {s3_endpoint} s3 sync {s3_url}/ {localdir}/
echo {nxf_command} 
eval {nxf_command}
echo "ok" > ok.txt
aws --endpoint-url {s3_endpoint} s3 sync {localdir}/ {s3_url}/
echo "done" > /var/run/bootstrap.done
""".strip()
    else:
        cmd_script = f"""
#!/bin/bash
set -euo pipefail
{env_vars}
cd {nxf_workdir}
echo {nxf_command} 
eval {nxf_command}
echo "ok" > ok.txt
echo "done" > /var/run/bootstrap.done
""".strip()

    bastion_host = os.getenv("TF_VAR_bastion_host") or os.getenv("BASTION_IP", "")
    bastion_user = os.getenv("TF_VAR_bastion_user") or os.getenv("BASTION_USER", "")
    bastion_key = os.getenv("TF_VAR_bastion_private_key_path") or os.getenv(
        "BASTION_SSH_KEY", ""
    )

    vm_key = os.getenv("TF_VAR_vm_private_key_path") or os.getenv(
        "VM_SSH_PRIVATE_KEY_PATH", ""
    )

    ssh_key = os.getenv("TF_VAR_ssh_authorized_key", "")

    cfg = TFVarConfig(
        tenancy_ocid=tenancy,
        user_ocid=user,
        fingerprint=fingerprint,
        private_key_path=str(Path(key_file).expanduser()),
        region=region,
        compartment_id=os.getenv("COMPARTMENT_ID", os.getenv("TF_VAR_compartment_id", "")),
        subnet_id=os.getenv("SUBNET_ID", os.getenv("TF_VAR_subnet_id", "")),
        shape=shape,
        ocpus=cpu,
        memory_gbs=ram,
        image_boot_size=boot,
        cmd_script=cmd_script,
        env_vars=env_vars,
        ssh_authorized_key=ssh_key,
        bastion_host=bastion_host,
        bastion_user=bastion_user or "opc",
        bastion_private_key_path=bastion_key,
        vm_private_key_path=str(Path(vm_key).expanduser()),
        name=name,
    )

    return cfg.model_dump(exclude_none=True)


@app.on_event("startup")
async def start_workers() -> None:
    """
    Start background worker coroutines based on environment variable.
    """
    # Ensure schema exists
    await asyncio.to_thread(init_db)
    await asyncio.to_thread(reset_running_jobs_to_failed)

    worker_env = os.getenv("EXECUTOR_WORKERS")
    if not worker_env:
        raise RuntimeError("EXECUTOR_WORKERS environment variable must be set")
    worker_count = int(worker_env)
    for i in range(worker_count):
        t = threading.Thread(target=worker_loop, args=(i,), daemon=True)
        t.start()
        WORKERS.append(t)
    log(f"[executor] start with {get_job_status_counts()}")

if __name__ == "__main__":
    # Run: python rest_executor_service.py
    uvicorn.run(app, host="0.0.0.0", port=8080)
