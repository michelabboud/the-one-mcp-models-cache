#!/usr/bin/env bash
set -euo pipefail

# ╔══════════════════════════════════════════════════════════════════════╗
# ║  Download ONNX Models from GitHub Releases                          ║
# ║  Reads models-manifest.toml for the model list and metadata.        ║
# ╚══════════════════════════════════════════════════════════════════════╝
#
# Usage:
#   bash scripts/download-model.sh                        # download default
#   bash scripts/download-model.sh all-MiniLM-L6-v2       # specific model
#   bash scripts/download-model.sh --all                   # all models
#   bash scripts/download-model.sh --list                  # list available
#   bash scripts/download-model.sh --embeddings            # all embedding models
#   bash scripts/download-model.sh --rerankers             # all reranker models

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "${SCRIPT_DIR}/manifest.sh"

readonly CACHE_DIR="${FASTEMBED_CACHE_PATH:-${HOME}/.fastembed_cache}"
readonly REPO=$(get_meta "repo")
readonly RELEASE_TAG=$(get_meta "release_tag")

# ── Colors ─────────────────────────────────────────────────────────────
if [ -t 1 ]; then
    GREEN=$'\033[0;32m'; YELLOW=$'\033[1;33m'; CYAN=$'\033[0;36m'
    DIM=$'\033[2m'; BOLD=$'\033[1m'; NC=$'\033[0m'
else
    GREEN='' YELLOW='' CYAN='' DIM='' BOLD='' NC=''
fi

info()  { echo "${CYAN}[info]${NC} $*"; }
ok()    { echo "${GREEN}[ok]${NC} $*"; }
warn()  { echo "${YELLOW}[warn]${NC} $*"; }

# ── Parse args ─────────────────────────────────────────────────────────
DEFAULT_MODEL=$(get_default_model)
targets=()

case "${1:-}" in
    --list)
        echo "${BOLD}Available models (from models-manifest.toml):${NC}"
        echo ""
        printf "  ${DIM}%-40s %-10s %-6s %-7s %s${NC}\n" "Model" "Type" "Dims" "Size" "License"
        printf "  ${DIM}%-40s %-10s %-6s %-7s %s${NC}\n" "────────────────────────────────────────" "──────────" "──────" "───────" "───────"
        while IFS='|' read -r key name family type hf_repo cache_dir dims size_mb license version sha256 is_default onnx_src; do
            if [ "$is_default" = "1" ]; then
                printf "  ${GREEN}${BOLD}%-40s${NC} %-10s %-6s %-5sMB %s ${GREEN}(default)${NC}\n" "$name" "$type" "$dims" "$size_mb" "$license"
            else
                printf "  %-40s %-10s %-6s %-5sMB %s\n" "$name" "$type" "$dims" "$size_mb" "$license"
            fi
        done < <(parse_manifest)
        echo ""
        echo "${DIM}Download: bash $0 <model-name>${NC}"
        exit 0
        ;;
    --all)
        while IFS= read -r key; do targets+=("$key"); done < <(get_model_keys)
        ;;
    --embeddings)
        while IFS='|' read -r key name family type _rest; do
            [ "$type" = "embedding" ] && targets+=("$key")
        done < <(parse_manifest)
        ;;
    --rerankers)
        while IFS='|' read -r key name family type _rest; do
            [ "$type" = "reranker" ] && targets+=("$key")
        done < <(parse_manifest)
        ;;
    --help|-h)
        echo "Usage: $0 [model-name|--all|--embeddings|--rerankers|--list|--help]"
        echo ""
        echo "Downloads ONNX models from GitHub Releases (${REPO})."
        echo "Model list read from models-manifest.toml."
        echo ""
        echo "Default model: ${DEFAULT_MODEL}"
        echo "Cache dir:     ${CACHE_DIR}"
        echo "Release tag:   ${RELEASE_TAG}"
        exit 0
        ;;
    "")
        targets=("${DEFAULT_MODEL}")
        ;;
    *)
        # Validate model exists in manifest
        if ! get_model_keys | grep -q "^${1}$"; then
            echo "ERROR: Unknown model '${1}'. Run '$0 --list' to see available models."
            exit 1
        fi
        targets=("$1")
        ;;
esac

# ── Check dependencies ────────────────────────────────────────────────
if ! command -v gh &>/dev/null && ! command -v curl &>/dev/null; then
    echo "ERROR: Either 'gh' (GitHub CLI) or 'curl' is required."
    exit 1
fi

# ── Download ───────────────────────────────────────────────────────────
mkdir -p "$CACHE_DIR"

download_model() {
    local model="$1"
    local archive="${model}.tar.gz"
    local tmp_file="${CACHE_DIR}/${archive}"
    local expected_sha256
    expected_sha256=$(get_model_field "$model" 11)

    info "Downloading ${model}..."

    if command -v gh &>/dev/null; then
        if ! gh release download "$RELEASE_TAG" -R "$REPO" -p "$archive" -D "$CACHE_DIR" --clobber 2>/dev/null; then
            warn "Model '${model}' not found in release ${RELEASE_TAG}."
            return 1
        fi
    else
        local url
        url=$(curl -sL "https://api.github.com/repos/${REPO}/releases/tags/${RELEASE_TAG}" \
            | grep -o "https://[^\"]*${archive}" | head -1)
        if [ -z "$url" ]; then
            warn "Model '${model}' not found in release ${RELEASE_TAG}."
            return 1
        fi
        curl -sL "$url" -o "$tmp_file"
    fi

    # Verify checksum if available
    if [ -n "$expected_sha256" ] && command -v sha256sum &>/dev/null; then
        local actual_sha256
        actual_sha256=$(sha256sum "$tmp_file" | cut -d' ' -f1)
        if [ "$actual_sha256" != "$expected_sha256" ]; then
            warn "Checksum mismatch for ${model}!"
            warn "  Expected: ${expected_sha256}"
            warn "  Got:      ${actual_sha256}"
            rm -f "$tmp_file"
            return 1
        fi
    fi

    info "Extracting to ${CACHE_DIR}..."
    tar -xzf "$tmp_file" -C "$CACHE_DIR"
    rm -f "$tmp_file"
    ok "Installed: ${model} -> ${CACHE_DIR}"
}

failed=0
for model in "${targets[@]}"; do
    if ! download_model "$model"; then
        ((failed++))
    fi
done

if [ "$failed" -gt 0 ]; then
    warn "${failed} model(s) failed to download."
    exit 1
fi

echo ""
ok "Done. ${#targets[@]} model(s) downloaded to ${CACHE_DIR}"
