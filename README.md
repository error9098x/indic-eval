# indic-eval

A reproducible test suite for Indic-language LLM responsible-AI audits, built
on top of [CeRAI AIEvaluationTool](https://github.com/cerai-iitm/AIEvaluationTool)
v2.0. The reference run audits **Sarvam-30B** against **Gemma 4 26B-A4B-IT**
as a baseline.

Submission for the Gates Foundation AI Fellows Program — India 2026 (Path A).

## Quick links

| | |
|---|---|
| Live site | https://indic-eval.kaintura.com |
| Auto-generated report | https://indic-eval.kaintura.com/report |
| HuggingFace dataset | https://huggingface.co/datasets/procodec/sarvam-30b-audit-prompts |
| Source | https://github.com/error9098x/indic-eval |

## Requirements

- Python 3.12+
- Docker Engine 24+ with Docker Compose v2  *(skip with `--tracks ours`)*
- ~16 GB RAM  *(CPU-only)*
- API keys for OpenRouter and Sarvam *(plus HuggingFace if pushing the manifest dataset)*

### Installing Docker

| Platform | Install |
|---|---|
| macOS, Windows | [Docker Desktop](https://docs.docker.com/desktop/) |
| Linux | `curl -fsSL https://get.docker.com \| sudo sh` *(official convenience script)* |

## Quick start

```bash
git clone https://github.com/error9098x/indic-eval.git
cd indic-eval

cp .env.example .env                                     # fill in 3 keys

python3 -m venv .venv && source .venv/bin/activate
pip install -e .

indic-eval run --preset presets/sarvam-30b-preset.yaml   # writes results/ + site/report.html
```

The CeRAI v2.0 release is fetched automatically into a gitignored
`third_party/` checkout on the first Track 2 run.

### CLI flags

```bash
indic-eval run --smoke                  # 1 prompt per category / per CeRAI metric
indic-eval run --tracks ours            # skip Track 2 (no Docker needed)
indic-eval run --tracks cerai           # skip Track 1
indic-eval run --targets <id>           # one target only
indic-eval run --resume                 # keep prior JSONLs (default wipes for a fresh run)
indic-eval run --no-report              # skip the HTML render
indic-eval report                       # re-render report.html from results/
indic-eval validate --preset <yaml>     # CI lint
indic-eval cleanup                      # docker compose down
```

Standalone bootstrap (idempotent; pass `--force` to re-download the CeRAI tarball):

```bash
./scripts/00-bootstrap-cerai.sh
```

## Running a different model

The preset YAML is the single config knob. To audit a different target, copy
`presets/sarvam-30b-preset.yaml` and edit the `targets:` block — nothing else
in the preset is model-specific:

```yaml
targets:
  - id: my-custom-target
    model: my-org/my-model                       # provider's model id
    base_url: https://api.openai.com/v1          # OpenAI-compatible endpoint
    api_key_env: MY_API_KEY                      # env var name in .env

  - id: another-target                           # multiple targets run side by side
    model: anthropic/claude-3-opus
    base_url: https://openrouter.ai/api/v1
    api_key_env: OPENROUTER_API_KEY
```

`judge:` (LLM judge for C1 / C3 / C4), `ours.limit_per_category` (per-category
sample size), and `cerai.plans` (which CeRAI metrics to run) work the same
way — see the reference preset for the full shape. Run with:

```bash
indic-eval run --preset presets/my-custom.yaml
```

## Repo layout

```
indic-eval/
├── indic_eval/          The Python package (CLI, runner, analysis, report, tracks)
├── manifest/            The eval contract — 120 prompts + 18 PII probes
├── presets/             Run configs (sarvam-30b-preset.yaml ships as reference)
├── cerai/               7 patched CeRAI files (vendored at v2.0) + env templates
├── scripts/             bootstrap + manifest → CeRAI datapoints converter
├── results/             May 13 2026 audit outputs
├── site/                Public landing page + auto-generated report
└── third_party/         CeRAI v2.0 checkout (gitignored; recreated by bootstrap)
```

## Test suite

| Track | Category / Plan          | Source                              | Prompts / Metrics  |
|-------|--------------------------|-------------------------------------|--------------------|
| 1     | C1 Cross-lingual safety  | XSafety + Aya Red-Team + MultiJail  | 32 prompts         |
| 1     | C2 Maternal/child health | MedMCQA-Indic (OB/GYN filter)       | 25 prompts         |
| 1     | C3 Agricultural advisory | DigiGreen / Farmer.Chat             | 20 prompts         |
| 1     | C4 Demographic bias      | IndiCASA (5 axes)                   | 28 prompts         |
| 1     | C5 Indian PII            | LLM-PBE × DPDP × format-valid       | 15 prompts         |
| 2     | T1 Responsible AI        | CeRAI bundled                       | 4 metrics          |
| 2     | T3 Guardrails & Safety   | CeRAI bundled                       | 1 metric           |
| 2     | T4 Language Support      | CeRAI bundled                       | 3 metrics          |

## License

MIT. See [LICENSE](LICENSE).
