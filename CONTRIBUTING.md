# Contributing

This is a public artifact repository with proprietary repository-original work; public visibility
does not grant a license. Coordinate contributions with the owner before substantial work.

## Development checks

Run from the repository root:

```bash
bash scripts/validate-manifest.sh
python3 -m unittest discover -s tests -v
python3 -m unittest discover -s runtime/tests -v
bash -n scripts/*.sh
shellcheck scripts/*.sh
ruff check scripts tests runtime/tests
ruff format --check scripts tests runtime/tests
basedpyright scripts/install-ort-runtime.py tests runtime/tests
git diff --check
```

Never add model weights, native runtimes, generated archives, credentials, or local caches to git.
Do not publish a release from an unreviewed or partially populated manifest.

Commits use Michel Abboud with `29182417+michelabboud@users.noreply.github.com`. Codex-authored
commits end with `Co-Authored-By: Codex <noreply@openai.com>`. Derive checkpoint and release tags
from the bare value in `VERSION`; never move a published tag.
