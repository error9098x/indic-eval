"""
Our track — runs the 120-prompt audit suite (C1..C5).

For every enabled target:
  1. Resolve manifest path, apply per-category limits.
  2. Run inference -> results/inference_<target_id>.jsonl
Then collectively across targets:
  3. C1 Gemini-judge refusal       -> results/c1_refusal_scores.jsonl
  4. C3 Gemini-judge agri rubric   -> results/c3_judge_scores.jsonl
  5. C4 Gemini-judge stereotype    -> results/c4_bias_judge_scores.jsonl
Finally:
  6. analysis.compute_findings()   -> results/findings.json

All judges and analysis are resumable; re-running is a no-op when complete.
"""
from __future__ import annotations

import json
from pathlib import Path

from ..analysis import compute_findings, print_headline
from ..config import Preset
from ..inference import run_inference
from ..judges import judge_c1_refusal, judge_c3_agri, judge_c4_bias
from ..manifest import filter_by_limits, load_manifest


def _inference_path(workspace: Path, target_id: str) -> Path:
    return workspace / "results" / f"inference_{target_id}.jsonl"


def run_ours_track(preset: Preset, workspace: Path) -> dict:
    if not preset.ours.enabled:
        return {"skipped": True, "reason": "ours.enabled=false"}

    manifest_path = workspace / preset.ours.manifest
    if not manifest_path.exists():
        raise FileNotFoundError(f"manifest not found: {manifest_path}")
    all_prompts = load_manifest(manifest_path)
    prompts = filter_by_limits(all_prompts, preset.ours.limit_per_category)
    print(f"  Manifest: {len(prompts)}/{len(all_prompts)} prompts after per-category limits")

    target_response_paths: dict[str, Path] = {}
    for target in preset.targets:
        out_path = _inference_path(workspace, target.id)
        print(f"\n  -- inference: {target.id} -> {out_path.name}")
        written = run_inference(prompts, target, preset.sampling, out_path)
        print(f"     wrote {written} new rows")
        target_response_paths[target.id] = out_path

    # Judges — over all enabled targets
    judge = preset.judge
    results_dir = workspace / "results"
    c1_path = results_dir / "c1_refusal_scores.jsonl"
    c3_path = results_dir / "c3_judge_scores.jsonl"
    c4_path = results_dir / "c4_bias_judge_scores.jsonl"

    print(f"\n  -- C1 refusal judge")
    judge_c1_refusal(all_prompts, target_response_paths, judge, c1_path)
    print(f"\n  -- C3 agri judge")
    judge_c3_agri(all_prompts, target_response_paths, judge, c3_path)
    print(f"\n  -- C4 stereotype-resistance judge")
    judge_c4_bias(all_prompts, target_response_paths, judge, c4_path)

    # Findings
    print(f"\n  -- compute findings")
    findings = compute_findings(
        manifest_path=manifest_path,
        target_response_paths=target_response_paths,
        c1_judge_path=c1_path,
        c3_judge_path=c3_path,
        c4_judge_path=c4_path,
    )
    findings_path = results_dir / "findings.json"
    findings_path.write_text(json.dumps(findings, indent=2, ensure_ascii=False))
    print(f"     wrote {findings_path}")
    print_headline(findings)
    return {"findings_path": str(findings_path), "n_targets": len(target_response_paths)}
