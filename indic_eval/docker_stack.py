"""
Wraps `docker compose` for the CeRAI stack — start, stop, exec, importer.

The CeRAI compose file (docker-compose.yml in AIEvalTool_test/AIEvaluationTool/)
already declares healthchecks for db / interface-manager / app-backend, so
`compose up -d --wait` is enough to know the stack is ready.

If the user's docker daemon requires group membership (`docker` group), wrap the
whole CLI call: `sg docker -c "indic-eval run ..."`.  We don't bake that in.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

CERAI_DIR = Path(
    "/home/aviralkaintura/Desktop/Projects/Gates_Foundation/AIEvalTool_test/AIEvaluationTool"
)
CONFIG_IN_CONTAINER = "/app/config.json"


class DockerError(RuntimeError):
    pass


def _check_docker_available() -> None:
    if shutil.which("docker") is None:
        raise DockerError("docker CLI not found on PATH")
    r = subprocess.run(["docker", "compose", "version"], capture_output=True, text=True)
    if r.returncode != 0:
        raise DockerError(f"`docker compose` not working: {r.stderr.strip()}")


# Services Track 2 actually depends on.  We don't wait on nginx /
# app-frontend / tdms-frontend because those are the web UI and may be
# unhealthy on a headless host without affecting the audit.
REQUIRED_SERVICES = ("db", "interface-manager", "app-backend")


def _service_health(service: str, cerai_dir: Path = CERAI_DIR) -> str:
    """Return health status of a compose service: 'healthy' / 'starting' / 'unhealthy' / 'none'."""
    r = subprocess.run(
        ["docker", "compose", "ps", "--format", "{{.Health}}", service],
        cwd=cerai_dir, capture_output=True, text=True,
    )
    if r.returncode != 0:
        return "none"
    return r.stdout.strip().split("\n")[0].strip() or "none"


def start(cerai_dir: Path = CERAI_DIR, with_sarvam_profile: bool = False,
          timeout_s: int = 120) -> None:
    """Bring the CeRAI stack up and wait for db / interface-manager / app-backend
    to report `healthy`.  Web-UI containers are not required for the audit and
    are not waited on (they often report unhealthy on headless hosts).
    """
    import time
    _check_docker_available()
    if not cerai_dir.exists():
        raise DockerError(f"CeRAI directory not found: {cerai_dir}")
    cmd = ["docker", "compose", "up", "-d"]
    if with_sarvam_profile:
        cmd = ["docker", "compose", "--profile", "sarvam", "up", "-d"]
    r = subprocess.run(cmd, cwd=cerai_dir, capture_output=True, text=True)
    if r.returncode != 0:
        raise DockerError(
            f"docker compose up failed (rc={r.returncode}):\n{r.stderr}\n"
            f"Permission errors usually mean the docker group isn't active "
            f"in the current shell — wrap via `sg docker -c '...'`."
        )
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        statuses = {svc: _service_health(svc, cerai_dir) for svc in REQUIRED_SERVICES}
        if all(s == "healthy" for s in statuses.values()):
            return
        unhealthy = {k: v for k, v in statuses.items() if v != "healthy"}
        time.sleep(2)
    raise DockerError(
        f"timed out after {timeout_s}s waiting for required services to be healthy.  "
        f"Last status: {statuses}"
    )


def stop(cerai_dir: Path = CERAI_DIR) -> None:
    """Bring the CeRAI stack down."""
    _check_docker_available()
    r = subprocess.run(
        ["docker", "compose", "down"], cwd=cerai_dir, capture_output=True, text=True
    )
    if r.returncode != 0:
        raise DockerError(f"docker compose down failed:\n{r.stderr}")


def exec_in(
    service: str,
    cmd: list[str],
    cerai_dir: Path = CERAI_DIR,
    workdir: str | None = "/app",
    capture: bool = True,
) -> subprocess.CompletedProcess:
    """Run a command inside a running compose service container.

    `workdir=None` skips the `-w` flag (use for the `db` container which has no `/app`).
    """
    full = ["docker", "compose", "exec", "-T"]
    if workdir:
        full.extend(["-w", workdir])
    full.extend([service, *cmd])
    return subprocess.run(
        full, cwd=cerai_dir, capture_output=capture, text=True, check=False
    )


def run_importer(cerai_dir: Path = CERAI_DIR) -> None:
    """Run CeRAI's importer to load the manifest into MariaDB.

    Idempotent — the importer recognises already-imported rows by primary key.
    """
    r = exec_in(
        "app-backend",
        ["python3", "src/app/importer/main.py", "--config", CONFIG_IN_CONTAINER],
        cerai_dir=cerai_dir,
    )
    if r.returncode != 0:
        raise DockerError(f"importer failed:\n{r.stdout}\n{r.stderr}")


def query_db(sql: str, cerai_dir: Path = CERAI_DIR) -> str:
    """Run a SQL query against the CeRAI MariaDB.  Returns raw text output."""
    r = exec_in(
        "db",
        [
            "mariadb",
            "-u", "aiet_user",
            "-paiet_password",
            "aievaluationtool",
            "-B", "-N",
            "-e", sql,
        ],
        cerai_dir=cerai_dir,
        workdir=None,  # db container has no /app
    )
    if r.returncode != 0:
        raise DockerError(f"DB query failed (rc={r.returncode}):\nstdout: {r.stdout}\nstderr: {r.stderr}")
    return r.stdout
