#!/usr/bin/env bash
# Download CeRAI v2.0 release, overlay our 7 patched files, render env
# templates. Idempotent — re-runs wipe and re-extract the CeRAI tree from
# the release tarball so any in-place edits are reset.
set -euo pipefail

# CeRAI v2.0 release — tag v2.0 maps to commit 190c1297d4c5178249b03255f3688b765128b4a5
# (verified via api.github.com/repos/cerai-iitm/AIEvaluationTool/git/refs/tags/v2.0).
CERAI_TARBALL="https://github.com/cerai-iitm/AIEvaluationTool/archive/refs/tags/v2.0.tar.gz"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CERAI_DIR="${REPO_ROOT}/third_party/AIEvaluationTool"

require() {
  command -v "$1" >/dev/null 2>&1 || { echo "missing: $1" >&2; exit 1; }
}
require curl
require tar
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

# Tarball download is the expensive step (~50 MB). Skip it when the checkout
# already exists; --force re-downloads from scratch (e.g. after a corrupted
# extract or when bumping the pinned release).
FORCE=0
for arg in "$@"; do
  case "$arg" in --force|-f) FORCE=1 ;; esac
done
if [[ "${FORCE}" -eq 1 || ! -f "${CERAI_DIR}/docker-compose.yml" ]]; then
  rm -rf "${CERAI_DIR}"
  mkdir -p "${CERAI_DIR}"
  curl -fsSL "${CERAI_TARBALL}" | tar -xz --strip-components=1 -C "${CERAI_DIR}"
fi

# Overlay our 7 modified files onto the extracted v2.0 tree
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
echo "  release:     v2.0 (commit 190c1297)"
echo "  overlay:     7 files from cerai/"
echo "  env files:   .env, strategy.env rendered from repo-root .env"
