#!/usr/bin/env bash
set -euo pipefail

# ╔══════════════════════════════════════════════════════════════════════╗
# ║  Sync Local Cache to GitHub Release                                 ║
# ║  Reads models-manifest.toml, compares with local cache, uploads.   ║
# ╚══════════════════════════════════════════════════════════════════════╝
#
# Usage:
#   bash scripts/sync-release.sh                # dry run
#   bash scripts/sync-release.sh --upload       # upload new/changed
#   bash scripts/sync-release.sh --force        # re-upload all
#   bash scripts/sync-release.sh --model X      # sync only model X

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "${SCRIPT_DIR}/manifest.sh"

# fastembed creates .fastembed_cache relative to CWD. Check common locations.
find_cache_dir() {
    if [ -n "${FASTEMBED_CACHE_PATH:-}" ] && [ -d "$FASTEMBED_CACHE_PATH" ]; then
        echo "$FASTEMBED_CACHE_PATH"
        return
    fi
    # Check common locations
    for candidate in \
        "${HOME}/.fastembed_cache" \
        "${HOME}/.cache/fastembed" \
        ".fastembed_cache"; do
        if [ -d "$candidate" ]; then
            echo "$candidate"
            return
        fi
    done
    # Search the-one-mcp crate dirs (fastembed creates cache relative to CWD during tests)
    local the_one_root="${THE_ONE_PROJECT_ROOT:-}"
    if [ -z "$the_one_root" ]; then
        # Try to find it
        for d in "${HOME}/projects/the-one-mcp" "$(pwd)"; do
            if [ -d "$d/crates" ]; then
                the_one_root="$d"
                break
            fi
        done
    fi
    if [ -n "$the_one_root" ]; then
        for crate_cache in "$the_one_root"/crates/*/.fastembed_cache; do
            if [ -d "$crate_cache" ]; then
                echo "$crate_cache"
                return
            fi
        done
    fi
    echo ""
}

CACHE_DIR=$(find_cache_dir)
readonly DIST_DIR="${REPO_ROOT}/dist"
readonly REPO=$(get_meta "repo")
readonly RELEASE_TAG=$(get_meta "release_tag")

UPLOAD=false
FORCE=false
SINGLE_MODEL=""

for arg in "$@"; do
    case "$arg" in
        --upload)  UPLOAD=true ;;
        --force)   FORCE=true; UPLOAD=true ;;
        --help|-h)
            echo "Usage: $0 [--upload] [--force] [--model <name>]"
            echo ""
            echo "Compares local fastembed cache against models-manifest.toml,"
            echo "packages changed models, and uploads to GitHub Release."
            exit 0
            ;;
    esac
done

# Handle --model (needs next arg)
while [[ $# -gt 0 ]]; do
    case "$1" in
        --model) SINGLE_MODEL="${2:-}"; shift 2 ;;
        --model=*) SINGLE_MODEL="${1#*=}"; shift ;;
        *) shift ;;
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

# ── Preflight ──────────────────────────────────────────────────────────
if ! command -v gh &>/dev/null; then
    echo "ERROR: GitHub CLI (gh) is required."
    exit 1
fi

if [ -z "$CACHE_DIR" ] || [ ! -d "$CACHE_DIR" ]; then
    echo "ERROR: fastembed cache not found."
    echo "Set FASTEMBED_CACHE_PATH or run models first to populate the cache."
    echo "Searched: ~/.fastembed_cache, ~/.cache/fastembed, the-one-mcp crate dirs"
    exit 1
fi

# Also collect all cache dirs (models may be spread across crate dirs)
ALL_CACHE_DIRS=("$CACHE_DIR")
the_one_root="${THE_ONE_PROJECT_ROOT:-${HOME}/projects/the-one-mcp}"
if [ -d "$the_one_root/crates" ]; then
    for d in "$the_one_root"/crates/*/.fastembed_cache; do
        [ -d "$d" ] && [[ ! " ${ALL_CACHE_DIRS[*]} " =~ " $d " ]] && ALL_CACHE_DIRS+=("$d")
    done
fi

# Find a model's cache path across all cache dirs
find_model_cache() {
    local cache_dir_name="$1"
    for d in "${ALL_CACHE_DIRS[@]}"; do
        if [ -d "${d}/${cache_dir_name}" ]; then
            echo "${d}/${cache_dir_name}"
            return
        fi
    done
    echo ""
}

echo "${BOLD}=== Model Cache Sync ===${NC}"
echo ""
echo "Manifest:    ${MANIFEST}"
echo "Cache dir:   ${CACHE_DIR}"
echo "Release:     ${RELEASE_TAG}"
echo "Mode:        $([ "$UPLOAD" = true ] && echo "UPLOAD" || echo "DRY RUN")"
echo ""

# ── Get existing release assets ───────────────────────────────────────
existing_assets=""
release_exists=false
if gh release view "$RELEASE_TAG" -R "$REPO" &>/dev/null; then
    release_exists=true
    existing_assets=$(gh release view "$RELEASE_TAG" -R "$REPO" --json assets -q '.assets[].name' 2>/dev/null || echo "")
fi

# ── Scan manifest and compare ─────────────────────────────────────────
mkdir -p "$DIST_DIR"

to_upload=()
to_skip=()
not_cached=()

while IFS='|' read -r key name family type hf_repo cache_dir dims size_mb license version sha256 is_default onnx_src; do
    # Filter to single model if specified
    if [ -n "$SINGLE_MODEL" ] && [ "$key" != "$SINGLE_MODEL" ]; then
        continue
    fi

    cache_path=$(find_model_cache "$cache_dir")
    archive_name="${key}.tar.gz"
    archive_path="${DIST_DIR}/${archive_name}"

    if [ -z "$cache_path" ] || [ ! -d "$cache_path" ]; then
        not_cached+=("$key")
        printf "  ${DIM}%-45s not in cache${NC}\n" "$key"
        continue
    fi

    # Compute local checksum
    parent_dir=$(dirname "$cache_path")
    dir_name=$(basename "$cache_path")
    local_sha256=$(tar -czf - -C "$parent_dir" "$dir_name" 2>/dev/null | sha256sum | cut -d' ' -f1)

    # Compare with manifest sha256
    if [ "$FORCE" = false ] && [ -n "$sha256" ] && [ "$local_sha256" = "$sha256" ] \
       && echo "$existing_assets" | grep -q "^${archive_name}$"; then
        to_skip+=("$key")
        printf "  ${DIM}%-45s${NC} ${GREEN}up to date${NC}\n" "$key"
        continue
    fi

    # Package
    tar -czf "$archive_path" -C "$parent_dir" "$dir_name"
    actual_size=$(du -h "$archive_path" | cut -f1)

    if echo "$existing_assets" | grep -q "^${archive_name}$"; then
        printf "  ${BOLD}%-45s${NC} ${YELLOW}updated${NC} (${actual_size})\n" "$key"
    else
        printf "  ${BOLD}%-45s${NC} ${GREEN}new${NC} (${actual_size})\n" "$key"
    fi

    # Update sha256 in manifest
    update_manifest_field "$key" "sha256" "$local_sha256"

    to_upload+=("$key")

done < <(parse_manifest)

# ── Summary ───────────────────────────────────────────────────────────
echo ""
echo "${BOLD}=== Summary ===${NC}"
echo "  To upload:    ${#to_upload[@]}"
echo "  Up to date:   ${#to_skip[@]}"
echo "  Not in cache: ${#not_cached[@]}"

if [ ${#to_upload[@]} -eq 0 ]; then
    echo ""
    ok "Nothing to upload."
    exit 0
fi

if [ "$UPLOAD" = false ]; then
    echo ""
    warn "Dry run. Use --upload to push to GitHub."
    exit 0
fi

# ── Upload ────────────────────────────────────────────────────────────
echo ""
info "Uploading to release ${RELEASE_TAG}..."

if [ "$release_exists" = false ]; then
    gh release create "$RELEASE_TAG" \
        -R "$REPO" \
        --title "Model Cache (${RELEASE_TAG})" \
        --notes "ONNX embedding and reranker models for the-one-mcp.
Extract archives to ~/.fastembed_cache/
See README for details."
    ok "Release created."
fi

for model in "${to_upload[@]}"; do
    archive_name="${model}.tar.gz"
    archive_path="${DIST_DIR}/${archive_name}"

    if echo "$existing_assets" | grep -q "^${archive_name}$"; then
        gh release delete-asset "$RELEASE_TAG" "$archive_name" -R "$REPO" -y 2>/dev/null || true
    fi

    gh release upload "$RELEASE_TAG" "$archive_path" -R "$REPO" --clobber
    ok "Uploaded: ${archive_name}"
done

# Commit updated manifest (sha256 fields changed)
if git -C "$REPO_ROOT" diff --quiet models-manifest.toml 2>/dev/null; then
    : # no changes
else
    git -C "$REPO_ROOT" add models-manifest.toml
    git -C "$REPO_ROOT" commit -m "chore: update sha256 checksums after sync"
    git -C "$REPO_ROOT" push origin main
    ok "Manifest checksums committed."
fi

echo ""
ok "Sync complete. ${#to_upload[@]} model(s) uploaded."
