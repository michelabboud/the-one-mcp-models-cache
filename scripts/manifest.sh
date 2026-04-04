#!/usr/bin/env bash
# ── Shared manifest parser ─────────────────────────────────────────────
# Sourced by other scripts. Reads models-manifest.toml into bash arrays.
# Requires: python3 (for TOML parsing — bash can't do nested TOML well)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
MANIFEST="${REPO_ROOT}/models-manifest.toml"

if [ ! -f "$MANIFEST" ]; then
    echo "ERROR: models-manifest.toml not found at ${MANIFEST}"
    exit 1
fi

if ! command -v python3 &>/dev/null; then
    echo "ERROR: python3 is required for TOML parsing."
    exit 1
fi

# ── Parse manifest into shell variables ────────────────────────────────
# Outputs one line per model: key|family|type|hf_repo|cache_dir|dims|size_mb|license|version|sha256|default|onnx_source
parse_manifest() {
    python3 -c "
import sys
try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib
    except ImportError:
        # Fallback: pip install tomli or use Python 3.11+
        print('ERROR: Python 3.11+ or tomli package required', file=sys.stderr)
        sys.exit(1)

with open('${MANIFEST}', 'rb') as f:
    data = tomllib.load(f)

for key, m in data.get('models', {}).items():
    fields = [
        key,
        m.get('family', ''),
        m.get('type', ''),
        m.get('huggingface_repo', ''),
        m.get('fastembed_cache_dir', ''),
        str(m.get('dims', 0)),
        str(m.get('size_mb', 0)),
        m.get('license', ''),
        m.get('version', ''),
        m.get('sha256', ''),
        '1' if m.get('default', False) else '0',
        m.get('onnx_source', ''),
    ]
    print('|'.join(fields))
"
}

# Get meta fields
get_meta() {
    local field="$1"
    python3 -c "
import sys
try:
    import tomllib
except ImportError:
    import tomli as tomllib

with open('${MANIFEST}', 'rb') as f:
    data = tomllib.load(f)
print(data.get('meta', {}).get('${field}', ''))
"
}

# Update a model field in the manifest
update_manifest_field() {
    local model_key="$1" field="$2" value="$3"
    python3 -c "
import re

with open('${MANIFEST}', 'r') as f:
    content = f.read()

# Find the model section and update the field
in_section = False
lines = content.split('\n')
result = []
for line in lines:
    if line.strip() == '[models.${model_key}]':
        in_section = True
    elif line.strip().startswith('[') and in_section:
        in_section = False
    if in_section and line.strip().startswith('${field} ='):
        line = '${field} = \"${value}\"'
    result.append(line)

with open('${MANIFEST}', 'w') as f:
    f.write('\n'.join(result))
"
}

# Update meta field
update_meta_field() {
    local field="$1" value="$2"
    python3 -c "
with open('${MANIFEST}', 'r') as f:
    content = f.read()

import re
lines = content.split('\n')
in_meta = False
result = []
for line in lines:
    if line.strip() == '[meta]':
        in_meta = True
    elif line.strip().startswith('[') and in_meta:
        in_meta = False
    if in_meta and line.strip().startswith('${field} ='):
        line = '${field} = \"${value}\"'
    result.append(line)

with open('${MANIFEST}', 'w') as f:
    f.write('\n'.join(result))
"
}

# ── Convenience: get all model keys ────────────────────────────────────
get_model_keys() {
    parse_manifest | cut -d'|' -f1
}

# Get a specific model field (key, field_index)
# Fields: 1=key 2=family 3=type 4=hf_repo 5=cache_dir 6=dims 7=size_mb 8=license 9=version 10=sha256 11=default 12=onnx_source
get_model_field() {
    local key="$1" field_num="$2"
    parse_manifest | grep "^${key}|" | cut -d'|' -f"$field_num"
}

# Get the default model key
get_default_model() {
    parse_manifest | grep '|1|' | head -1 | cut -d'|' -f1
}
