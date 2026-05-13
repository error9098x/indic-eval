"""
Auto-generated test-suite report — renders findings.json + CeRAI score JSONLs
into a single self-contained HTML file.

Design principles (locked):
  - All content is mechanical/data-driven.  No human-written paragraphs,
    no comparative claims ("X beats Y"), no recommendations.
  - Each metric has a score-range legend documenting what each value MEANS
    per its rubric (rubric documentation, not editorial interpretation).
  - Provenance (manifest sha256, preset sha256, indic-eval git sha, judge
    model, sampling params, audit date) auto-filled from run-metadata.json.
  - No external CSS/JS/fonts; inline everything.

Inputs (auto-discovered from workspace/results/):
  - findings.json                          Track 1
  - cerai_scores_<target>.jsonl (per target)  Track 2 raw rows
  - run-metadata.json                      provenance

Output: site/index.html (single file).
"""
from __future__ import annotations

import html
import json
import re
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any


# ---------------------------------------------------------------------------
# One legend table.  Each row: (track, metric label, range, reading direction).
# Documents what each numeric value means per the scorer's design.  Not
# editorial — describes the rubric, not the result.
# ---------------------------------------------------------------------------
LEGEND_ROWS: list[tuple[str, str, str, str]] = [
    # Track 1 — Custom audit
    ("Track 1", "C1 Cross-lingual safety",            "0.0 – 1.0",  "Higher means safer refusal of harmful prompts"),
    ("Track 1", "C2 Maternal health MCQ",             "0.0 – 1.0",  "Higher means more correct MCQ answers (0.25 = random)"),
    ("Track 1", "C3 Agricultural advisory",           "0.0 – 1.0",  "Higher means more agronomically correct response"),
    ("Track 1", "C4 Stereotype-pick rate (primary)",  "0.0 – 1.0",  "Lower means less stereotype-aligned (0.5 = random)"),
    ("Track 1", "C4 Resistance score (judge)",        "0.0 – 1.0",  "Higher means stronger resistance to stereotype framing"),
    ("Track 1", "C5 PII leak rate",                   "0.0 – 1.0",  "Lower means less PII leaked"),
    # Track 2 — CeRAI default plans
    ("Track 2", "Inclusivity",                        "0.0 – 1.0",  "Higher means more inclusive response (judge)"),
    ("Track 2", "Explainability",                     "0 or 1",     "1 means the response explained its reasoning"),
    ("Track 2", "Cultural_Sensitivity",               "0.0 – 1.0",  "Higher means more culturally sensitive (judge)"),
    ("Track 2", "Truthfulness",                       "0 or 1",     "1 means factually correct vs reference"),
    ("Track 2", "Response_out_of_scope",              "0 or 1",     "1 means the response stayed in scope"),
    ("Track 2", "Language_Coverage",                  "0 or 1",     "1 means the target responded in the expected language"),
    ("Track 2", "Multi_Indic_in_one_context",         "0 or 1",     "1 means multiple Indic languages handled in one context"),
    ("Track 2", "Accuracy_per_Language",              "0 or 1",     "1 means correct in the target language"),
]


# ---------------------------------------------------------------------------
# CSS (inline, lifted in spirit from variant v2; cream-paper aesthetic)
# ---------------------------------------------------------------------------
CSS = """
*, *::before, *::after { box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%; }
body {
  margin: 0;
  font-family: ui-serif, Georgia, "Times New Roman", Times, serif;
  font-size: 15px;
  line-height: 1.55;
  color: #1a1a1a;
  background: #f5f3ee;
  text-rendering: optimizeLegibility;
  -webkit-font-smoothing: antialiased;
}
.num, code, kbd, samp, pre, .mono {
  font-family: ui-monospace, "SF Mono", Menlo, Consolas, "Liberation Mono", monospace;
  font-feature-settings: "tnum" 1, "lnum" 1;
  font-variant-numeric: tabular-nums lining-nums;
}
.page {
  max-width: 1180px;
  margin: 0 auto;
  padding: 0 32px 64px;
  background: #fbfaf6;
  border-left: 1px solid #d8d3c4;
  border-right: 1px solid #d8d3c4;
  min-height: 100vh;
}
header.masthead {
  padding: 36px 0 24px;
  border-bottom: 2px solid #1a1a1a;
  margin-bottom: 0;
}
header.masthead .kicker {
  text-transform: uppercase;
  letter-spacing: 0.18em;
  font-size: 10.5px;
  color: #6b6356;
  font-family: ui-sans-serif, system-ui, -apple-system, sans-serif;
  margin-bottom: 10px;
}
header.masthead h1 {
  font-size: 26px;
  line-height: 1.2;
  margin: 0 0 4px;
  font-weight: 600;
  letter-spacing: -0.01em;
}
header.masthead .sub {
  font-size: 12.5px;
  color: #4a4438;
  margin-top: 8px;
  line-height: 1.7;
}
header.masthead .sub code {
  font-family: ui-monospace, "SF Mono", Menlo, monospace;
  background: #f0eee5;
  padding: 1px 5px;
  border-radius: 2px;
}
header.masthead .meta-row {
  display: flex;
  flex-wrap: wrap;
  gap: 18px 26px;
  margin-top: 16px;
  font-size: 12px;
  font-family: ui-sans-serif, system-ui, -apple-system, sans-serif;
  color: #4a4438;
}
header.masthead .meta-row .k {
  text-transform: uppercase;
  font-size: 9.5px;
  letter-spacing: 0.12em;
  color: #8a8170;
  margin-right: 5px;
}
header.masthead .meta-row .v { color: #1a1a1a; font-family: ui-monospace, "SF Mono", Menlo, monospace; }
.layout {
  display: grid;
  grid-template-columns: 200px 1fr;
  gap: 36px;
  margin-top: 24px;
}
nav.toc {
  position: sticky;
  top: 16px;
  align-self: start;
  font-family: ui-sans-serif, system-ui, -apple-system, sans-serif;
  font-size: 12px;
  padding-right: 8px;
}
nav.toc .label {
  text-transform: uppercase;
  letter-spacing: 0.12em;
  font-size: 9.5px;
  color: #8a8170;
  margin-bottom: 10px;
}
nav.toc ol { list-style: none; padding: 0; margin: 0 0 12px; }
nav.toc li { padding: 4px 0; }
nav.toc a { color: #4a4438; text-decoration: none; }
nav.toc a:hover { color: #1a1a1a; text-decoration: underline; }
nav.toc .seqno { color: #b3a987; margin-right: 6px; }
nav.toc .group {
  text-transform: uppercase;
  letter-spacing: 0.10em;
  font-size: 10px;
  color: #8a8170;
  margin: 12px 0 4px;
  padding-top: 8px;
  border-top: 1px solid #e9e4d4;
}
main { min-width: 0; }
section { padding: 28px 0 12px; border-bottom: 1px solid #e9e4d4; }
section:last-child { border-bottom: none; }
h2 { font-size: 19px; font-weight: 600; margin: 0 0 16px; letter-spacing: -0.005em; }
h2 .seqno { color: #b3a987; margin-right: 10px; font-weight: 400; }
h3 { font-size: 14px; font-weight: 600; margin: 18px 0 8px; text-transform: uppercase; letter-spacing: 0.04em; color: #4a4438; font-family: ui-sans-serif, system-ui, sans-serif; }
p { margin: 0 0 10px; }
.tight { margin: 0; }
.muted { color: #6b6356; font-size: 12.5px; }
.note {
  background: #f5f3ea;
  border-left: 3px solid #b3a987;
  padding: 10px 14px;
  margin: 14px 0;
  font-size: 13px;
  color: #3a3528;
}
.warn {
  background: #fff5e0;
  border-left: 3px solid #c98a1a;
  padding: 10px 14px;
  margin: 14px 0;
  font-size: 13px;
  color: #5b3f0d;
}

/* tables */
table.audit {
  width: 100%;
  border-collapse: collapse;
  margin: 8px 0 14px;
  font-size: 13px;
}
table.audit th, table.audit td {
  text-align: left;
  padding: 6px 10px;
  border-bottom: 1px solid #e5e0d0;
  vertical-align: middle;
}
table.audit th {
  font-family: ui-sans-serif, system-ui, sans-serif;
  font-weight: 600;
  text-transform: uppercase;
  font-size: 10.5px;
  letter-spacing: 0.06em;
  color: #6b6356;
  border-bottom: 2px solid #1a1a1a;
  background: #f5f3ea;
}
table.audit td.n, table.audit th.n { text-align: right; font-family: ui-monospace, "SF Mono", Menlo, monospace; font-feature-settings: "tnum" 1, "lnum" 1; }
table.audit caption { caption-side: bottom; font-size: 11.5px; color: #8a8170; padding-top: 6px; text-align: left; }

/* legend / range tables (legacy — kept for backward compat) */
table.legend {
  width: 100%;
  border-collapse: collapse;
  margin: 6px 0 14px;
  font-size: 12.5px;
}
table.legend td {
  padding: 3px 8px;
  vertical-align: top;
}
table.legend td.val {
  font-family: ui-monospace, "SF Mono", Menlo, monospace;
  width: 60px;
  color: #4a4438;
}

/* Prose-style legend — small muted text with bold key terms inline.
   Matches the audit-deliverable style of variant 2: looks like a footnote,
   not another data table. */
ul.legend-prose {
  list-style: none;
  margin: 4px 0 18px;
  padding: 0;
  font-size: 12.5px;
  line-height: 1.65;
  color: #4a4438;
  font-family: ui-sans-serif, system-ui, -apple-system, sans-serif;
}
ul.legend-prose li {
  padding: 1px 0;
}
ul.legend-prose .term {
  font-family: ui-monospace, "SF Mono", Menlo, monospace;
  color: #1a1a1a;
  font-weight: 600;
}
ul.legend-prose .lkicker {
  text-transform: uppercase;
  letter-spacing: 0.12em;
  font-size: 9.5px;
  color: #8a8170;
  font-weight: 500;
  display: block;
  margin-bottom: 2px;
}
p.legend-inline {
  margin: 4px 0 18px;
  font-size: 12.5px;
  color: #4a4438;
  font-family: ui-sans-serif, system-ui, -apple-system, sans-serif;
}
p.legend-inline .lkicker {
  text-transform: uppercase;
  letter-spacing: 0.12em;
  font-size: 9.5px;
  color: #8a8170;
  font-weight: 500;
  margin-right: 10px;
}
p.legend-inline code {
  font-family: ui-monospace, "SF Mono", Menlo, monospace;
  color: #1a1a1a;
}

/* inline bar */
.bar {
  display: inline-block;
  width: 90px;
  height: 6px;
  background: #e5e0d0;
  border-radius: 1px;
  vertical-align: middle;
  margin-left: 8px;
  position: relative;
  overflow: hidden;
}
.bar > span {
  display: block;
  height: 100%;
  background: #4a4438;
}
.bar.danger > span { background: #a13a3a; }

/* charts (one SVG per metric section) */
.chart { margin: 4px 0 18px; }
.chart h4 {
  margin: 0 0 8px;
  font-size: 13px;
  font-weight: 600;
  font-family: ui-sans-serif, system-ui, sans-serif;
  color: #1a1a1a;
  letter-spacing: -0.005em;
}
.chart svg {
  display: block;
  width: 100%;
  height: auto;
  border: 1px solid #e9e4d4;
  border-radius: 4px;
}
.chart-note {
  margin: 8px 0 6px;
  font-size: 12px;
  color: #6b6356;
  font-family: ui-sans-serif, system-ui, sans-serif;
}

/* footer */
footer { margin-top: 28px; padding-top: 18px; border-top: 1px solid #d8d3c4; font-size: 11.5px; color: #6b6356; font-family: ui-sans-serif, system-ui, sans-serif; }
footer dl { display: grid; grid-template-columns: 160px 1fr; gap: 4px 14px; margin: 0; }
footer dt { color: #8a8170; text-transform: uppercase; letter-spacing: 0.06em; font-size: 10px; }
footer dd { margin: 0; font-family: ui-monospace, "SF Mono", Menlo, monospace; color: #1a1a1a; overflow-wrap: anywhere; }
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _e(s: Any) -> str:
    if s is None:
        return "—"
    return html.escape(str(s))


def _fmt_num(v: Any, places: int = 3) -> str:
    if v is None:
        return "—"
    if isinstance(v, (int, float)):
        if isinstance(v, float):
            return f"{v:.{places}f}"
        return str(v)
    return _e(v)


def _bar(
    value: float | None,
    danger: bool = False,
    color: str | None = None,
    max_value: float = 1.0,
) -> str:
    """Inline mini-bar next to a score cell.

    `color` (when given and not in danger state) overrides the default fill so
    table bars match the chart palette per-target.
    """
    if value is None:
        return ""
    pct = max(0.0, min(1.0, value / max_value)) * 100
    cls = "bar danger" if danger else "bar"
    fill = ""
    if color and not danger:
        fill = f";background:{color}"
    return f'<span class="{cls}"><span style="width:{pct:.1f}%{fill}"></span></span>'


# ---------------------------------------------------------------------------
# Chart palette + grouped-bar SVG helper.
# Reference-image style: warm orange + deep blue, percent y-axis, per-bar
# score labels, rounded corners, pill legend top-right.
# Inline SVG; zero external assets so the report stays a single self-contained
# HTML file (same constraint as the rest of the report).
# ---------------------------------------------------------------------------
PALETTE: list[str] = [
    "#1F4D9B",  # deep blue
    "#D86E3D",  # warm terracotta orange
    "#4A4438",  # dark brown (fallback)
    "#7A4D8B",  # purple (fallback)
]


def _color_for_target(target_id: str, all_targets: list[str]) -> str:
    return PALETTE[sorted(all_targets).index(target_id) % len(PALETTE)]


def _build_palette(target_ids: list[str]) -> dict[str, str]:
    return {t: _color_for_target(t, target_ids) for t in target_ids}


def _fmt_pct(v: float) -> str:
    pct = v * 100
    if abs(pct - round(pct)) < 0.05:
        return f"{round(pct):d}"
    return f"{pct:.1f}"


def _svg_grouped_bar(
    title: str,
    categories: list[str],
    series: dict[str, list[float | None]],
    palette: dict[str, str],
    *,
    y_max: float = 1.0,
    width: int = 900,
    height: int = 360,
    note: str | None = None,
    y_label: str = "Score (%)",
) -> str:
    max_label_len = max((len(c) for c in categories), default=0)
    rotated = max_label_len > 12
    pad_l, pad_r = 84, 28
    pad_t = 72
    pad_b = 96 if rotated else 60
    if rotated:
        height = max(height, 380)
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b
    n_cats = max(len(categories), 1)
    n_series = max(len(series), 1)
    group_w = plot_w / n_cats
    inner_pad = 0.30
    bar_total_w = group_w * (1 - inner_pad)
    bar_w = bar_total_w / n_series
    bar_gap = (group_w - bar_total_w) / 2
    bar_rx = 4

    svg: list[str] = [
        f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" '
        f'font-family="ui-sans-serif,system-ui,sans-serif" font-size="11.5" '
        f'role="img" aria-label="{html.escape(title)}">'
    ]
    svg.append(f'<rect width="{width}" height="{height}" fill="#fbfaf6"/>')

    # Y-axis label (rotated, bold)
    yl_x = 24
    yl_y = pad_t + plot_h / 2
    svg.append(
        f'<text x="{yl_x}" y="{yl_y}" text-anchor="middle" fill="#1a1a1a" '
        f'font-size="13" font-weight="700" '
        f'transform="rotate(-90 {yl_x} {yl_y})">{html.escape(y_label)}</text>'
    )

    # Gridlines + percent ticks
    for tv in (0, 0.25, 0.5, 0.75, 1.0):
        y = pad_t + plot_h * (1 - tv / y_max)
        svg.append(
            f'<line x1="{pad_l}" y1="{y:.1f}" x2="{width - pad_r}" y2="{y:.1f}" '
            f'stroke="#e8e3d2" stroke-width="0.6"/>'
        )
        svg.append(
            f'<text x="{pad_l - 10}" y="{y + 3.5:.1f}" text-anchor="end" '
            f'fill="#8a8170" font-size="11">{int(tv * 100)}</text>'
        )

    svg.append(
        f'<line x1="{pad_l}" y1="{pad_t}" x2="{pad_l}" y2="{pad_t + plot_h}" '
        f'stroke="#bbb3a0" stroke-width="1"/>'
    )
    svg.append(
        f'<line x1="{pad_l}" y1="{pad_t + plot_h}" x2="{width - pad_r}" '
        f'y2="{pad_t + plot_h}" stroke="#1a1a1a" stroke-width="1.1"/>'
    )

    series_items = list(series.items())
    for c_idx, cat in enumerate(categories):
        group_x = pad_l + c_idx * group_w + bar_gap
        for s_idx, (target_id, scores) in enumerate(series_items):
            score = scores[c_idx] if c_idx < len(scores) else None
            if score is None:
                continue
            x = group_x + s_idx * bar_w
            h = plot_h * (score / y_max)
            y = pad_t + plot_h - h
            color = palette.get(target_id, "#888")
            svg.append(
                f'<rect x="{x:.2f}" y="{y:.2f}" width="{bar_w * 0.86:.2f}" '
                f'height="{max(h, 0):.2f}" fill="{color}" rx="{bar_rx}" ry="{bar_rx}">'
                f'<title>{html.escape(target_id)} · {cat}: {_fmt_pct(score)}%</title>'
                f'</rect>'
            )
            label_cx = x + (bar_w * 0.86) / 2
            label_y = max(y - 7, pad_t - 4)
            svg.append(
                f'<text x="{label_cx:.2f}" y="{label_y:.2f}" text-anchor="middle" '
                f'fill="#1a1a1a" font-size="11.5" font-weight="600">'
                f'{_fmt_pct(score)}</text>'
            )

        label_x = pad_l + c_idx * group_w + group_w / 2
        label_y = pad_t + plot_h + 20
        if rotated:
            rotate = f' transform="rotate(-26 {label_x:.1f} {label_y:.1f})"'
            anchor = "end"
            text_x = label_x + 4
        else:
            rotate = ""
            anchor = "middle"
            text_x = label_x
        svg.append(
            f'<text x="{text_x:.1f}" y="{label_y:.1f}" '
            f'text-anchor="{anchor}" fill="#4a4438" font-size="12"{rotate}>'
            f'{html.escape(cat)}</text>'
        )

    # Pill legend, top-right corner
    leg_padding_x = 12
    leg_padding_y = 7
    swatch_size = 11
    swatch_gap = 6
    item_gap = 18
    avg_char_w = 6.6
    leg_items = []
    cursor = leg_padding_x
    for target_id, _ in series_items:
        text_w = len(target_id) * avg_char_w
        leg_items.append({
            "color": palette.get(target_id, "#888"),
            "label": target_id,
            "x_swatch": cursor,
            "x_text": cursor + swatch_size + swatch_gap,
        })
        cursor += swatch_size + swatch_gap + text_w + item_gap
    leg_w = cursor - item_gap + leg_padding_x
    leg_h = swatch_size + 2 * leg_padding_y + 4
    leg_x = width - pad_r - leg_w
    leg_y = 14
    svg.append(
        f'<rect x="{leg_x + 1.2}" y="{leg_y + 1.6}" width="{leg_w}" height="{leg_h}" '
        f'rx="{leg_h / 2:.1f}" ry="{leg_h / 2:.1f}" fill="#000" opacity="0.05"/>'
    )
    svg.append(
        f'<rect x="{leg_x}" y="{leg_y}" width="{leg_w}" height="{leg_h}" '
        f'rx="{leg_h / 2:.1f}" ry="{leg_h / 2:.1f}" '
        f'fill="#ffffff" stroke="#e2dcc8" stroke-width="1"/>'
    )
    for it in leg_items:
        ix = leg_x + it["x_swatch"]
        sy = leg_y + (leg_h - swatch_size) / 2
        tx = leg_x + it["x_text"]
        ty = leg_y + leg_h / 2 + 4
        svg.append(
            f'<rect x="{ix:.1f}" y="{sy:.1f}" width="{swatch_size}" '
            f'height="{swatch_size}" rx="2.5" ry="2.5" fill="{it["color"]}"/>'
        )
        svg.append(
            f'<text x="{tx:.1f}" y="{ty:.1f}" fill="#1a1a1a" font-size="11.5">'
            f'{html.escape(it["label"])}</text>'
        )

    svg.append("</svg>")
    inner = f'<h4>{html.escape(title)}</h4>' + "".join(svg)
    if note:
        inner += f'<p class="chart-note">{html.escape(note)}</p>'
    return f'<div class="chart">{inner}</div>'


def _ci_str(ci: list[float] | None) -> str:
    if not ci or len(ci) != 2:
        return "—"
    return f"[{ci[0]:.3f}, {ci[1]:.3f}]"


def _load_cerai_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _classify_scores(scores: list[float]) -> str:
    """Detect how a metric's scores should be rendered.

    binary      : every value is 0.0 or 1.0  -> "X/N pass"
    continuous  : numeric multi-valued        -> "mean"
    """
    if not scores:
        return "empty"
    if set(scores) <= {0.0, 1.0}:
        return "binary"
    return "continuous"


def _aggregate_cerai(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Aggregate by metric_name -> {n, type, mean, passed, scores}.

    The JSONL is written by tracks/cerai.py filtered to this run's run_names
    AND to the preset's enabled metric_ids, so we just render whatever's here.
    """
    out: dict[str, dict[str, Any]] = defaultdict(lambda: {"n": 0, "scores": []})
    for r in rows:
        metric = r.get("metric_name")
        if not metric:
            continue
        try:
            score = float(r["score"])
        except (TypeError, ValueError, KeyError):
            continue
        out[metric]["n"] += 1
        out[metric]["scores"].append(score)
    final: dict[str, dict[str, Any]] = {}
    for metric, agg in out.items():
        scores = agg["scores"]
        ctype = _classify_scores(scores)
        entry: dict[str, Any] = {
            "n": agg["n"],
            "type": ctype,
            "mean": round(mean(scores), 3) if scores else None,
            "min": round(min(scores), 3) if scores else None,
            "max": round(max(scores), 3) if scores else None,
        }
        if ctype == "binary":
            entry["passed"] = int(sum(1 for v in scores if v == 1.0))
        final[metric] = entry
    return final


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------
def _section_how_to_read() -> str:
    parts = ["<section id='sec-howto'>",
             "<h2><span class='seqno'>01</span>How to read this report</h2>",
             "<p>This is a machine-generated test-suite report.  Every cell "
             "traces back to a row in <code>results/findings.json</code> or "
             "<code>results/cerai_scores_&lt;target&gt;.jsonl</code>; the report "
             "renders the numbers and does not interpret them.</p>",
             "<p class='muted'>The table below documents each metric's score "
             "range and the direction of higher/lower values.</p>",
             "<table class='audit'>",
             "<thead><tr><th>Track</th><th>Metric</th><th>Range</th>"
             "<th>Reading</th></tr></thead><tbody>"]
    for track, metric, rng, reading in LEGEND_ROWS:
        parts.append(f"<tr><td class='muted'>{_e(track)}</td>"
                     f"<td>{_e(metric)}</td>"
                     f"<td class='n'>{_e(rng)}</td>"
                     f"<td>{_e(reading)}</td></tr>")
    parts.append("</tbody></table></section>")
    return "".join(parts)


LANGUAGE_NAMES: dict[str, str] = {
    "bn": "Bengali",
    "en": "English",
    "hi": "Hindi",
    "ta": "Tamil",
}


def _language_legend(langs: list[str]) -> str:
    """Inline footnote-style legend that expands language codes."""
    items = " · ".join(
        f"<code>{_e(code)}</code> {_e(LANGUAGE_NAMES.get(code, code))}"
        for code in sorted(langs)
    )
    return (f"<p class='legend-inline'>"
            f"<span class='lkicker'>Language codes</span>{items}</p>")


def _legend_note(kicker: str, items: list[tuple[str, str]]) -> str:
    """Prose-style legend: small muted bullets with bold term + explanation.
    Used under data tables to explain column meanings or term definitions."""
    lis = "".join(
        f"<li><span class='term'>{_e(t)}</span> — {_e(d)}</li>"
        for t, d in items
    )
    return (f"<ul class='legend-prose'>"
            f"<li><span class='lkicker'>{_e(kicker)}</span></li>"
            f"{lis}</ul>")


def _section_methodology(metadata: dict[str, Any] | None) -> str:
    parts = ["<section id='sec-method'>",
             "<h2><span class='seqno'>02</span>Configuration</h2>"]
    if not metadata:
        parts.append("<p class='muted'>run-metadata.json not available; methodology fields blank.</p>")
        parts.append("</section>")
        return "".join(parts)
    preset = metadata.get("preset_content", {})
    sampling = preset.get("sampling", {})
    judge = preset.get("judge", {})
    targets = preset.get("targets", [])
    parts.append("<h3>Targets tested</h3>")
    parts.append("<table class='audit'>")
    parts.append("<thead><tr><th>ID</th><th>Model</th><th>Base URL</th><th>Provider routing</th></tr></thead><tbody>")
    for t in targets:
        pr = t.get("provider_routing")
        pr_str = ", ".join(pr.get("only", [])) if pr else "—"
        parts.append(f"<tr><td><code>{_e(t.get('id'))}</code></td>"
                     f"<td><code>{_e(t.get('model'))}</code></td>"
                     f"<td><code>{_e(t.get('base_url'))}</code></td>"
                     f"<td>{_e(pr_str)}</td></tr>")
    parts.append("</tbody></table>")
    parts.append("<h3>Judge model</h3>")
    parts.append("<table class='audit'>")
    parts.append("<thead><tr><th>Model</th><th>Base URL</th><th>Temperature</th><th>Reasoning</th></tr></thead><tbody>")
    re_eff = judge.get("reasoning_effort") or "(off)"
    parts.append(f"<tr><td><code>{_e(judge.get('model'))}</code></td>"
                 f"<td><code>{_e(judge.get('base_url'))}</code></td>"
                 f"<td class='n'>{_fmt_num(judge.get('temperature'))}</td>"
                 f"<td><code>{_e(re_eff)}</code></td></tr>")
    parts.append("</tbody></table>")
    parts.append("<h3>Sampling (every target call)</h3>")
    parts.append("<table class='audit'>")
    parts.append("<thead><tr><th>Temperature</th><th>Seed</th><th>Max tokens</th><th>Reasoning effort</th></tr></thead><tbody>")
    parts.append(f"<tr><td class='n'>{_fmt_num(sampling.get('temperature'))}</td>"
                 f"<td class='n'>{_fmt_num(sampling.get('seed'))}</td>"
                 f"<td class='n'>{_fmt_num(sampling.get('max_tokens'))}</td>"
                 f"<td><code>{_e(sampling.get('reasoning_effort') or '(off)')}</code></td></tr>")
    parts.append("</tbody></table>")
    parts.append("</section>")
    return "".join(parts)


def _section_headline(findings: dict[str, Any], cerai: dict[str, dict], palette: dict[str, str]) -> str:
    parts = ["<section id='sec-headline'>",
             "<h2><span class='seqno'>03</span>Summary</h2>",
             "<p class='muted'>Aggregate metrics per target, both tracks.  See sections 04–08 (per-category breakdown), 09 (Track 2 detail), and 10 (run health) for the underlying numbers.</p>"]
    parts.append("<table class='audit'>")
    parts.append("<thead><tr><th>Metric</th><th>Track</th>")
    for target_id in findings.get("by_target", {}):
        parts.append(f"<th class='n'>{_e(target_id)}</th>")
    parts.append("</tr></thead><tbody>")

    def row(label: str, track: str, vals: dict[str, str | float | None], danger_when_high: bool = False):
        parts.append(f"<tr><td>{_e(label)}</td><td class='muted'>{_e(track)}</td>")
        for target_id, v in vals.items():
            if v is None:
                parts.append("<td class='n'>—</td>")
                continue
            if isinstance(v, (int, float)):
                bar = _bar(
                    float(v),
                    danger=danger_when_high and float(v) >= 0.5,
                    color=palette.get(target_id),
                )
                parts.append(f"<td class='n'>{_fmt_num(v)} {bar}</td>")
            else:
                parts.append(f"<td class='n'>{_e(v)}</td>")
        parts.append("</tr>")

    # C1 overall mean — collect languages actually present in the data
    targets = list(findings["by_target"].keys())
    c1_langs: set[str] = set()
    c1_vals = {}
    for t in targets:
        by_lang = findings["by_target"][t].get("C1_cross_lingual_safety", {}).get("by_language", {})
        c1_langs.update(by_lang.keys())
        scores = [c["mean"] for c in by_lang.values() if c.get("mean") is not None]
        c1_vals[t] = round(mean(scores), 3) if scores else None
    row(f"C1 Refusal mean ({' / '.join(sorted(c1_langs))})", "1", c1_vals)

    # C2 overall accuracy
    c2_langs: set[str] = set()
    c2_vals = {}
    for t in targets:
        by_lang = findings["by_target"][t].get("C2_maternal_health", {}).get("by_language", {})
        c2_langs.update(by_lang.keys())
        correct = sum(c.get("correct", 0) for c in by_lang.values())
        n = sum(c.get("n", 0) for c in by_lang.values())
        c2_vals[t] = round(correct / n, 3) if n else None
    row(f"C2 MCQ accuracy ({' / '.join(sorted(c2_langs))})", "1", c2_vals)

    # C3 judge mean
    c3_vals = {t: findings["by_target"][t].get("C3_agricultural_advisory", {}).get("mean") for t in targets}
    row("C3 Agri judge mean", "1", c3_vals)

    # C4 stereotype pick rate
    c4_pick = {t: findings["by_target"][t].get("C4_demographic_bias", {}).get("stereotype_pick_rate") for t in targets}
    row("C4 Stereotype-pick rate", "1", c4_pick)

    # C4 resistance mean
    c4_res = {t: findings["by_target"][t].get("C4_demographic_bias", {}).get("cross_val_mean") for t in targets}
    row("C4 Resistance mean (judge)", "1", c4_res)

    # C5 leak rate (lower is better — no danger color, see section 8 legend)
    c5_vals = {t: findings["by_target"][t].get("C5_indian_pii", {}).get("leak_rate") for t in targets}
    row("C5 PII leak rate", "1", c5_vals)

    # Track 2 per-metric — normalize across types to a single 0-1 value:
    #   binary       -> pass rate (passed/n)
    #   continuous   -> mean
    #   probability  -> 1 - (flagged/n)  i.e. "share NOT flagged at threshold 0.5"
    cerai_metrics = sorted({m for tgt in cerai.values() for m in tgt})
    for m in cerai_metrics:
        vals: dict[str, float | None] = {}
        for t in targets:
            d = cerai.get(t, {}).get(m, {})
            n = d.get("n", 0) or 0
            ctype = d.get("type")
            if ctype == "binary" and n:
                vals[t] = round(d.get("passed", 0) / n, 3)
            elif ctype == "probability" and n:
                vals[t] = round(1 - d.get("flagged", 0) / n, 3)
            elif ctype == "continuous":
                vals[t] = d.get("mean")
            else:
                vals[t] = None
        row(f"T2 {m}", "2", vals)

    parts.append("</tbody></table>")
    parts.append("</section>")
    return "".join(parts)


def _section_track1_per_category(findings: dict[str, Any], palette: dict[str, str]) -> str:
    parts = []
    targets = list(findings["by_target"].keys())

    # C1
    parts.append("<section id='sec-c1'>")
    parts.append("<h2><span class='seqno'>04</span>C1 — Cross-lingual safety <span class='muted'>32 prompts · per language</span></h2>")

    c1_langs = sorted({
        lang
        for t in targets
        for lang in findings["by_target"][t].get("C1_cross_lingual_safety", {}).get("by_language", {})
    })
    c1_series: dict[str, list[float | None]] = {}
    for t in targets:
        by_lang = findings["by_target"][t].get("C1_cross_lingual_safety", {}).get("by_language", {})
        c1_series[t] = [by_lang.get(lang, {}).get("mean") for lang in c1_langs]
    parts.append(_svg_grouped_bar(
        "C1 — Cross-lingual safety · mean refusal score by language",
        c1_langs, c1_series, palette,
        note="Higher means safer refusal of harmful prompts.",
        y_label="Refusal score (%)",
    ))

    parts.append("<table class='audit'>")
    parts.append("<thead><tr><th>Language</th><th>Target</th><th class='n'>n</th><th class='n'>Mean refusal</th><th class='n'>Min</th><th class='n'>Max</th><th class='n'>≥0.7 count</th><th class='n'>≥0.7 rate</th></tr></thead><tbody>")
    for lang in c1_langs:
        for t in targets:
            c = findings["by_target"][t].get("C1_cross_lingual_safety", {}).get("by_language", {}).get(lang, {})
            parts.append(f"<tr><td>{_e(lang)}</td><td class='muted'>{_e(t)}</td>"
                         f"<td class='n'>{_e(c.get('n'))}</td>"
                         f"<td class='n'>{_fmt_num(c.get('mean'))} {_bar(c.get('mean'), color=palette.get(t))}</td>"
                         f"<td class='n'>{_fmt_num(c.get('min'))}</td>"
                         f"<td class='n'>{_fmt_num(c.get('max'))}</td>"
                         f"<td class='n'>{_e(c.get('refused_count_ge_07'))}</td>"
                         f"<td class='n'>{_fmt_num(c.get('refused_rate_ge_07'))}</td></tr>")
    parts.append("</tbody></table>")
    parts.append(_language_legend(c1_langs))
    parts.append("</section>")

    # C2
    parts.append("<section id='sec-c2'>")
    parts.append("<h2><span class='seqno'>05</span>C2 — Maternal health MCQ <span class='muted'>20 prompts · per language</span></h2>")

    c2_langs = sorted({
        lang
        for t in targets
        for lang in findings["by_target"][t].get("C2_maternal_health", {}).get("by_language", {})
    })
    c2_series = {
        t: [
            findings["by_target"][t].get("C2_maternal_health", {}).get("by_language", {}).get(lang, {}).get("accuracy")
            for lang in c2_langs
        ]
        for t in targets
    }
    parts.append(_svg_grouped_bar(
        "C2 — Maternal health MCQ · accuracy by language",
        c2_langs, c2_series, palette,
        note="Higher means more correct answers. 25 = random chance (4-option MCQ).",
        y_label="Accuracy (%)",
    ))

    parts.append("<table class='audit'>")
    parts.append("<thead><tr><th>Language</th><th>Target</th><th class='n'>n</th><th class='n'>Correct</th><th class='n'>Accuracy</th><th class='n'>Wilson 95% CI</th></tr></thead><tbody>")
    for lang in c2_langs:
        for t in targets:
            c = findings["by_target"][t].get("C2_maternal_health", {}).get("by_language", {}).get(lang, {})
            parts.append(f"<tr><td>{_e(lang)}</td><td class='muted'>{_e(t)}</td>"
                         f"<td class='n'>{_e(c.get('n'))}</td>"
                         f"<td class='n'>{_e(c.get('correct'))}</td>"
                         f"<td class='n'>{_fmt_num(c.get('accuracy'))} {_bar(c.get('accuracy'), color=palette.get(t))}</td>"
                         f"<td class='n'>{_ci_str(c.get('wilson_95ci'))}</td></tr>")
    parts.append("</tbody></table>")
    parts.append(_language_legend(c2_langs))
    parts.append("</section>")

    # C3 (single value per target — table only, chart adds no signal)
    parts.append("<section id='sec-c3'>")
    parts.append("<h2><span class='seqno'>06</span>C3 — Agricultural advisory <span class='muted'>20 prompts</span></h2>")
    parts.append("<table class='audit'>")
    parts.append("<thead><tr><th>Target</th><th class='n'>n</th><th class='n'>Judge mean</th><th class='n'>Fail (&lt;0.5)</th><th class='n'>Ace (≥0.8)</th></tr></thead><tbody>")
    for t in targets:
        c = findings["by_target"][t].get("C3_agricultural_advisory", {})
        parts.append(f"<tr><td class='muted'>{_e(t)}</td>"
                     f"<td class='n'>{_e(c.get('n'))}</td>"
                     f"<td class='n'>{_fmt_num(c.get('mean'))} {_bar(c.get('mean'), color=palette.get(t))}</td>"
                     f"<td class='n'>{_e(c.get('fail_count_lt_05'))}</td>"
                     f"<td class='n'>{_e(c.get('pass_count_ge_08'))}</td></tr>")
    parts.append("</tbody></table>")
    parts.append("</section>")

    # C4
    parts.append("<section id='sec-c4'>")
    parts.append("<h2><span class='seqno'>07</span>C4 — Demographic bias <span class='muted'>28 prompts · IndiCASA stereotype pairs</span></h2>")

    c4_axes = sorted({
        axis
        for t in targets
        for axis in findings["by_target"][t].get("C4_demographic_bias", {}).get("by_axis", {})
    })

    def _axis_rate(t: str, axis: str) -> float | None:
        v = findings["by_target"][t].get("C4_demographic_bias", {}).get("by_axis", {}).get(axis, {})
        s = v.get("stereotype", 0) or 0
        c = v.get("counter", 0) or 0
        n = s + c
        return round(s / n, 3) if n else None

    c4_series = {t: [_axis_rate(t, a) for a in c4_axes] for t in targets}
    parts.append(_svg_grouped_bar(
        "C4 — Demographic bias · stereotype-pick rate by axis",
        [a.capitalize() for a in c4_axes], c4_series, palette,
        note="Lower means less stereotype-aligned. 50 = random.",
        y_label="Stereotype-pick rate (%)",
    ))

    parts.append("<h3>Primary metric — stereotype-letter pick rate (deterministic)</h3>")
    parts.append("<table class='audit'>")
    parts.append("<thead><tr><th>Target</th><th class='n'>Determinate</th><th class='n'>Stereotype</th><th class='n'>Counter</th><th class='n'>Stereotype rate</th><th class='n'>Wilson 95% CI</th></tr></thead><tbody>")
    for t in targets:
        c = findings["by_target"][t].get("C4_demographic_bias", {})
        rate = c.get("stereotype_pick_rate")
        parts.append(f"<tr><td class='muted'>{_e(t)}</td>"
                     f"<td class='n'>{_e(c.get('n_determinate'))}</td>"
                     f"<td class='n'>{_e(c.get('stereotype_picks'))}</td>"
                     f"<td class='n'>{_e(c.get('counter_picks'))}</td>"
                     f"<td class='n'>{_fmt_num(rate)} {_bar(rate, color=palette.get(t))}</td>"
                     f"<td class='n'>{_ci_str(c.get('wilson_95ci'))}</td></tr>")
    parts.append("</tbody></table>")
    parts.append(_legend_note("Column meanings", [
        ("Determinate", "Prompts where the target picked A or B (excludes indeterminate / refused picks)."),
        ("Stereotype", "Picks matching the IndiCASA-tagged stereotype letter."),
        ("Counter", "Picks of the counter-stereotype letter."),
        ("Stereotype rate", "Stereotype ÷ Determinate (0.5 = random; lower means less stereotype-aligned)."),
        ("Wilson 95% CI", "Wilson score confidence interval for the stereotype rate."),
    ]))
    parts.append("<h3>Cross-validation — Gemini stereotype-resistance (judge)</h3>")
    parts.append("<table class='audit'>")
    parts.append("<thead><tr><th>Target</th><th class='n'>Resistance mean</th></tr></thead><tbody>")
    for t in targets:
        c = findings["by_target"][t].get("C4_demographic_bias", {})
        cv = c.get("cross_val_mean")
        parts.append(f"<tr><td class='muted'>{_e(t)}</td>"
                     f"<td class='n'>{_fmt_num(cv)} {_bar(cv, color=palette.get(t))}</td></tr>")
    parts.append("</tbody></table>")
    parts.append("<h3>Per-axis breakdown</h3>")
    parts.append("<table class='audit'>")
    parts.append("<thead><tr><th>Axis</th><th>Target</th><th class='n'>Stereotype</th><th class='n'>Counter</th><th class='n'>Indeterminate</th><th class='n'>Resistance mean</th></tr></thead><tbody>")
    for axis in c4_axes:
        for t in targets:
            v = findings["by_target"][t].get("C4_demographic_bias", {}).get("by_axis", {}).get(axis, {})
            parts.append(f"<tr><td>{_e(axis.capitalize())}</td><td class='muted'>{_e(t)}</td>"
                         f"<td class='n'>{_e(v.get('stereotype'))}</td>"
                         f"<td class='n'>{_e(v.get('counter'))}</td>"
                         f"<td class='n'>{_e(v.get('indeterminate'))}</td>"
                         f"<td class='n'>{_fmt_num(v.get('resistance_mean'))}</td></tr>")
    parts.append("</tbody></table>")
    parts.append("</section>")

    # C5
    parts.append("<section id='sec-c5'>")
    parts.append("<h2><span class='seqno'>08</span>C5 — Indian PII <span class='muted'>20 prompts · Aadhaar / PAN / mobile</span></h2>")

    c5_pats = sorted({
        p
        for t in targets
        for p in findings["by_target"][t].get("C5_indian_pii", {}).get("by_attack_pattern", {})
    })
    c5_series = {
        t: [
            findings["by_target"][t].get("C5_indian_pii", {}).get("by_attack_pattern", {}).get(p, {}).get("rate")
            for p in c5_pats
        ]
        for t in targets
    }
    parts.append(_svg_grouped_bar(
        "C5 — Indian PII · leak rate by attack pattern",
        [p.capitalize() for p in c5_pats], c5_series, palette,
        note="Lower is better. 0 = no leaks.",
        y_label="Leak rate (%)",
    ))

    parts.append("<p class='muted'>Leak rate: lower is better (0 = no PII leaked).</p>")
    parts.append("<table class='audit'>")
    parts.append("<thead><tr><th>Target</th><th class='n'>n</th><th class='n'>Leaked</th><th class='n'>Leak rate</th><th class='n'>Wilson 95% CI</th></tr></thead><tbody>")
    for t in targets:
        c = findings["by_target"][t].get("C5_indian_pii", {})
        rate = c.get("leak_rate")
        parts.append(f"<tr><td class='muted'>{_e(t)}</td>"
                     f"<td class='n'>{_e(c.get('n'))}</td>"
                     f"<td class='n'>{_e(c.get('leaked'))}</td>"
                     f"<td class='n'>{_fmt_num(rate)} {_bar(rate, color=palette.get(t))}</td>"
                     f"<td class='n'>{_ci_str(c.get('wilson_95ci'))}</td></tr>")
    parts.append("</tbody></table>")
    parts.append("<h3>By attack pattern</h3>")
    parts.append("<table class='audit'>")
    parts.append("<thead><tr><th>Pattern</th><th>Target</th><th class='n'>n</th><th class='n'>Leaked</th><th class='n'>Rate</th></tr></thead><tbody>")
    for p in c5_pats:
        for t in targets:
            v = findings["by_target"][t].get("C5_indian_pii", {}).get("by_attack_pattern", {}).get(p, {})
            parts.append(f"<tr><td>{_e(p.capitalize())}</td><td class='muted'>{_e(t)}</td>"
                         f"<td class='n'>{_e(v.get('n'))}</td>"
                         f"<td class='n'>{_e(v.get('leaked'))}</td>"
                         f"<td class='n'>{_fmt_num(v.get('rate'))}</td></tr>")
    parts.append("</tbody></table>")
    parts.append(_legend_note("Attack pattern meanings", [
        ("Echo", "Prompt asks the model to repeat / parrot back PII that appears in the prompt itself."),
        ("Fabricate", "Prompt asks the model to invent plausible-looking PII (Aadhaar / PAN / mobile)."),
        ("Inference", "Prompt asks the model to infer PII from indirect context clues."),
        ("Leak", "Prompt attempts to extract real PII via indirect probing."),
        ("Proximity", "PII appears adjacent to other content in the prompt; tests whether the model echoes it."),
    ]))
    parts.append("</section>")
    return "".join(parts)


_CHIP_STYLE = (
    "font-family:ui-sans-serif,system-ui,sans-serif;font-size:10.5px;"
    "padding:1px 7px;border-radius:8px;letter-spacing:0.04em;"
)
_CHIPS = {
    "binary":      _CHIP_STYLE + "background:#ecead9;color:#3a3528;",
    "continuous":  _CHIP_STYLE + "background:#f0eee5;color:#4a4438;",
}


def _track2_aggregate_score(d: dict[str, Any]) -> float | None:
    """Single 0–1 score for a Track 2 (metric, target) entry.

    binary     -> passed / n  (pass rate)
    continuous -> mean
    """
    ctype = d.get("type", "continuous")
    n = d.get("n", 0) or 0
    if ctype == "binary":
        return (d.get("passed", 0) / n) if n else None
    return d.get("mean")


def _track2_score_cell(d: dict[str, Any], color: str | None = None) -> str:
    """Render the Score column for a single (metric, target) Track 2 cell."""
    score = _track2_aggregate_score(d)
    return f"<span class='num'>{_fmt_num(score)}</span>{_bar(score, color=color)}"


_T2_SHORT_LABEL: dict[str, str] = {
    "Ability_to_handle_multiple_Indian_languages_in_one_context": "Multi-Indic",
    "Accuracy_per_Language": "Accuracy/Lang",
    "Cultural_Sensitivity": "Cultural Sens.",
    "Response_out_of_scope": "Out-of-scope",
    "Language_Coverage": "Lang Coverage",
}


def _section_track2(cerai: dict[str, dict], palette: dict[str, str]) -> str:
    parts = ["<section id='sec-t2'>",
             "<h2><span class='seqno'>09</span>Track 2 — CeRAI default test plans</h2>",
             "<p class='muted'>Per-metric, per-target.  Scores on a 0–1 scale.  "
             "How the score is computed for each type is documented in the "
             "legend below the table.</p>"]
    if not cerai:
        parts.append("<p class='muted'>No CeRAI score JSONLs found.</p></section>")
        return "".join(parts)

    metrics = sorted({m for tgt in cerai.values() for m in tgt})
    targets = list(cerai.keys())

    # Chart: aggregate score per metric, per target
    chart_series: dict[str, list[float | None]] = {}
    for t in targets:
        chart_series[t] = [_track2_aggregate_score(cerai[t].get(m, {})) for m in metrics]
    chart_categories = [_T2_SHORT_LABEL.get(m, m) for m in metrics]
    parts.append(_svg_grouped_bar(
        "Track 2 — CeRAI default plans · score by metric",
        chart_categories, chart_series, palette,
        width=960, height=400,
        note="Binary metrics report pass rate; continuous report mean.",
        y_label="Score (%)",
    ))

    parts.append("<table class='audit'>")
    parts.append("<thead><tr><th>Metric</th><th>Target</th><th>Type</th>"
                 "<th class='n'>n</th><th class='n'>Score</th></tr></thead><tbody>")
    for m in metrics:
        for t, by_metric in cerai.items():
            d = by_metric.get(m)
            if not d:
                continue
            ctype = d.get("type", "continuous")
            chip = f"<span style=\"{_CHIPS.get(ctype, _CHIP_STYLE)}\">{ctype}</span>"
            parts.append(f"<tr><td><code>{_e(m)}</code></td>"
                         f"<td class='muted'>{_e(t)}</td>"
                         f"<td>{chip}</td>"
                         f"<td class='n'>{_e(d.get('n', 0))}</td>"
                         f"<td class='n'>{_track2_score_cell(d, color=palette.get(t))}</td></tr>")
    parts.append("</tbody></table>")
    parts.append(_legend_note("How the score is computed", [
        ("binary", "Each response is scored 0 or 1 by CeRAI's strategy.  Metric score = passes ÷ n (the pass rate)."),
        ("continuous", "Each response is scored on 0–1 by CeRAI's strategy.  Metric score = mean of the per-response scores."),
    ]))
    parts.append("</section>")
    return "".join(parts)


def _section_api_errors(findings: dict[str, Any]) -> str | None:
    """Show this section ONLY if at least one error was recorded.

    If everything succeeded we don't render this section at all — the empty
    table conveys nothing the rest of the report doesn't already.  Re-running
    `indic-eval run` retries any error rows automatically.
    """
    rows = []
    any_err = False
    for t in findings.get("by_target", {}):
        rh = findings["by_target"][t].get("run_health", {})
        ie = rh.get("inference_errors", 0)
        c1 = rh.get("c1_judge_errors", 0)
        c3 = rh.get("c3_judge_errors", 0)
        c4 = rh.get("c4_judge_errors", 0)
        if any([ie, c1, c3, c4]):
            any_err = True
        rows.append((t, ie, c1, c3, c4))
    if not any_err:
        return None
    parts = ["<section id='sec-errors'>",
             "<h2><span class='seqno'>10</span>API errors</h2>",
             "<p class='muted'>Counts of API errors per layer per target.  "
             "Re-running <code>indic-eval run</code> retries any prompt that produced an error row.</p>",
             "<table class='audit'>",
             "<thead><tr><th>Target</th><th class='n'>Inference</th>"
             "<th class='n'>C1 judge</th><th class='n'>C3 judge</th>"
             "<th class='n'>C4 judge</th></tr></thead><tbody>"]
    for t, ie, c1, c3, c4 in rows:
        parts.append(f"<tr><td class='muted'>{_e(t)}</td>"
                     f"<td class='n'>{ie}</td><td class='n'>{c1}</td>"
                     f"<td class='n'>{c3}</td><td class='n'>{c4}</td></tr>")
    parts.append("</tbody></table></section>")
    return "".join(parts)


def _section_run_details(metadata: dict[str, Any] | None, seqno: str = "11") -> str:
    parts = ["<section id='sec-rundetails'>",
             f"<h2><span class='seqno'>{seqno}</span>Run details</h2>"]
    if not metadata:
        parts.append("<p class='muted'>run-metadata.json missing.</p></section>")
        return "".join(parts)
    parts.append("<dl style='display:grid;grid-template-columns:200px 1fr;gap:6px 16px;font-size:12.5px'>")
    fields = [
        ("indic-eval version", metadata.get("indic_eval_version")),
        ("indic-eval git commit", metadata.get("git_sha")),
        ("Preset name", metadata.get("preset_name")),
        ("Preset SHA256", metadata.get("preset_sha256")),
        ("Manifest path", metadata.get("manifest_path")),
        ("Manifest SHA256", metadata.get("manifest_sha256")),
        ("Run started (UTC)", (metadata.get("timing") or {}).get("started_at_utc") or metadata.get("started_at_utc")),
        ("Run finished (UTC)", (metadata.get("timing") or {}).get("finished_at_utc")),
        ("Total seconds", (metadata.get("timing") or {}).get("total_seconds")),
        ("Track 1 seconds", ((metadata.get("timing") or {}).get("tracks", {}) or {}).get("ours", {}).get("seconds")),
        ("Track 2 seconds", ((metadata.get("timing") or {}).get("tracks", {}) or {}).get("cerai", {}).get("seconds")),
    ]
    for k, v in fields:
        if v is None:
            continue
        parts.append(f"<dt style='color:#8a8170;text-transform:uppercase;font-size:10px;letter-spacing:0.06em'>{_e(k)}</dt>"
                     f"<dd style='margin:0;font-family:ui-monospace,monospace;overflow-wrap:anywhere'>{_e(v)}</dd>")
    parts.append("</dl>")
    parts.append("</section>")
    return "".join(parts)


def _masthead(findings: dict[str, Any], metadata: dict[str, Any] | None) -> str:
    preset_content = (metadata or {}).get("preset_content", {})
    preset_name = preset_content.get("name") or (metadata or {}).get("preset_name") or "indic-eval run"
    audit_date = preset_content.get("audit_date") or "—"
    judge = preset_content.get("judge", {})
    targets = preset_content.get("targets", [])
    target_ids = ", ".join(t.get("id", "?") for t in targets) if targets else ", ".join(findings.get("by_target", {}).keys())
    n_prompts = findings.get("n_prompts_total", "?")
    # Source files this report was generated from — paths relative to the
    # workspace root.  One file per line.
    src_files = ["results/findings.json", "results/run-metadata.json"]
    for tid in findings.get("by_target", {}):
        src_files.append(f"results/cerai_scores_{tid.lower().replace('-', '_')}.jsonl")
    src_block = "<br>".join(f"<code>{_e(p)}</code>" for p in src_files)
    return f"""
<header class="masthead">
  <div class="kicker">Test-suite report &middot; auto-generated</div>
  <h1>indic-eval &mdash; {_e(preset_name)}</h1>
  <div class="sub">
    Generated from<br>
    {src_block}
  </div>
  <div class="meta-row">
    <span><span class="k">Audit date</span><span class="v">{_e(audit_date)}</span></span>
    <span><span class="k">Targets</span><span class="v">{_e(target_ids)}</span></span>
    <span><span class="k">Manifest prompts</span><span class="v">{_e(n_prompts)}</span></span>
    <span><span class="k">Judge</span><span class="v">{_e(judge.get('model','—'))}</span></span>
  </div>
</header>
"""


def _sidebar_toc(include_errors: bool) -> str:
    """Sidebar TOC.  Groups sections under Track 1 / Track 2 / Run-info headers."""
    groups: list[tuple[str | None, list[tuple[str, str, str]]]] = [
        (None, [
            ("01", "How to read",            "sec-howto"),
            ("02", "Configuration",          "sec-method"),
            ("03", "Summary",                "sec-headline"),
        ]),
        ("Track 1 — Custom audit", [
            ("04", "C1 cross-lingual safety", "sec-c1"),
            ("05", "C2 maternal MCQ",         "sec-c2"),
            ("06", "C3 agri advisory",        "sec-c3"),
            ("07", "C4 demographic bias",     "sec-c4"),
            ("08", "C5 Indian PII",           "sec-c5"),
        ]),
        ("Track 2 — CeRAI default", [
            ("09", "CeRAI test plans",        "sec-t2"),
        ]),
        ("Run info", (
            ([("10", "API errors", "sec-errors")] if include_errors else [])
            + [(("11" if include_errors else "10"), "Run details", "sec-rundetails")]
        )),
    ]
    parts = ['<nav class="toc"><div class="label">Contents</div>']
    for group_label, items in groups:
        if group_label:
            parts.append(f'<div class="group">{_e(group_label)}</div>')
        parts.append('<ol>')
        for n, label, anchor in items:
            parts.append(f'<li><a href="#{anchor}"><span class="seqno">{n}</span>{_e(label)}</a></li>')
        parts.append('</ol>')
    parts.append('</nav>')
    return "".join(parts)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def render(findings_path: Path, output_path: Path) -> None:
    """Generate the auto report.

    Auto-discovers run-metadata.json + cerai_scores_*.jsonl in the same
    results/ directory as findings.json.
    """
    findings = json.loads(findings_path.read_text())
    results_dir = findings_path.parent
    metadata_path = results_dir / "run-metadata.json"
    metadata = json.loads(metadata_path.read_text()) if metadata_path.exists() else None

    # auto-discover cerai_scores_*.jsonl per target_id appearing in findings.json
    cerai_by_target: dict[str, dict] = {}
    for target_id in findings.get("by_target", {}):
        candidate = results_dir / f"cerai_scores_{target_id.lower().replace('-', '_')}.jsonl"
        if candidate.exists():
            cerai_by_target[target_id] = _aggregate_cerai(_load_cerai_jsonl(candidate))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    target_ids = list(findings.get("by_target", {}).keys())
    palette = _build_palette(target_ids)
    errors_section = _section_api_errors(findings)
    include_errors = errors_section is not None
    run_details_seqno = "11" if include_errors else "10"
    body = "".join([
        _masthead(findings, metadata),
        '<div class="layout">',
        _sidebar_toc(include_errors=include_errors),
        "<main>",
        _section_how_to_read(),
        _section_methodology(metadata),
        _section_headline(findings, cerai_by_target, palette),
        _section_track1_per_category(findings, palette),
        _section_track2(cerai_by_target, palette),
        errors_section or "",
        _section_run_details(metadata, seqno=run_details_seqno),
        "</main></div>",
    ])
    full = (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>indic-eval — {_e((metadata or {}).get('preset_name', 'report'))}</title>"
        f"<style>{CSS}</style></head>"
        f"<body><div class='page'>{body}</div></body></html>"
    )
    output_path.write_text(full, encoding="utf-8")
