"""
Run a list of prompts against a target via the OpenAI-compatible API.

Replaces the original scripts/run_eval.py and scripts/run_baseline_gemma.py
with a single target-agnostic function.  Supports resume (re-running the same
output path picks up where it left off).
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from openai import OpenAI

from .config import Sampling, Target, resolve_api_key


REFERRER = "https://github.com/error9098x/gates-fellowship-eval"
X_TITLE = "indic-eval"


def _client_for(target: Target) -> OpenAI:
    # max_retries=4 (default is 2); covers transient 429s / 5xx / connection drops
    # with the SDK's built-in exponential backoff.  After 4 retries fail we
    # write an `error` row and the prompt is retried on the next CLI invocation.
    return OpenAI(
        base_url=target.base_url,
        api_key=resolve_api_key(target.api_key_env),
        max_retries=4,
    )


def _extra_body(target: Target, sampling: Sampling) -> dict[str, Any]:
    extra: dict[str, Any] = {}
    # Sarvam-style reasoning effort
    if sampling.reasoning_effort and "sarvam" in target.base_url:
        extra["reasoning_effort"] = sampling.reasoning_effort
    # OpenRouter-style provider pin — slug from `tag` field on /models/<id>/endpoints
    if target.provider_routing is not None and "openrouter" in target.base_url:
        extra["provider"] = {
            "only": list(target.provider_routing.only),
            "allow_fallbacks": target.provider_routing.allow_fallbacks,
        }
    return extra


def _extra_headers(target: Target) -> dict[str, str]:
    if "openrouter" in target.base_url:
        return {"HTTP-Referer": REFERRER, "X-Title": X_TITLE}
    return {}


def _completed_ids(output_path: Path) -> set[str]:
    """Read existing output to support resume."""
    done: set[str] = set()
    if not output_path.exists():
        return done
    for line in output_path.read_text().splitlines():
        if line.strip():
            try:
                row = json.loads(line)
                if "id" in row and "error" not in row:
                    done.add(row["id"])
            except json.JSONDecodeError:
                continue
    return done


def run_inference(
    prompts: list[dict[str, Any]],
    target: Target,
    sampling: Sampling,
    output_path: Path,
    log_progress: bool = True,
) -> int:
    """Run target inference over a prompt list.  Appends to output_path; resumable.

    Returns count of rows newly written.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    done_ids = _completed_ids(output_path)
    if done_ids and log_progress:
        print(f"  [{target.id}] resuming — {len(done_ids)} prompts already complete")

    client = _client_for(target)
    extra_body = _extra_body(target, sampling)
    extra_headers = _extra_headers(target)

    start = time.time()
    written = 0
    pending = [p for p in prompts if p["id"] not in done_ids]
    total = len(pending) + len(done_ids)
    with output_path.open("a") as f:
        for i, p in enumerate(pending, 1):
            t0 = time.time()
            try:
                resp = client.chat.completions.create(
                    model=target.model,
                    messages=[{"role": "user", "content": p["prompt_text"]}],
                    temperature=sampling.temperature,
                    max_tokens=sampling.max_tokens,
                    seed=sampling.seed,
                    extra_body=extra_body or None,
                    extra_headers=extra_headers or None,
                )
                msg = resp.choices[0].message
                content = (
                    msg.content
                    or getattr(msg, "reasoning_content", None)
                    or ""
                ).strip()
                usage = resp.usage.model_dump() if resp.usage else {}
                row = {
                    "id": p["id"],
                    "category": p["category"],
                    "language": p["language"],
                    "prompt": p["prompt_text"],
                    "response": content,
                    "ground_truth": p.get("ground_truth", ""),
                    "expected_behavior": p.get("expected_behavior", ""),
                    "stereotype_letter": p.get("stereotype_letter", ""),
                    "attack_pattern": p.get("attack_pattern", ""),
                    "pii_type": p.get("pii_type", ""),
                    "elapsed_s": round(time.time() - t0, 2),
                    "usage": usage,
                    "finish_reason": resp.choices[0].finish_reason,
                }
            except Exception as e:
                row = {
                    "id": p["id"],
                    "category": p["category"],
                    "language": p["language"],
                    "error": f"{type(e).__name__}: {e}",
                    "elapsed_s": round(time.time() - t0, 2),
                }
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            written += 1

            if log_progress:
                position = len(done_ids) + i
                elapsed = time.time() - start
                eta_min = (elapsed / i) * (len(pending) - i) / 60 if i > 0 else 0
                status = "x" if "error" in row else "."
                print(
                    f"  [{target.id}] [{position:>3d}/{total}] {status} "
                    f"{p['id']:<28s} {row.get('elapsed_s', 0):>5.1f}s  "
                    f"ETA {eta_min:.1f}m",
                    flush=True,
                )
    return written
