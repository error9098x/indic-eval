# indic-eval

A reproducible LLM evaluation harness for Indic responsible-AI audits, built
on top of the [CeRAI AIEvaluationTool](https://github.com/cerai-iitm/AIEvaluationTool)
with seven patches for reasoning-model support. Reference audit ships against
**Sarvam-30B**, India's sovereign-built reasoning LLM, with **Gemma 4 26B-A4B-IT**
as a baseline.

Submission for the **Gates Foundation AI Fellows Program — India 2026**
technical assignment (Path A — Evaluate & Report).

## What this is

- A **120-prompt audit suite** across 5 categories (cross-lingual safety,
  maternal/child health, agricultural advisory, demographic bias, Indian PII),
  pre-registered as the eval contract before any prompt was sent to a target.
- **87% of prompts directly sampled from peer-reviewed benchmarks** (XSafety,
  Aya Red-Team, MultiJail, MedMCQA-Indic, DigiGreen, IndiCASA). The remaining
  13% are PII probes constructed deterministically from documented format
  specifications (DPDP Act 2023 × LLM-PBE attack patterns × format-valid
  synthetic values). Zero prompts are AI-synthesized end-to-end.
- **Seven patches** to CeRAI v2.0's `LOCAL` provider path + judge dispatch,
  vendored as full source files under [`cerai/`](cerai/) for transparent diff
  review.
- A **self-contained auto-generated report** ([`site/report.html`](site/report.html))
  with 5 inline-SVG grouped-bar charts and 9 per-section data tables.

## Quick links

| Artefact | Where |
|---|---|
| 🌐 Live findings page | [`site/index.html`](site/index.html) — opens in any browser |
| 📊 Auto-generated test-suite report | [`site/report.html`](site/report.html) |
| 🤗 HuggingFace dataset (120 prompts, viewer + API) | [procodec/sarvam-30b-audit-prompts](https://huggingface.co/datasets/procodec/sarvam-30b-audit-prompts) |
| 🩹 CeRAI patches (7 files, ~640 LOC) | [`cerai/`](cerai/) — vendored at v2.0 release |
| 📦 Audit manifest (canonical JSON) | [`manifest/prompts_manifest.json`](manifest/prompts_manifest.json) |

## Requirements

- Python 3.12+
- Docker Engine 24+ with Docker Compose v2  *(Track 2 only — `--tracks ours` skips it)*
- ~16 GB RAM  *(CPU-only path; no GPU required)*
- API keys: OpenRouter (judge + Gemma baseline), Sarvam (target), HuggingFace
  *(only for pushing the manifest dataset; reading the published dataset works
  without auth)*

## Quick start

```bash
git clone https://github.com/error9098x/indic-eval.git
cd indic-eval

cp .env.example .env                                    # fill in 3 keys

python3 -m venv .venv && source .venv/bin/activate
pip install -e .

indic-eval run --preset presets/sarvam-30b-preset.yaml  # runs both tracks, writes
                                                        # results/ + site/report.html
```

The first `indic-eval run` invocation that touches Track 2 auto-bootstraps
CeRAI: downloads the v2.0 release tarball into `third_party/AIEvaluationTool/`,
overlays the seven patched files from `cerai/`, renders the env files from
the repo-root `.env`, and regenerates the CeRAI-format datapoints from the
manifest. Subsequent runs reuse the cached checkout in ~70 ms.

### Common flags

```bash
indic-eval run --preset presets/… --smoke              # 1 prompt per category, 1 per CeRAI metric
indic-eval run --preset presets/… --tracks ours        # skip CeRAI / docker entirely
indic-eval run --preset presets/… --targets sarvam-30b # one target only
indic-eval run --preset presets/… --resume             # keep prior JSONLs (default wipes for fresh)
indic-eval run --preset presets/… --no-report          # skip the site/report.html render
indic-eval report                                       # re-render report.html from results/
indic-eval validate --preset presets/…                  # CI lint
indic-eval cleanup                                      # docker compose down
```

Bootstrap is also invokable standalone:

```bash
./scripts/00-bootstrap-cerai.sh           # idempotent; lazy on tarball download
./scripts/00-bootstrap-cerai.sh --force   # re-download from scratch
```

## Repo layout

```
indic-eval/
├── README.md            (this file)
├── LICENSE              MIT for code; CC-BY-4.0 for manifest/
├── .env.example         3 keys: OPENROUTER_API_KEY / SARVAM_API_KEY / HF_TOKEN
├── pyproject.toml       indic-eval console_scripts
│
├── indic_eval/          The Python package (CLI, runner, analysis, report, tracks)
├── manifest/            The eval contract — 120 prompts + 18 PII probes
├── presets/             YAML run configs (sarvam-30b-preset.yaml ships as the reference)
│
├── cerai/               The 7 patched CeRAI files (vendored at v2.0)
│   ├── src/app/interface_manager/{context,api_handler}.py
│   ├── src/lib/interface_manager/client.py
│   ├── src/lib/strategy/{llm_judge,utils_new}.py
│   ├── src/app/testcase_executor/main.py
│   ├── docker-compose.yml
│   ├── cerai.env.example     CeRAI service env template
│   └── strategy.env.example  CeRAI strategy-module env template
│
├── scripts/
│   ├── 00-bootstrap-cerai.sh             clones CeRAI v2.0 + overlays cerai/
│   └── manifest_to_cerai_datapoints.py   manifest → CeRAI importer format
│
├── results/             May 13 2026 audit outputs (gitignored under raw/)
│   ├── findings.json
│   ├── run-metadata.json
│   ├── inference_<target>.jsonl
│   ├── cerai_scores_<target>.jsonl
│   ├── c{1,3,4}_*_scores.jsonl
│   ├── cerai/summary.json
│   └── refusal_audit_*.{md,json}, quality_audit.md, ambiguity_audit.md, …
│
├── site/
│   ├── index.html       Placeholder homepage (live endpoint)
│   ├── report.html      Auto-generated test-suite report
│   └── static/          Bulma + Nerfies assets
│
└── third_party/         CeRAI v2.0 checkout (gitignored; recreated by bootstrap)
```

## Methodology summary

### Path choice
**Path A — Evaluate & Report**, with patches as "materially modified code"
(explicitly permitted by the brief). CeRAI v2.0 has narrower gaps in the
`LOCAL` provider path that don't apply to its OpenAI / Gemini paths.
Patching ~640 LOC across 7 files is the constructive contribution;
rebuilding from scratch would have discarded CeRAI's 60+ metric
implementations.

### Why Sarvam-30B
- From-scratch sovereign reasoning LLM trained under the IndiaAI Mission.
- API-accessible (OpenAI-compatible chat completions at `api.sarvam.ai`).
- No public bias / safety / PII evaluation exists for the model — the audit
  fills that gap.

### Test suite — sourcing-tier discipline
Every prompt belongs to one of:
- **T1** — direct sample from a peer-reviewed benchmark *(102 prompts)*
- **T3** — constructed from a documented format spec *(18 PII probes)*
- **T4** — AI-synthesized prompt content *(**zero** prompts; explicitly excluded)*

### Metric-to-category mapping

| Cat | Topic | n | Primary metric (Track 1) | LLM judge |
|---|---|---|---|---|
| C1 | Cross-lingual safety / refusal | 32 | Gemini 3.1 Flash Lite rubric (0..1) | ✅ |
| C2 | Maternal & child health MCQ | 25 | Letter-accuracy vs ground truth | — |
| C3 | Agricultural advisory | 20 | Gemini 3.1 Flash Lite rubric vs DigiGreen reference | ✅ |
| C4 | Caste / religion / gender / disability / SES bias | 28 | Stereotype-letter pick rate vs IndiCASA label | + judge cross-val |
| C5 | Indian PII probes | 15 | Aadhaar (Verhoeff) / PAN / TRAI-mobile regex | — |

### Statistical analysis
- Wilson 95% CIs on every binomial proportion (refusal rate, MCQ accuracy,
  stereotype-pick rate, leak rate).
- Per-axis stereotype tally on C4 cross-validated by a Gemini rubric.

## Citations

- **IndiCASA** — Santhosh et al., AAAI/AIES 2025 ([arXiv:2510.02742](https://arxiv.org/abs/2510.02742))
- **XSafety** — Wang et al., ACL 2024 Findings ([arXiv:2310.00905](https://arxiv.org/abs/2310.00905))
- **Aya Red-Team** — Aksitov et al., 2024 ([arXiv:2406.18682](https://arxiv.org/abs/2406.18682))
- **MultiJail** — Deng et al., ICLR 2024 ([arXiv:2310.06474](https://arxiv.org/abs/2310.06474))
- **MedMCQA-Indic** — Pal et al., PMLR 2022; Indic translation by ekacare ([HF dataset](https://huggingface.co/datasets/ekacare/MedMCQA-Indic))
- **DigiGreen / Farmer.Chat** ([arXiv:2603.03294](https://arxiv.org/abs/2603.03294))
- **LLM-PBE** — Li et al., VLDB 2024 ([arXiv:2408.12787](https://arxiv.org/abs/2408.12787))
- **CeRAI AIEvaluationTool v2.0** — Centre for Responsible AI, IIT Madras ([GitHub](https://github.com/cerai-iitm/AIEvaluationTool))

## License

- **Code** — MIT (see [LICENSE](LICENSE)).
- **Manifest** (`manifest/prompts_manifest.json`) — CC-BY-4.0, the most
  restrictive license among the source benchmarks. Per-prompt attribution is
  preserved in each row's `source_ref` / `source_url` / `license` fields.

## Contact

Aviral Kaintura · [@error9098x](https://github.com/error9098x) · procodecavi@gmail.com
