"""Top-level orchestrator — start docker if needed, run tracks, write metadata."""
from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .config import Preset
from .docker_stack import start as docker_start, stop as docker_stop
from .manifest import manifest_sha256
from .tracks.cerai import run_cerai_track
from .tracks.ours import run_ours_track


def _git_sha(workspace: Path) -> str:
    try:
        # Walk up looking for a .git directory; eval_workspace itself isn't a repo.
        for p in [workspace, *workspace.parents]:
            if (p / ".git").exists():
                r = subprocess.run(
                    ["git", "rev-parse", "HEAD"],
                    cwd=p, capture_output=True, text=True, check=False,
                )
                if r.returncode == 0:
                    return r.stdout.strip()
        return "not-a-git-repo"
    except Exception:
        return "unknown"


def _write_run_metadata(workspace: Path, meta: dict) -> Path:
    """Write or overwrite results/run-metadata.json with the given dict."""
    out = workspace / "results" / "run-metadata.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(meta, indent=2, ensure_ascii=False))
    return out


def _initial_metadata(workspace: Path, preset: Preset) -> dict:
    manifest_path = workspace / preset.ours.manifest
    return {
        "indic_eval_version": __version__,
        "preset_name": preset.name,
        "preset_sha256": preset.sha256(),
        "preset_content": preset.model_dump(mode="json"),
        "manifest_path": str(manifest_path.relative_to(workspace)),
        "manifest_sha256": manifest_sha256(manifest_path) if manifest_path.exists() else None,
        "git_sha": _git_sha(workspace),
        "env_keys_set": {
            k: bool(os.environ.get(k)) for k in (
                "SARVAM_API_KEY", "OPENROUTER_API_KEY", "GOOGLE_API_KEY",
            )
        },
        "timing": {
            "started_at_utc": datetime.now(timezone.utc).isoformat(),
            "finished_at_utc": None,
            "total_seconds": None,
            "tracks": {},
        },
    }


def run_all(preset: Preset, workspace: Path, no_docker: bool = False) -> dict:
    """Run every enabled track.  Brings docker up/down if cerai track is enabled."""
    meta = _initial_metadata(workspace, preset)
    run_start = time.monotonic()
    started_docker = False
    try:
        if preset.cerai.enabled and not no_docker:
            print("== docker compose up -d --wait ==")
            t0 = time.time()
            docker_start()
            started_docker = True
            print(f"   ready in {time.time()-t0:.1f}s")
            meta["timing"]["docker_start_seconds"] = round(time.time() - t0, 2)

        meta_path = _write_run_metadata(workspace, meta)
        print(f"== run metadata: {meta_path.name} ==")

        result: dict = {}

        if preset.ours.enabled:
            print("\n== TRACK 1: our 120-prompt audit (C1..C5) ==")
            t_track = time.monotonic()
            t_track_utc = datetime.now(timezone.utc).isoformat()
            result["ours"] = run_ours_track(preset, workspace)
            meta["timing"]["tracks"]["ours"] = {
                "started_at_utc": t_track_utc,
                "finished_at_utc": datetime.now(timezone.utc).isoformat(),
                "seconds": round(time.monotonic() - t_track, 2),
            }
            _write_run_metadata(workspace, meta)
        else:
            print("\n== TRACK 1 skipped (ours.enabled=false) ==")

        if preset.cerai.enabled:
            print("\n== TRACK 2: CeRAI bundled test plans (T1+T3+T4) ==")
            t_track = time.monotonic()
            t_track_utc = datetime.now(timezone.utc).isoformat()
            result["cerai"] = run_cerai_track(preset, workspace_results=workspace / "results")
            cerai_summary_path = workspace / "results" / "cerai" / "summary.json"
            cerai_summary_path.parent.mkdir(parents=True, exist_ok=True)
            cerai_summary_path.write_text(
                json.dumps(result["cerai"], indent=2, ensure_ascii=False)
            )
            print(f"   wrote {cerai_summary_path}")
            meta["timing"]["tracks"]["cerai"] = {
                "started_at_utc": t_track_utc,
                "finished_at_utc": datetime.now(timezone.utc).isoformat(),
                "seconds": round(time.monotonic() - t_track, 2),
            }
        else:
            print("\n== TRACK 2 skipped (cerai.enabled=false) ==")

        return result
    finally:
        meta["timing"]["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        meta["timing"]["total_seconds"] = round(time.monotonic() - run_start, 2)
        _write_run_metadata(workspace, meta)
        if started_docker:
            # We intentionally do NOT stop docker on success — keeping the
            # stack up means re-runs are instant and the user can inspect
            # results via the CeRAI web UI.  Use `indic-eval cleanup`.
            pass
