#!/usr/bin/env bash
# Bash 3.2-compatible, validated read-only access to the schema-v3 manifest.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
MANIFEST="${MODELS_MANIFEST:-${REPO_ROOT}/models-manifest.toml}"
MODEL_CACHE_TOOL="${SCRIPT_DIR}/model_cache.py"

if [ ! -f "${MANIFEST}" ]; then
    echo "ERROR: models-manifest.toml not found at ${MANIFEST}" >&2
    exit 1
fi

validate_manifest() {
    python3 "${MODEL_CACHE_TOOL}" --manifest "${MANIFEST}" validate >/dev/null
}

get_meta() {
    python3 "${MODEL_CACHE_TOOL}" --manifest "${MANIFEST}" query meta "$1"
}

get_model_keys() {
    python3 "${MODEL_CACHE_TOOL}" --manifest "${MANIFEST}" query keys
}

get_model_field() {
    python3 "${MODEL_CACHE_TOOL}" --manifest "${MANIFEST}" query field "$1" "$2"
}

get_model_list() {
    get_model_field "$1" "$2"
}

model_keys_for_type() {
    python3 "${MODEL_CACHE_TOOL}" --manifest "${MANIFEST}" query type "$1"
}

get_default_model_key() {
    python3 "${MODEL_CACHE_TOOL}" --manifest "${MANIFEST}" query default "${1:-embedding}"
}

get_default_model() {
    model_key="$(get_default_model_key "${1:-embedding}")"
    get_model_field "${model_key}" name
}

# Shell callers may not mutate the manifest incrementally. Every write must pass
# one lock, one prospective schema validation, and one atomic transaction.
update_manifest_field() {
    echo "ERROR: use the transactional model_cache.py mutation command" >&2
    return 1
}

update_meta_field() {
    echo "ERROR: use the transactional model_cache.py mutation command" >&2
    return 1
}
