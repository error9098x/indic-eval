"""
Preset loader.  A preset is a YAML file pinning everything needed to reproduce
a run: targets, sampling params, judge model, per-track prompt limits.

Schema is validated by Pydantic; unknown keys raise.  CLI flags override YAML
keys via apply_overrides() (dotted-path syntax: cerai.plans.T1_Responsible_AI.enabled=false).
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator


class Sampling(BaseModel):
    model_config = ConfigDict(extra="forbid")
    temperature: float = 0.0
    seed: int = 42
    max_tokens: int = 2048
    reasoning_effort: str | None = "low"


class ProviderRouting(BaseModel):
    model_config = ConfigDict(extra="forbid")
    only: list[str] = Field(default_factory=list)
    allow_fallbacks: bool = False


class Target(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    model: str
    base_url: str
    api_key_env: str
    provider_routing: ProviderRouting | None = None


class Judge(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str
    base_url: str
    api_key_env: str
    temperature: float = 0.0
    max_tokens: int = 1024
    # Gemini 3.x reasoning controls (passed through OpenRouter's extra_body).
    # `minimal` is the lowest setting Gemini 3 accepts; `exclude=true` strips
    # thinking tokens from the response.  None on either field omits the param.
    reasoning_effort: str | None = None
    reasoning_exclude: bool = True


class OurTrack(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = True
    manifest: str = "manifest/prompts_manifest.json"
    limit_per_category: dict[str, int | None] = Field(default_factory=dict)


class CeraiMetric(BaseModel):
    """One CeRAI metric to run inside a plan.

    `id` is CeRAI's metric_id (must exist in CeRAI's Metrics table — wrong
    IDs cause CeRAI's executor to silently fall back to defaults).
    `label` is a display name used in CLI logs and cerai/summary.json.
    """
    model_config = ConfigDict(extra="forbid")
    id: int
    label: str


class CeraiPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = True
    limit_per_metric: int | None = 33
    # Explicit list of metrics to run for this plan.  Single source of truth —
    # to add/remove a metric, edit this list in the preset YAML.  Code never
    # carries its own metric list.
    metrics: list[CeraiMetric] = Field(default_factory=list)


class CeraiTrack(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = True
    plans: dict[str, CeraiPlan] = Field(default_factory=dict)


class Preset(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    audit_date: str
    sampling: Sampling
    targets: list[Target]
    judge: Judge
    ours: OurTrack
    cerai: CeraiTrack

    @field_validator("audit_date", mode="before")
    @classmethod
    def _coerce_date_to_str(cls, v):
        # YAML parses bare YYYY-MM-DD as datetime.date; convert to ISO string.
        return v.isoformat() if hasattr(v, "isoformat") else str(v)

    def sha256(self) -> str:
        canonical = json.dumps(self.model_dump(mode="json"), sort_keys=True).encode()
        return hashlib.sha256(canonical).hexdigest()

    def target_by_id(self, target_id: str) -> Target:
        for t in self.targets:
            if t.id == target_id:
                return t
        raise KeyError(f"target '{target_id}' not in preset (have: {[t.id for t in self.targets]})")


def load_preset(path: str | Path) -> Preset:
    """Load and validate a preset YAML file."""
    raw = yaml.safe_load(Path(path).read_text())
    return Preset.model_validate(raw)


def apply_overrides(preset: Preset, overrides: list[str]) -> Preset:
    """Apply --set key.path=value overrides.  Values are parsed as YAML scalars."""
    data = preset.model_dump()
    for o in overrides:
        if "=" not in o:
            raise ValueError(f"--set expects key=value, got: {o}")
        key, val = o.split("=", 1)
        parsed = yaml.safe_load(val)   # parses "false"→False, "33"→33, etc.
        node = data
        parts = key.split(".")
        for p in parts[:-1]:
            if p not in node:
                raise KeyError(f"--set key '{key}': '{p}' not in preset")
            node = node[p]
        node[parts[-1]] = parsed
    return Preset.model_validate(data)


def apply_smoke(preset: Preset) -> Preset:
    """--smoke: collapse every limit to 1 (one prompt per category, one per CeRAI metric)."""
    data = preset.model_dump()
    for k in data["ours"]["limit_per_category"]:
        data["ours"]["limit_per_category"][k] = 1
    for plan in data["cerai"]["plans"].values():
        plan["limit_per_metric"] = 1
    return Preset.model_validate(data)


def filter_tracks(preset: Preset, tracks: list[str]) -> Preset:
    """--tracks: keep only the listed tracks; disable others."""
    data = preset.model_dump()
    data["ours"]["enabled"] = "ours" in tracks
    data["cerai"]["enabled"] = "cerai" in tracks
    return Preset.model_validate(data)


def filter_targets(preset: Preset, target_ids: list[str]) -> Preset:
    """--targets: keep only the listed targets."""
    data = preset.model_dump()
    keep = [t for t in data["targets"] if t["id"] in target_ids]
    if not keep:
        raise ValueError(f"--targets filtered to nothing.  Asked: {target_ids}.  "
                         f"Available: {[t['id'] for t in data['targets']]}")
    data["targets"] = keep
    return Preset.model_validate(data)


def resolve_api_key(env_var: str) -> str:
    """Look up an API key from the env; clear error if missing."""
    val = os.environ.get(env_var)
    if not val:
        raise RuntimeError(f"environment variable {env_var} is not set")
    return val
