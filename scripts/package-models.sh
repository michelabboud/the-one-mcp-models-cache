#!/usr/bin/env bash
set -euo pipefail

# ╔══════════════════════════════════════════════════════════════════════╗
# ║  Package ONNX Models for GitHub Release                             ║
# ║  Downloads from Hugging Face, packages as .tar.gz for release       ║
# ╚══════════════════════════════════════════════════════════════════════╝
#
# Usage:
#   bash scripts/package-models.sh                    # package all models
#   bash scripts/package-models.sh BGE-large-en-v1.5  # package one model
#   bash scripts/package-models.sh --release v1.0.0   # package + create release

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUTPUT_DIR="${REPO_ROOT}/dist"
RELEASE_TAG=""
CACHE_DIR="${FASTEMBED_CACHE_PATH:-${HOME}/.fastembed_cache}"

# Parse args
TARGETS=()
for arg in "$@"; do
    case "$arg" in
        --release)
            shift
            RELEASE_TAG="${2:-}"
            shift
            ;;
        --release=*)
            RELEASE_TAG="${arg#*=}"
            ;;
        --help|-h)
            echo "Usage: $0 [model-name...] [--release <tag>]"
            echo ""
            echo "Packages fastembed model cache directories into .tar.gz archives."
            echo "If --release is specified, creates a GitHub release with the archives."
            exit 0
            ;;
        *)
            TARGETS+=("$arg")
            ;;
    esac
done

# ── Colors ─────────────────────────────────────────────────────────────
GREEN=$'\033[0;32m'
CYAN=$'\033[0;36m'
YELLOW=$'\033[1;33m'
NC=$'\033[0m'

info()  { echo "${CYAN}[info]${NC} $*"; }
ok()    { echo "${GREEN}[ok]${NC} $*"; }
warn()  { echo "${YELLOW}[warn]${NC} $*"; }

# ── Model → cache dir mapping ─────────────────────────────────────────
# fastembed uses its own naming convention for cache directories.
# This map translates human model names to fastembed cache dir names.
declare -A MODEL_CACHE_DIRS=(
    ["all-MiniLM-L6-v2"]="fast-all-MiniLM-L6-v2"
    ["all-MiniLM-L12-v2"]="fast-all-MiniLM-L12-v2"
    ["BGE-small-en-v1.5"]="fast-bge-small-en-v1.5"
    ["BGE-base-en-v1.5"]="fast-bge-base-en-v1.5"
    ["BGE-large-en-v1.5"]="fast-bge-large-en-v1.5"
    ["multilingual-e5-small"]="fast-multilingual-e5-small"
    ["multilingual-e5-base"]="fast-multilingual-e5-base"
    ["multilingual-e5-large"]="fast-multilingual-e5-large"
    ["paraphrase-multilingual-MiniLM-L12-v2"]="fast-paraphrase-multilingual-MiniLM-L12-v2"
    ["nomic-embed-text-v1"]="fast-nomic-embed-text-v1"
    ["nomic-embed-text-v1.5"]="fast-nomic-embed-text-v1.5"
    ["mxbai-embed-large-v1"]="fast-mxbai-embed-large-v1"
    ["gte-base-en-v1.5"]="fast-gte-base-en-v1.5"
    ["gte-large-en-v1.5"]="fast-gte-large-en-v1.5"
    ["BGE-reranker-base"]="fast-bge-reranker-base"
    ["BGE-reranker-v2-m3"]="fast-bge-reranker-v2-m3"
    ["jina-reranker-v1-turbo-en"]="fast-jina-reranker-v1-turbo-en"
    ["jina-reranker-v2-base-multilingual"]="fast-jina-reranker-v2-base-multilingual"
)

# Default: all models
if [ ${#TARGETS[@]} -eq 0 ]; then
    TARGETS=("${!MODEL_CACHE_DIRS[@]}")
fi

# ── Package ────────────────────────────────────────────────────────────
mkdir -p "$OUTPUT_DIR"

packaged=()
for model in "${TARGETS[@]}"; do
    cache_name="${MODEL_CACHE_DIRS[$model]:-}"
    if [ -z "$cache_name" ]; then
        warn "Unknown model: ${model}. Skipping."
        continue
    fi

    cache_path="${CACHE_DIR}/${cache_name}"
    if [ ! -d "$cache_path" ]; then
        warn "Cache directory not found: ${cache_path}"
        warn "Run the model at least once to populate the cache, or download from Hugging Face."
        continue
    fi

    archive="${OUTPUT_DIR}/${model}.tar.gz"
    info "Packaging ${model}..."
    tar -czf "$archive" -C "$CACHE_DIR" "$cache_name"
    size=$(du -h "$archive" | cut -f1)
    ok "Created: ${archive} (${size})"
    packaged+=("$archive")
done

if [ ${#packaged[@]} -eq 0 ]; then
    warn "No models were packaged. Make sure the fastembed cache is populated."
    echo "Cache directory: ${CACHE_DIR}"
    echo ""
    echo "To populate, run the-one-mcp with each model at least once:"
    echo "  cargo test -p the-one-memory -- test_fastembed"
    exit 1
fi

echo ""
ok "Packaged ${#packaged[@]} model(s) in ${OUTPUT_DIR}/"

# ── Create release ─────────────────────────────────────────────────────
if [ -n "$RELEASE_TAG" ]; then
    echo ""
    info "Creating GitHub release: ${RELEASE_TAG}"

    if ! command -v gh &>/dev/null; then
        warn "GitHub CLI (gh) required for release creation."
        echo "Install: https://cli.github.com/"
        exit 1
    fi

    gh release create "$RELEASE_TAG" \
        --repo "michelabboud/the-one-mcp-models-cache" \
        --title "Model Cache ${RELEASE_TAG}" \
        --notes "ONNX embedding and reranker models for the-one-mcp.

Packaged from fastembed cache. Extract to ~/.fastembed_cache/

Models: ${#packaged[@]}
$(printf '- %s\n' "${TARGETS[@]}")" \
        "${packaged[@]}"

    ok "Release created: ${RELEASE_TAG}"
fi
