"""Manifest loader with per-category subsampling."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


CATEGORY_KEY_MAP = {
    "C1_cross_lingual_safety": "cross_lingual_safety",
    "C2_maternal_health": "maternal_health",
    "C3_agricultural_advisory": "agricultural_advisory",
    "C4_demographic_bias": "demographic_bias",
    "C5_indian_pii": "indian_pii",
}


def load_manifest(path: Path) -> list[dict[str, Any]]:
    return json.loads(path.read_text())["prompts"]


def manifest_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def filter_by_limits(
    prompts: list[dict[str, Any]],
    limit_per_category: dict[str, int | None],
) -> list[dict[str, Any]]:
    """Return a list keeping at most limit_per_category[cat] prompts per category.

    Keys in limit_per_category use the C1_..C5_ form; manifest categories use
    the long form (cross_lingual_safety etc).  None = no limit.
    """
    by_cat: dict[str, list[dict[str, Any]]] = {}
    for p in prompts:
        by_cat.setdefault(p["category"], []).append(p)

    out: list[dict[str, Any]] = []
    for c_key, lim in limit_per_category.items():
        long_key = CATEGORY_KEY_MAP.get(c_key, c_key)
        bucket = by_cat.get(long_key, [])
        if lim is None:
            out.extend(bucket)
        else:
            out.extend(bucket[:lim])
    # Preserve any categories not mentioned in the limits dict
    mentioned_long = {CATEGORY_KEY_MAP.get(k, k) for k in limit_per_category}
    for c_long, bucket in by_cat.items():
        if c_long not in mentioned_long:
            out.extend(bucket)
    return out
