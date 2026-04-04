#!/usr/bin/env bash
set -euo pipefail

# ╔══════════════════════════════════════════════════════════════════════╗
# ║  Sync Models to GitHub Release                                      ║
# ║                                                                      ║
# ║  Compares local fastembed cache against the GitHub Release,          ║
# ║  packages new/updated models, and uploads them as release assets.   ║
# ║                                                                      ║
# ║  Strategy: ONE release per fastembed major version (e.g. fastembed-  ║
# ║  v4). Assets are added/replaced individually — no need to recreate  ║
# ║  the release from scratch.                                           ║
# ╚══════════════════════════════════════════════════════════════════════╝
#
# Usage:
#   bash scripts/sync-release.sh                # dry run — show what would change
#   bash scripts/sync-release.sh --upload       # actually upload to release
#   bash scripts/sync-release.sh --force        # re-upload all (even if unchanged)
#   bash scripts/sync-release.sh --model X      # sync only model X

readonly REPO="michelabboud/the-one-mcp-models-cache"
readonly REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
readonly CACHE_DIR="${FASTEMBED_CACHE_PATH:-${HOME}/.fastembed_cache}"
readonly DIST_DIR="${REPO_ROOT}/dist"
readonly RELEASE_TAG="fastembed-v4"

UPLOAD=false
FORCE=false
SINGLE_MODEL=""

for arg in "$@"; do
    case "$arg" in
        --upload)  UPLOAD=true ;;
        --force)   FORCE=true; UPLOAD=true ;;
        --model)   shift; SINGLE_MODEL="${2:-}"; shift ;;
        --model=*) SINGLE_MODEL="${arg#*=}" ;;
        --help|-h)
            echo "Usage: $0 [--upload] [--force] [--model <name>]"
            echo ""
            echo "Flags:"
            echo "  --upload   Actually upload to GitHub Release (default: dry run)"
            echo "  --force    Re-upload all models even if checksums match"
            echo "  --model X  Only process model X"
            echo ""
            echo "Environment:"
            echo "  FASTEMBED_CACHE_PATH  Override cache dir (default: ~/.fastembed_cache)"
            exit 0
            ;;
    esac
done

# ── Colors ─────────────────────────────────────────────────────────────
if [ -t 1 ]; then
    GREEN=$'\033[0;32m'; RED=$'\033[0;31m'; YELLOW=$'\033[1;33m'
    CYAN=$'\033[0;36m'; DIM=$'\033[2m'; BOLD=$'\033[1m'; NC=$'\033[0m'
else
    GREEN='' RED='' YELLOW='' CYAN='' DIM='' BOLD='' NC=''
fi

info()  { echo "${CYAN}[info]${NC} $*"; }
ok()    { echo "${GREEN}[ok]${NC} $*"; }
warn()  { echo "${YELLOW}[warn]${NC} $*"; }
skip()  { echo "${DIM}[skip]${NC} $*"; }

# ── Model → cache dir mapping ─────────────────────────────────────────
# fastembed uses "fast-<model-name>" as the cache directory name.
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

# ── Preflight checks ──────────────────────────────────────────────────
if ! command -v gh &>/dev/null; then
    echo "ERROR: GitHub CLI (gh) is required. Install: https://cli.github.com/"
    exit 1
fi

if [ ! -d "$CACHE_DIR" ]; then
    echo "ERROR: fastembed cache not found at ${CACHE_DIR}"
    echo "Run models first, or set FASTEMBED_CACHE_PATH."
    exit 1
fi

# ── Step 1: Scan local cache ──────────────────────────────────────────
echo "${BOLD}═══ Model Cache Sync ═══${NC}"
echo ""
echo "Cache dir:     ${CACHE_DIR}"
echo "Release tag:   ${RELEASE_TAG}"
echo "Mode:          $([ "$UPLOAD" = true ] && echo "UPLOAD" || echo "DRY RUN")"
echo ""

# Which models to process
if [ -n "$SINGLE_MODEL" ]; then
    if [ -z "${MODEL_CACHE_DIRS[$SINGLE_MODEL]:-}" ]; then
        echo "ERROR: Unknown model '${SINGLE_MODEL}'"
        echo "Available: ${!MODEL_CACHE_DIRS[*]}"
        exit 1
    fi
    targets=("$SINGLE_MODEL")
else
    targets=("${!MODEL_CACHE_DIRS[@]}")
fi

# ── Step 2: Get existing release assets ───────────────────────────────
info "Checking existing release assets..."

existing_assets=""
release_exists=false
if gh release view "$RELEASE_TAG" -R "$REPO" &>/dev/null; then
    release_exists=true
    existing_assets=$(gh release view "$RELEASE_TAG" -R "$REPO" --json assets -q '.assets[].name' 2>/dev/null || echo "")
    asset_count=$(echo "$existing_assets" | grep -c '.' 2>/dev/null || echo "0")
    ok "Release ${RELEASE_TAG} exists with ${asset_count} asset(s)"
else
    warn "Release ${RELEASE_TAG} does not exist yet. Will create on upload."
fi

# ── Step 3: Compare and build upload list ─────────────────────────────
echo ""
info "Scanning local cache..."
echo ""

mkdir -p "$DIST_DIR"

to_upload=()
to_skip=()
not_cached=()

# Checksum file for tracking what we've uploaded
checksum_file="${REPO_ROOT}/.checksums"
touch "$checksum_file"

for model in $(printf '%s\n' "${targets[@]}" | sort); do
    cache_name="${MODEL_CACHE_DIRS[$model]}"
    cache_path="${CACHE_DIR}/${cache_name}"
    archive_name="${model}.tar.gz"
    archive_path="${DIST_DIR}/${archive_name}"

    # Check if model is in local cache
    if [ ! -d "$cache_path" ]; then
        not_cached+=("$model")
        printf "  ${DIM}%-45s${NC} ${DIM}not in cache${NC}\n" "$model"
        continue
    fi

    # Compute checksum of the model directory (based on file sizes + names)
    local_checksum=$(find "$cache_path" -type f -exec stat --printf='%s %n\n' {} \; 2>/dev/null \
        | sort | sha256sum | cut -d' ' -f1)

    # Check if we've already uploaded this exact version
    prev_checksum=$(grep "^${model}=" "$checksum_file" 2>/dev/null | cut -d'=' -f2 || echo "")

    if [ "$FORCE" = false ] && [ "$local_checksum" = "$prev_checksum" ] && echo "$existing_assets" | grep -q "^${archive_name}$"; then
        to_skip+=("$model")
        printf "  ${DIM}%-45s${NC} ${GREEN}up to date${NC}\n" "$model"
        continue
    fi

    # Package it
    info "Packaging ${model}..."
    tar -czf "$archive_path" -C "$CACHE_DIR" "$cache_name"
    size=$(du -h "$archive_path" | cut -f1)

    if echo "$existing_assets" | grep -q "^${archive_name}$"; then
        printf "  ${BOLD}%-45s${NC} ${YELLOW}updated${NC} (${size})\n" "$model"
    else
        printf "  ${BOLD}%-45s${NC} ${GREEN}new${NC} (${size})\n" "$model"
    fi

    to_upload+=("$model")

    # Store checksum for next run
    sed -i "/^${model}=/d" "$checksum_file" 2>/dev/null || true
    echo "${model}=${local_checksum}" >> "$checksum_file"
done

# ── Step 4: Summary ───────────────────────────────────────────────────
echo ""
echo "${BOLD}═══ Summary ═══${NC}"
echo "  To upload:    ${#to_upload[@]}"
echo "  Up to date:   ${#to_skip[@]}"
echo "  Not in cache: ${#not_cached[@]}"

if [ ${#not_cached[@]} -gt 0 ]; then
    echo ""
    echo "${DIM}Models not in cache (run them first to download):${NC}"
    for m in "${not_cached[@]}"; do
        echo "  ${DIM}- ${m}${NC}"
    done
fi

# ── Step 5: Upload ────────────────────────────────────────────────────
if [ ${#to_upload[@]} -eq 0 ]; then
    echo ""
    ok "Nothing to upload. All models are up to date."
    exit 0
fi

if [ "$UPLOAD" = false ]; then
    echo ""
    warn "Dry run — no changes made. Use --upload to push to GitHub."
    exit 0
fi

echo ""
info "Uploading to release ${RELEASE_TAG}..."

# Create release if it doesn't exist
if [ "$release_exists" = false ]; then
    info "Creating release ${RELEASE_TAG}..."
    gh release create "$RELEASE_TAG" \
        -R "$REPO" \
        --title "Model Cache (${RELEASE_TAG})" \
        --notes "ONNX embedding and reranker models for the-one-mcp.

Extract archives to ~/.fastembed_cache/

Download script:
\`\`\`bash
bash scripts/download-model.sh           # default model (BGE-large-en-v1.5)
bash scripts/download-model.sh --all     # all models
\`\`\`

See [README](https://github.com/${REPO}) for details."
    ok "Release created."
fi

# Upload each model (delete existing asset first if replacing)
for model in "${to_upload[@]}"; do
    archive_name="${model}.tar.gz"
    archive_path="${DIST_DIR}/${archive_name}"

    # Delete existing asset if present (gh doesn't support overwrite)
    if echo "$existing_assets" | grep -q "^${archive_name}$"; then
        info "Replacing ${archive_name}..."
        gh release delete-asset "$RELEASE_TAG" "$archive_name" -R "$REPO" -y 2>/dev/null || true
    fi

    gh release upload "$RELEASE_TAG" "$archive_path" -R "$REPO" --clobber
    ok "Uploaded: ${archive_name}"
done

echo ""
ok "Sync complete. ${#to_upload[@]} model(s) uploaded to ${RELEASE_TAG}."
echo "  View: https://github.com/${REPO}/releases/tag/${RELEASE_TAG}"
