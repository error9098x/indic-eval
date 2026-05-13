"""
indic-eval CLI — entry point for `pip install -e .` console_scripts.

Subcommands:
  run       end-to-end audit (Track 1 + Track 2)
  report    render findings.json -> static HTML
  cleanup   docker compose down (+ optional --purge-results)
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from .config import (
    Preset,
    apply_overrides,
    apply_smoke,
    filter_targets,
    filter_tracks,
    load_preset,
)


app = typer.Typer(
    name="indic-eval",
    help="Reproducible LLM evaluation harness — Indic safety/bias suite + CeRAI tool plans.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()


def _default_workspace() -> Path:
    """Workspace = directory containing the package install (eval_workspace).

    Falls back to cwd if running from an unusual install location.
    """
    pkg_dir = Path(__file__).resolve().parent.parent
    if (pkg_dir / "manifest").exists() or (pkg_dir / "presets").exists():
        return pkg_dir
    return Path.cwd()


def _load_env_file(workspace: Path) -> None:
    """Source .env from the workspace's parent (Gates_Foundation/.env) if it exists."""
    candidates = [
        workspace.parent / ".env",
        workspace / ".env",
    ]
    for envp in candidates:
        if envp.exists():
            for line in envp.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _ensure_cerai_bootstrapped(workspace: Path) -> None:
    """Run scripts/00-bootstrap-cerai.sh before Track 2 fires.

    The script is idempotent and short-circuits the expensive tarball download
    when the CeRAI tree is already in place — so calling it every run costs <1 s
    on the cached path while still re-rendering env files (catches updated keys
    in .env) and regenerating the CeRAI-format datapoints from our manifest.
    """
    bootstrap = workspace / "scripts" / "00-bootstrap-cerai.sh"
    if not bootstrap.exists():
        console.print(f"[red]missing[/red] {bootstrap}")
        raise typer.Exit(code=2)
    result = subprocess.run([str(bootstrap)], cwd=workspace, check=False)
    if result.returncode != 0:
        console.print("[red]bootstrap failed[/red] — fix the error above and re-run.")
        raise typer.Exit(code=result.returncode)


def _wipe_target_outputs(workspace: Path, target_ids: list[str]) -> None:
    """Default fresh-run cleanup: wipe per-target inference + cerai score files
    for the targets in this run, and prune the shared judge JSONLs of rows
    belonging to those targets. Other targets' data is preserved. Wipes the
    aggregate findings.json + run-metadata.json (both regenerated)."""
    import json
    results = workspace / "results"
    if not results.exists():
        return
    for tid in target_ids:
        (results / f"inference_{tid}.jsonl").unlink(missing_ok=True)
        cerai_id = tid.lower().replace("-", "_")
        (results / f"cerai_scores_{cerai_id}.jsonl").unlink(missing_ok=True)
    target_set = set(target_ids)
    for judge_file in ("c1_refusal_scores.jsonl", "c3_judge_scores.jsonl", "c4_bias_judge_scores.jsonl"):
        jp = results / judge_file
        if not jp.exists():
            continue
        kept = []
        for line in jp.read_text().splitlines():
            if not line.strip():
                continue
            try:
                if json.loads(line).get("target") not in target_set:
                    kept.append(line)
            except json.JSONDecodeError:
                pass
        jp.write_text("\n".join(kept) + ("\n" if kept else ""))
    (results / "findings.json").unlink(missing_ok=True)
    (results / "run-metadata.json").unlink(missing_ok=True)


def _build_preset(
    preset_path: Path,
    smoke: bool,
    tracks: list[str] | None,
    targets: list[str] | None,
    overrides: list[str],
) -> Preset:
    """Apply overrides in a deliberate order.

    `--smoke` is a HARD RESET (every limit collapses to 1) and runs LAST among
    the limit-touching flags, so `--set ours.limit_per_category.X=null --smoke`
    leaves X at 1, not null.  If you want to override a smoke value, drop
    --smoke and set every limit explicitly via --set.
    """
    preset = load_preset(preset_path)
    if overrides:
        preset = apply_overrides(preset, overrides)
    if smoke:
        preset = apply_smoke(preset)
    if tracks:
        preset = filter_tracks(preset, tracks)
    if targets:
        preset = filter_targets(preset, targets)
    return preset


@app.command()
def run(
    preset: Annotated[Path, typer.Option(
        "--preset", "-p",
        help="Path to the preset YAML.",
        exists=True, dir_okay=False, readable=True,
    )],
    workspace: Annotated[Path, typer.Option(
        "--workspace", "-w",
        help="Workspace directory (defaults to the install location).",
    )] = None,
    smoke: Annotated[bool, typer.Option(
        "--smoke",
        help="Collapse every limit to 1.  Hard reset — overrides any conflicting --set.",
    )] = False,
    tracks: Annotated[list[str], typer.Option(
        "--tracks",
        help="Comma-separated track list: 'ours', 'cerai', or both.",
    )] = None,
    targets: Annotated[list[str], typer.Option(
        "--targets",
        help="Comma-separated target IDs to keep (others dropped).",
    )] = None,
    set_overrides: Annotated[list[str], typer.Option(
        "--set", "-s",
        help="Override any preset key, dotted path. e.g. --set cerai.plans.T4_Language_Support.enabled=false",
    )] = None,
    no_docker: Annotated[bool, typer.Option(
        "--no-docker",
        help="Skip docker compose up/down — assume CeRAI stack is already running.",
    )] = False,
    no_report: Annotated[bool, typer.Option(
        "--no-report",
        help="Skip auto-rendering site/index.html after the run completes.",
    )] = False,
    resume: Annotated[bool, typer.Option(
        "--resume",
        help="Keep existing per-target JSONLs and skip prompts already complete. "
             "Default behaviour wipes per-target output so every run is a clean slate.",
    )] = False,
):
    """Run an end-to-end audit per the preset."""
    workspace = workspace or _default_workspace()
    _load_env_file(workspace)
    # Typer parses --tracks "ours,cerai" as a single string; split on commas.
    def _split(xs):
        out = []
        for x in xs or []:
            out.extend([s.strip() for s in x.split(",") if s.strip()])
        return out
    tracks_list = _split(tracks)
    targets_list = _split(targets)

    cfg = _build_preset(preset, smoke, tracks_list, targets_list, set_overrides or [])
    console.print(f"[bold]Preset:[/bold] {cfg.name}  (audit_date={cfg.audit_date})")
    console.print(f"  targets: {[t.id for t in cfg.targets]}")
    console.print(f"  tracks:  ours={cfg.ours.enabled}  cerai={cfg.cerai.enabled}")
    console.print(f"  workspace: {workspace}")

    if not resume:
        _wipe_target_outputs(workspace, [t.id for t in cfg.targets])

    if cfg.cerai.enabled:
        _ensure_cerai_bootstrapped(workspace)

    from .runner import run_all
    try:
        run_all(cfg, workspace, no_docker=no_docker)
    except Exception as e:
        console.print(f"[red]error:[/red] {type(e).__name__}: {e}")
        raise typer.Exit(code=2)

    if no_report:
        return
    findings = workspace / "results" / "findings.json"
    output = workspace / "site" / "index.html"
    if not findings.exists():
        console.print(f"[yellow]skip report:[/yellow] no findings.json at {findings}")
        return
    from .report import render
    render(findings, output)
    console.print(f"[green]wrote[/green] {output}")


@app.command()
def report(
    findings: Annotated[Path, typer.Option(
        "--findings", "-f",
        help="Path to findings.json (default: results/findings.json under workspace).",
    )] = None,
    output: Annotated[Path, typer.Option(
        "--output", "-o",
        help="HTML output path (default: site/index.html under workspace).",
    )] = None,
    workspace: Annotated[Path, typer.Option(
        "--workspace", "-w",
    )] = None,
):
    """Render findings.json -> static HTML."""
    workspace = workspace or _default_workspace()
    findings = findings or workspace / "results" / "findings.json"
    output = output or workspace / "site" / "index.html"
    if not findings.exists():
        console.print(f"[red]no findings.json at {findings}[/red] — run `indic-eval run` first")
        raise typer.Exit(code=2)
    from .report import render
    render(findings, output)
    console.print(f"[green]wrote[/green] {output}")


@app.command()
def cleanup(
    purge_results: Annotated[bool, typer.Option(
        "--purge-results",
        help="Also delete results/ and run-metadata.json (DESTRUCTIVE).",
    )] = False,
    workspace: Annotated[Path, typer.Option(
        "--workspace", "-w",
    )] = None,
):
    """`docker compose down`; optionally purge results."""
    workspace = workspace or _default_workspace()
    from .docker_stack import stop
    try:
        stop()
        console.print("[green]docker compose down OK[/green]")
    except Exception as e:
        console.print(f"[yellow]docker stop:[/yellow] {e}")

    if purge_results:
        import shutil
        rd = workspace / "results"
        if rd.exists():
            shutil.rmtree(rd)
            console.print(f"[red]purged[/red] {rd}")


@app.command(name="validate")
def validate_preset(
    preset: Annotated[Path, typer.Option(
        "--preset", "-p", exists=True, dir_okay=False, readable=True,
    )],
):
    """Validate a preset YAML.  Useful in CI."""
    cfg = load_preset(preset)
    console.print(f"[green]ok[/green] preset={cfg.name} sha256={cfg.sha256()[:12]}")
    console.print(f"  targets: {[t.id for t in cfg.targets]}")
    console.print(f"  ours.enabled={cfg.ours.enabled} cerai.enabled={cfg.cerai.enabled}")


if __name__ == "__main__":
    app()
