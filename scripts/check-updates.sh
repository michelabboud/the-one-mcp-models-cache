#!/usr/bin/env bash
set -euo pipefail

# ╔══════════════════════════════════════════════════════════════════════╗
# ║  Check for Model Updates on Hugging Face                            ║
# ║  Reads models-manifest.toml, queries HF API, reports changes.      ║
# ║  With --apply, updates version fields in the manifest.              ║
# ╚══════════════════════════════════════════════════════════════════════╝
#
# Usage:
#   bash scripts/check-updates.sh               # check only (dry run)
#   bash scripts/check-updates.sh --apply        # update manifest versions
#   bash scripts/check-updates.sh --apply --pr   # update + open PR

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "${SCRIPT_DIR}/manifest.sh"

APPLY=false
OPEN_PR=false

for arg in "$@"; do
    case "$arg" in
        --apply) APPLY=true ;;
        --pr)    APPLY=true; OPEN_PR=true ;;
        --help|-h)
            echo "Usage: $0 [--apply] [--pr]"
            echo ""
            echo "Checks Hugging Face for updated models. Compares last_modified"
            echo "dates against the version field in models-manifest.toml."
            echo ""
            echo "  --apply  Update version fields in manifest"
            echo "  --pr     Apply + commit + open a GitHub PR"
            exit 0
            ;;
    esac
done

# ── Colors ─────────────────────────────────────────────────────────────
if [ -t 1 ]; then
    GREEN=$'\033[0;32m'; YELLOW=$'\033[1;33m'; CYAN=$'\033[0;36m'
    RED=$'\033[0;31m'; DIM=$'\033[2m'; BOLD=$'\033[1m'; NC=$'\033[0m'
else
    GREEN='' YELLOW='' CYAN='' RED='' DIM='' BOLD='' NC=''
fi

info()  { echo "${CYAN}[info]${NC} $*"; }
ok()    { echo "${GREEN}[ok]${NC} $*"; }
warn()  { echo "${YELLOW}[warn]${NC} $*"; }

echo "${BOLD}=== Model Update Check ===${NC}"
echo ""
echo "Manifest:     ${MANIFEST}"
echo "Last checked: $(get_meta 'last_checked')"
echo ""

# ── Query Hugging Face API ─────────────────────────────────────────────
updated=()
unchanged=()
errors=()

check_model() {
    local key="$1" hf_repo="$2" current_version="$3"

    # Query HF API for last modified date
    local api_url="https://huggingface.co/api/models/${hf_repo}"
    local response
    response=$(curl -sL "$api_url" 2>/dev/null || echo "")

    if [ -z "$response" ] || echo "$response" | grep -q '"error"'; then
        errors+=("$key")
        printf "  ${RED}%-45s ERROR${NC} (could not reach HF API)\n" "$key"
        return
    fi

    # Extract lastModified date (YYYY-MM format for comparison)
    local hf_modified
    hf_modified=$(echo "$response" | python3 -c "
import json, sys
data = json.load(sys.stdin)
modified = data.get('lastModified', '')
# Format: 2024-03-15T10:30:00.000Z -> 2024-03
if modified:
    print(modified[:7])
else:
    print('unknown')
" 2>/dev/null || echo "unknown")

    if [ "$hf_modified" = "unknown" ]; then
        errors+=("$key")
        printf "  ${DIM}%-45s${NC} ${DIM}unknown${NC}\n" "$key"
        return
    fi

    if [ "$hf_modified" != "$current_version" ]; then
        updated+=("${key}|${current_version}|${hf_modified}")
        printf "  ${BOLD}%-45s${NC} ${YELLOW}${current_version} -> ${hf_modified}${NC}\n" "$key"
    else
        unchanged+=("$key")
        printf "  ${DIM}%-45s${NC} ${GREEN}${current_version} (current)${NC}\n" "$key"
    fi
}

# Check each model
info "Querying Hugging Face API..."
echo ""

while IFS='|' read -r key name family type hf_repo cache_dir dims size_mb license version sha256 is_default onnx_src; do
    check_model "$key" "$hf_repo" "$version"
    # Rate limit: don't hammer HF API
    sleep 0.3
done < <(parse_manifest)

# ── Summary ───────────────────────────────────────────────────────────
echo ""
echo "${BOLD}=== Summary ===${NC}"
echo "  Updated:    ${#updated[@]}"
echo "  Unchanged:  ${#unchanged[@]}"
echo "  Errors:     ${#errors[@]}"

if [ ${#updated[@]} -eq 0 ]; then
    echo ""
    ok "All models are up to date."

    # Update last_checked timestamp
    if [ "$APPLY" = true ]; then
        update_meta_field "last_checked" "$(date +%Y-%m-%d)"
        ok "Updated last_checked in manifest."
    fi
    exit 0
fi

echo ""
echo "${BOLD}Models with updates:${NC}"
for entry in "${updated[@]}"; do
    IFS='|' read -r key old_ver new_ver <<< "$entry"
    echo "  ${key}: ${old_ver} -> ${new_ver}"
done

# ── Apply ─────────────────────────────────────────────────────────────
if [ "$APPLY" = false ]; then
    echo ""
    warn "Dry run. Use --apply to update the manifest."
    exit 0
fi

echo ""
info "Updating models-manifest.toml..."

for entry in "${updated[@]}"; do
    IFS='|' read -r key old_ver new_ver <<< "$entry"
    update_manifest_field "$key" "version" "$new_ver"
    # Clear sha256 since the model changed — forces re-download on next sync
    update_manifest_field "$key" "sha256" ""
    ok "Updated ${key}: version=${new_ver}, sha256 cleared"
done

update_meta_field "last_checked" "$(date +%Y-%m-%d)"
ok "Updated last_checked."

# ── PR ────────────────────────────────────────────────────────────────
if [ "$OPEN_PR" = true ]; then
    if ! command -v gh &>/dev/null; then
        warn "GitHub CLI (gh) required for PR creation."
        exit 1
    fi

    branch="chore/model-updates-$(date +%Y%m%d)"
    cd "$REPO_ROOT"
    git checkout -b "$branch"
    git add models-manifest.toml
    git commit -m "chore: update model versions from Hugging Face

Updated models:
$(for entry in "${updated[@]}"; do
    IFS='|' read -r key old_ver new_ver <<< "$entry"
    echo "- ${key}: ${old_ver} -> ${new_ver}"
done)"
    git push -u origin "$branch"
    gh pr create \
        --title "chore: update model versions ($(date +%Y-%m-%d))" \
        --body "Auto-generated by \`scripts/check-updates.sh --apply --pr\`

## Updated Models

$(for entry in "${updated[@]}"; do
    IFS='|' read -r key old_ver new_ver <<< "$entry"
    echo "- **${key}**: \`${old_ver}\` -> \`${new_ver}\`"
done)

## Next Steps

1. Review the changes
2. Run \`bash scripts/sync-release.sh --upload\` to re-package and upload updated models
3. Merge this PR"
    ok "PR created."
fi
