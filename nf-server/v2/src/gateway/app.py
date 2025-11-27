#!/usr/bin/env python3
import asyncio
import json
import logging
import os
import time
import uuid
from typing import Any, Dict, Optional

from fastapi import Depends, FastAPI, HTTPException, Header
from pydantic import BaseModel
import uvicorn
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
    accelerator: Optional[int] = 0
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
    status: str              # queued | running | finished | failed | killed | killing | cleaned
    returncode: Optional[int]
    stdout: Optional[str]
    stderr: Optional[str]
    metadata: Dict[str, Any]
    resources: Optional[ResourceSpec] = None


DB_HOST = os.getenv("DB_HOST", "mysql")
DB_PORT = int(os.getenv("DB_PORT") or 3306)
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
HEARTBEAT_SECONDS = float(os.getenv("HEARTBEAT_SECONDS", "3"))
_heartbeat_task: Optional[asyncio.Task] = None

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


@app.on_event("startup")
async def _startup_heartbeat() -> None:
    global _heartbeat_task
    if HEARTBEAT_SECONDS <= 0:
        log("[heartbeat] disabled (HEARTBEAT_SECONDS <= 0)")
        return
    _heartbeat_task = asyncio.create_task(_heartbeat_loop())
    log(f"[heartbeat] started with interval {HEARTBEAT_SECONDS}s")


@app.on_event("shutdown")
async def _shutdown_heartbeat() -> None:
    global _heartbeat_task
    if _heartbeat_task:
        _heartbeat_task.cancel()
        try:
            await _heartbeat_task
        except asyncio.CancelledError:
            pass


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
    Keys: running, queued, pending, finished, failed, killing, killed, cleaned.
    """
    counts: Dict[str, int] = {
        "running": 0,
        "queued": 0,
        "pending": 0,
        "finished": 0,
        "failed": 0,
        "killing": 0,
        "killed": 0,
        "cleaned": 0,
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

    return counts


async def _heartbeat_loop() -> None:
    while True:
        try:
            counts = await asyncio.to_thread(get_job_status_counts)
            log(f"[heartbeat] queue {counts}")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log(f"[heartbeat] error: {e}")
        await asyncio.sleep(HEARTBEAT_SECONDS)


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


@app.post("/jobs", response_model=JobStatus)
async def submit_job(
    submit: JobSubmit, api_key: Optional[str] = Depends(require_api_key)
):
    """
    Submit a job: run a shell command in a given workdir with env.
    Returns a job_id you can poll later.
    """
    log(f"[api] raw payload: {submit.dict()}")
    normalized_resources = normalize_resources(submit.resources)
    submit = submit.copy(update={"resources": normalized_resources})
    if submit.resources:
        log(
            f"[api] resources cpu={submit.resources.cpu} "
            f"ram={submit.resources.ram} accelerator={submit.resources.accelerator} "
            f"shape={submit.resources.shape}"
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
    stdout = row.get("stdout") if status in ("finished", "failed", "killed", "cleaned") else None
    stderr = row.get("stderr") if status in ("finished", "failed", "killed", "cleaned") else None

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

    log(f"[api] job {job_id[:8]} status {status}, {get_job_status_counts()}")

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
    Request a job kill: mark status as killing so workers can react.
    """
    log(f"[api] kill request for job {job_id}")

    row = await asyncio.to_thread(_fetch_job, job_id)
    if not row:
        raise HTTPException(status_code=404, detail="Job not found")

    conn = get_db_connection()
    with conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE jobs SET status = %s WHERE job_id = %s",
                ("killing", job_id),
            )
    log(f"[executor] gateway ready: {get_job_status_counts()}")

    return await _get_job_status(job_id)


def normalize_resources(resources: Optional[ResourceSpec]) -> Optional[ResourceSpec]:
    """
    Allow alternate field names (accelerator, acceleratornum, acceleratorshape, acceleratorShape) and coerce into ResourceSpec.
    """
    if resources is None:
        return None

    data = resources.dict() if isinstance(resources, ResourceSpec) else dict(resources)

    def get_first(keys):
        for key in keys:
            if key in data and data[key] is not None:
                return data[key]
        return None

    accelerator_raw = data.get("accelerator")
    if accelerator_raw is None:
        accelerator_raw = data.get("gpu")
    if accelerator_raw is None:
        accelerator_raw = data.get("acceleratornum")
    try:
        accelerator = int(accelerator_raw) if accelerator_raw is not None else 0
    except Exception:
        accelerator = 0

    shape = get_first(
        ("acceleratorShape", "acceleratorshape", "accelerator_shape", "shape", "gpushape")
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
        accelerator=accelerator,
        shape=shape,
        disk=disk,
    )


def normalize_ram_gb(value: Optional[Any]) -> Optional[int]:
    # Not used in the gateway; retained for compatibility.
    return None


@app.on_event("startup")
async def start_workers() -> None:
    """
    Initialize DB and reset any stale running jobs to failed.
    """
    await asyncio.to_thread(init_db)
    await asyncio.to_thread(reset_running_jobs_to_failed)
    log(f"[executor] gateway ready: {get_job_status_counts()}")

if __name__ == "__main__":
    # Run: python rest_executor_service.py
    uvicorn.run(app, host="0.0.0.0", port=8080)
