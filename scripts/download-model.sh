#!/usr/bin/env bash
set -euo pipefail

# ╔══════════════════════════════════════════════════════════════════════╗
# ║  Download ONNX Models from GitHub Releases                          ║
# ║  Pre-packaged for the-one-mcp / fastembed-rs                        ║
# ╚══════════════════════════════════════════════════════════════════════╝
#
# Usage:
#   bash scripts/download-model.sh                  # download default (BGE-large-en-v1.5)
#   bash scripts/download-model.sh all-MiniLM-L6-v2 # download specific model
#   bash scripts/download-model.sh --all             # download all models
#   bash scripts/download-model.sh --list            # list available models

readonly REPO="michelabboud/the-one-mcp-models-cache"
readonly CACHE_DIR="${FASTEMBED_CACHE_PATH:-${HOME}/.fastembed_cache}"
readonly DEFAULT_MODEL="BGE-large-en-v1.5"

# ── Colors ─────────────────────────────────────────────────────────────
if [ -t 1 ]; then
    GREEN=$'\033[0;32m'
    YELLOW=$'\033[1;33m'
    CYAN=$'\033[0;36m'
    DIM=$'\033[2m'
    BOLD=$'\033[1m'
    NC=$'\033[0m'
else
    GREEN='' YELLOW='' CYAN='' DIM='' BOLD='' NC=''
fi

info()  { echo "${CYAN}[info]${NC} $*"; }
ok()    { echo "${GREEN}[ok]${NC} $*"; }
warn()  { echo "${YELLOW}[warn]${NC} $*"; }

# ── Available models ───────────────────────────────────────────────────
MODELS=(
    "all-MiniLM-L6-v2"
    "all-MiniLM-L12-v2"
    "BGE-small-en-v1.5"
    "BGE-base-en-v1.5"
    "BGE-large-en-v1.5"
    "multilingual-e5-small"
    "multilingual-e5-base"
    "multilingual-e5-large"
    "paraphrase-multilingual-MiniLM-L12-v2"
    "nomic-embed-text-v1"
    "nomic-embed-text-v1.5"
    "mxbai-embed-large-v1"
    "gte-base-en-v1.5"
    "gte-large-en-v1.5"
    "BGE-reranker-base"
    "BGE-reranker-v2-m3"
    "jina-reranker-v1-turbo-en"
    "jina-reranker-v2-base-multilingual"
)

# ── Parse args ─────────────────────────────────────────────────────────
case "${1:-}" in
    --list)
        echo "${BOLD}Available models:${NC}"
        echo ""
        for m in "${MODELS[@]}"; do
            if [ "$m" = "$DEFAULT_MODEL" ]; then
                echo "  ${GREEN}${m}${NC} ${DIM}(default)${NC}"
            else
                echo "  ${m}"
            fi
        done
        echo ""
        echo "${DIM}Download with: bash $0 <model-name>${NC}"
        exit 0
        ;;
    --all)
        targets=("${MODELS[@]}")
        ;;
    --help|-h)
        echo "Usage: $0 [model-name|--all|--list|--help]"
        echo ""
        echo "Downloads ONNX embedding models from GitHub Releases."
        echo "Default model: ${DEFAULT_MODEL}"
        echo "Cache directory: ${CACHE_DIR}"
        exit 0
        ;;
    "")
        targets=("$DEFAULT_MODEL")
        ;;
    *)
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

    info "Downloading ${model}..."

    if command -v gh &>/dev/null; then
        if ! gh release download latest -R "$REPO" -p "$archive" -D "$CACHE_DIR" --clobber 2>/dev/null; then
            warn "Model '${model}' not found in latest release. Check: gh release view latest -R ${REPO}"
            return 1
        fi
    else
        local url
        url=$(curl -sL "https://api.github.com/repos/${REPO}/releases/latest" \
            | grep -o "https://[^\"]*${archive}" | head -1)
        if [ -z "$url" ]; then
            warn "Model '${model}' not found in latest release."
            return 1
        fi
        curl -sL "$url" -o "$tmp_file"
    fi

    info "Extracting to ${CACHE_DIR}..."
    tar -xzf "$tmp_file" -C "$CACHE_DIR"
    rm -f "$tmp_file"
    ok "Installed: ${model} → ${CACHE_DIR}"
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
ok "All models downloaded to ${CACHE_DIR}"
