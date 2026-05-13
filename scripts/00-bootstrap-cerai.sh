#!/usr/bin/env bash
# Clone CeRAI at the pinned SHA, overlay our 7 patched files, render env
# templates. Idempotent — re-runs reset the cloned tree to the pinned SHA
# before re-overlaying.
set -euo pipefail

CERAI_REMOTE="https://github.com/cerai-iitm/AIEvaluationTool.git"
CERAI_PINNED_SHA="190c1297d4c5178249b03255f3688b765128b4a5"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CERAI_DIR="${REPO_ROOT}/third_party/AIEvaluationTool"

require() {
  command -v "$1" >/dev/null 2>&1 || { echo "missing: $1" >&2; exit 1; }
}
require git
require docker
require envsubst
require python3

if ! docker compose version >/dev/null 2>&1; then
  echo "missing: docker compose v2 (got: $(docker --version))" >&2
  exit 1
fi

if [[ ! -f "${REPO_ROOT}/.env" ]]; then
  echo "missing: ${REPO_ROOT}/.env — copy .env.example and fill the 3 keys" >&2
  exit 1
fi

# Clone CeRAI if missing; otherwise reset to pinned SHA (re-run safety)
if [[ ! -d "${CERAI_DIR}/.git" ]]; then
  mkdir -p "$(dirname "${CERAI_DIR}")"
  git clone --quiet "${CERAI_REMOTE}" "${CERAI_DIR}"
fi
cd "${CERAI_DIR}"
git fetch --quiet origin
git checkout --quiet --detach "${CERAI_PINNED_SHA}"
git reset --hard --quiet "${CERAI_PINNED_SHA}"

# Overlay our 7 modified files onto the upstream checkout
cp -r "${REPO_ROOT}/cerai/src"/. "${CERAI_DIR}/src/"
cp    "${REPO_ROOT}/cerai/docker-compose.yml" "${CERAI_DIR}/docker-compose.yml"

# Render env files from repo-root .env
set -a
# shellcheck disable=SC1091
source "${REPO_ROOT}/.env"
set +a
envsubst < "${REPO_ROOT}/cerai/cerai.env.example"    > "${CERAI_DIR}/.env"
envsubst < "${REPO_ROOT}/cerai/strategy.env.example" > "${CERAI_DIR}/strategy.env"

# Regenerate CeRAI-format datapoints from our manifest
# (script lands in a later commit; skip if absent)
if [[ -f "${REPO_ROOT}/scripts/manifest_to_cerai_datapoints.py" ]]; then
  python3 "${REPO_ROOT}/scripts/manifest_to_cerai_datapoints.py" \
    --manifest "${REPO_ROOT}/manifest/prompts_manifest.json" \
    --out      "${CERAI_DIR}/data/sarvam_audit_datapoints.json"
fi

echo "CeRAI bootstrapped at ${CERAI_DIR}"
echo "  pinned SHA:  ${CERAI_PINNED_SHA}"
echo "  overlay:     7 files from cerai/"
echo "  env files:   .env, strategy.env rendered from repo-root .env"
