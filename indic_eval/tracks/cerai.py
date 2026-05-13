"""
CeRAI track — runs CeRAI's bundled test plans against each target via the
tool's executor + analyzer scripts inside the app-backend container.

For each target we:
  1. Patch CeRAI's config.json with that target's model/base_url/api_key_env.
  2. For each enabled (plan, metric):
       a. docker exec executor with --max-testcases = limit_per_metric.
       b. Find the new run_name in the TestRuns table (latest started).
       c. docker exec analyzer with --run-name <run_name>.
  3. Restore config.json to its original state.
  4. Export this run's CeRAI rows to results/cerai_scores_<target>.jsonl,
     filtered to the run_names we just produced (no historical rows).

The plan/metric coverage and skipped metrics match the production audit
(documented in eval_workspace/LEARNINGS.md): T1 = 8 metrics, T3 = 2 working
metrics (skipped 61, 62, 64, 65, 66 — phantom metric_ids that don't exist in
CeRAI v2.0's Metrics table), T4 = 3 working metrics.
"""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

from ..config import Preset, Target
from ..docker_stack import (
    CERAI_DIR,
    CONFIG_IN_CONTAINER,
    DockerError,
    exec_in,
    query_db,
    run_importer,
)


# Plan name -> CeRAI testplan_id (passed to the executor via --testplan-id).
# The metric list per plan now lives in the preset YAML; this map only
# converts the plan name into the integer the executor expects.
PLAN_NAME_TO_ID = {
    "T1_Responsible_AI": 1,
    "T3_Guardrails_and_Safety": 3,
    "T4_Language_Support": 4,
}


def _patch_config_for_target(target: Target, preset: Preset, cerai_dir: Path = CERAI_DIR) -> Path:
    """Rewrite CeRAI's config.json with this target's model details.

    Returns the path so we can restore later.
    """
    cfg_path = cerai_dir / "config.json"
    cfg = json.loads(cfg_path.read_text())
    cfg["target"]["application_name"] = target.id
    cfg["target"]["application_url"] = target.base_url.replace("/v1", "")
    cfg["target"]["agent_name"] = target.model
    cfg["sampling"]["api_key_env"] = target.api_key_env
    cfg["sampling"]["max_tokens"] = preset.sampling.max_tokens
    cfg["sampling"]["temperature"] = preset.sampling.temperature
    cfg["sampling"]["seed"] = preset.sampling.seed
    if preset.sampling.reasoning_effort and "sarvam" in target.base_url:
        cfg["sampling"]["reasoning_effort"] = preset.sampling.reasoning_effort
    else:
        cfg["sampling"].pop("reasoning_effort", None)
    cfg_path.write_text(json.dumps(cfg, indent=4, ensure_ascii=False))
    return cfg_path


def _restart_app_backend(cerai_dir: Path = CERAI_DIR) -> None:
    """Restart app-backend + interface-manager so config bind-mount is re-read."""
    import subprocess
    subprocess.run(
        ["docker", "compose", "restart", "app-backend", "interface-manager"],
        cwd=cerai_dir, capture_output=True, text=True, check=False,
    )
    time.sleep(4)


def _latest_run_name(cerai_dir: Path = CERAI_DIR) -> str:
    """Query the latest TestRun row (most recently inserted).

    Previously this used `WHERE start_ts > NOW() - INTERVAL 5 MINUTE`, which
    silently lost heavy metric runs that exceeded the window (sarvam's
    Robustness has 66 rows and routinely took >5 minutes).  We now rely on
    run_id monotonicity — the executor we just called creates the highest
    run_id by definition.
    """
    raw = query_db(
        "SELECT run_name FROM TestRuns ORDER BY run_id DESC LIMIT 1",
        cerai_dir=cerai_dir,
    )
    name = raw.strip().split("\n")[0].strip().strip("\r")
    if not name:
        raise DockerError("could not find latest run_name in TestRuns")
    return name


SCORE_QUERY = """
SELECT
  tr.run_id, tr.run_name, tg.target_name AS target,
  m.metric_id, m.metric_name,
  s.strategy_id, s.strategy_name,
  tc.testcase_id, tc.testcase_name,
  LEFT(p.user_prompt, 400)  AS prompt_preview,
  LEFT(c.agent_response, 800) AS response_preview,
  c.evaluation_score AS score,
  LEFT(c.evaluation_reason, 400) AS reason,
  c.evaluation_ts AS ts
FROM TestRuns tr
JOIN TestRunDetails trd ON trd.run_id = tr.run_id
JOIN Targets tg ON tg.target_id = tr.target_id
JOIN Metrics m  ON m.metric_id  = trd.metric_id
JOIN TestCases tc ON tc.testcase_id = trd.testcase_id
JOIN Prompts p  ON p.prompt_id  = tc.prompt_id
JOIN Strategies s ON s.strategy_id = tc.strategy_id
JOIN Conversations c ON c.detail_id = trd.detail_id
WHERE tg.target_name = '{target_name}'
  AND tr.run_id >= {min_run_id}
  AND m.metric_id IN ({metric_ids_csv})
ORDER BY tr.run_id, m.metric_name, tc.testcase_name;
"""


def _max_run_id(cerai_dir: Path = CERAI_DIR) -> int:
    """Return the current max run_id in TestRuns (0 if empty)."""
    raw = query_db("SELECT COALESCE(MAX(run_id), 0) FROM TestRuns", cerai_dir=cerai_dir)
    try:
        return int(raw.strip().split("\n")[0])
    except (ValueError, IndexError):
        return 0


def _export_scores(
    target_id: str,
    target_name: str,
    min_run_id: int,
    metric_ids: list[int],
    workspace_results: Path,
    cerai_dir: Path = CERAI_DIR,
) -> Path:
    """Query the DB for THIS run's CeRAI rows and write them to a JSONL.

    Filters by `target_name = X AND run_id >= min_run_id AND metric_id IN
    (preset's enabled metrics)`.  The metric_ids filter is the second half of
    the single-source-of-truth contract — only the metrics the preset asked
    for end up in the JSONL.  If a future evaluator adds Bias_Assessment back
    to the YAML, it appears here automatically.
    """
    if not metric_ids:
        out = workspace_results / f"cerai_scores_{target_id.lower().replace('-', '_')}.jsonl"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("")
        return out
    raw_target = target_name.replace("'", "''")
    metric_ids_csv = ",".join(str(int(i)) for i in metric_ids)
    sql = SCORE_QUERY.format(
        target_name=raw_target,
        min_run_id=min_run_id,
        metric_ids_csv=metric_ids_csv,
    )
    # NOTE: do NOT use query_db() here — it sets -N (skip-column-names) which
    # would strip the header row.  We need the header so we can build dicts.
    r = exec_in(
        "db",
        ["mariadb", "-u", "aiet_user", "-paiet_password", "aievaluationtool",
         "-B", "-e", sql],
        cerai_dir=cerai_dir,
        workdir=None,
    )
    if r.returncode != 0:
        raise DockerError(f"_export_scores query failed: {r.stderr}")
    out_path = workspace_results / f"cerai_scores_{target_id.lower().replace('-', '_')}.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lines = r.stdout.strip().split("\n")
    if len(lines) < 2:
        out_path.write_text("")
        return out_path
    header = lines[0].split("\t")
    with out_path.open("w") as f:
        for line in lines[1:]:
            vals = line.split("\t")
            if len(vals) != len(header):
                continue
            row = dict(zip(header, vals))
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return out_path


def _run_names_for_target(summary: dict, target_id: str) -> list[str]:
    """Pull the list of run_names this evaluation produced for a target."""
    out = []
    for plan_name, metric_results in (summary.get(target_id) or {}).items():
        for label, val in metric_results.items():
            # `val` is either a run_name on success, or 'executor_failed: ...'
            # / 'no_run_name: ...' / 'analyzer_failed: ...' on failure.
            if val and not val.startswith(("executor_failed", "no_run_name", "analyzer_failed")):
                out.append(val)
    return out


def run_cerai_track(preset: Preset, cerai_dir: Path = CERAI_DIR,
                    workspace_results: Path | None = None) -> dict:
    """Run all enabled (plan, target) pairs.  Returns a per-target summary
    and writes results/cerai_scores_<target>.jsonl per target (this-run only)."""
    if not preset.cerai.enabled:
        return {"skipped": True, "reason": "cerai.enabled=false"}

    cfg_path = cerai_dir / "config.json"
    cfg_backup = cerai_dir / "config.json.indic-eval-backup"
    shutil.copyfile(cfg_path, cfg_backup)

    # Record the run_id baseline BEFORE we start writing new runs.  Used by
    # _export_scores to capture every CeRAI row this evaluation produces for
    # a target, even when its run_name was lost in summary.json.
    min_run_id = _max_run_id(cerai_dir) + 1

    summary: dict[str, dict] = {}
    try:
        for target in preset.targets:
            print(f"\n========= CeRAI track: {target.id} =========", flush=True)
            _patch_config_for_target(target, preset, cerai_dir)
            _restart_app_backend(cerai_dir)
            run_importer(cerai_dir)
            target_summary: dict[str, dict] = {}

            for plan_name, plan_cfg in preset.cerai.plans.items():
                if not plan_cfg.enabled:
                    print(f"  [skip] {plan_name} disabled in preset", flush=True)
                    continue
                if plan_name not in PLAN_NAME_TO_ID:
                    print(f"  [warn] unknown plan {plan_name}; skipping", flush=True)
                    continue
                if not plan_cfg.metrics:
                    print(f"  [skip] {plan_name} has no `metrics:` list", flush=True)
                    continue

                plan_id = PLAN_NAME_TO_ID[plan_name]
                max_arg = plan_cfg.limit_per_metric
                metric_results: dict[str, str] = {}

                for metric in plan_cfg.metrics:
                    metric_id, label = metric.id, metric.label
                    print(f"  -- {plan_name}/{label} (metric={metric_id}, max={max_arg})", flush=True)
                    exec_cmd = [
                        "python3", "/app/src/app/testcase_executor/main.py",
                        "--config", CONFIG_IN_CONTAINER,
                        "--testplan-id", str(plan_id),
                        "--metric-id", str(metric_id),
                        "--execute", "--verbosity", "2",
                    ]
                    if max_arg is not None:
                        exec_cmd.extend(["--max-testcases", str(max_arg)])
                    r = exec_in("app-backend", exec_cmd, cerai_dir=cerai_dir)
                    if r.returncode != 0:
                        metric_results[label] = f"executor_failed: {r.stderr[:120]}"
                        continue
                    try:
                        run_name = _latest_run_name(cerai_dir)
                    except DockerError as e:
                        metric_results[label] = f"no_run_name: {e}"
                        continue
                    a = exec_in(
                        "app-backend",
                        [
                            "python3", "/app/src/app/response_analyzer/analyze.py",
                            "--config", CONFIG_IN_CONTAINER,
                            "--run-name", run_name,
                            "--verbosity", "2",
                        ],
                        cerai_dir=cerai_dir,
                    )
                    if a.returncode != 0:
                        metric_results[label] = f"analyzer_failed: {a.stderr[:120]}"
                    else:
                        metric_results[label] = run_name
                target_summary[plan_name] = metric_results
            summary[target.id] = target_summary

            # Export per-run scores for THIS target.  We filter by
            # target_name AND run_id >= baseline AND metric_id IN preset's
            # configured metrics — three filters that together produce a
            # JSONL containing exactly what this preset asked CeRAI to do.
            if workspace_results is not None:
                target_name_in_db = target.id  # patched to config.json's application_name
                preset_metric_ids = [
                    metric.id
                    for plan_cfg in preset.cerai.plans.values()
                    if plan_cfg.enabled
                    for metric in plan_cfg.metrics
                ]
                out_path = _export_scores(
                    target.id, target_name_in_db, min_run_id,
                    preset_metric_ids, workspace_results, cerai_dir,
                )
                print(f"   exported {target.id} CeRAI scores -> {out_path.name}", flush=True)
    finally:
        shutil.copyfile(cfg_backup, cfg_path)
        cfg_backup.unlink(missing_ok=True)
        _restart_app_backend(cerai_dir)

    return summary
