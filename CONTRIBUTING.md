# Contributing

This is a public artifact repository with proprietary repository-original work; public visibility
does not grant a license. Coordinate contributions with the owner before substantial work.

## Development checks

Use Python 3.11 or newer plus Bash, ShellCheck, Ruff, and basedpyright. The prior recorded
toolchain run used Python 3.12.3, ShellCheck 0.9.0, Ruff 0.15.18, and basedpyright 1.39.8 (Pyright
1.1.410). The 2026-09-10 direct reviewed-artifact scanner repair passed the no-external/no-Git
local gate with 162 central and 47 runtime tests; its Git diff check remains for the root lane. This
is repair evidence rather than independent candidate acceptance. Install these tools through your
platform's normal isolated package/tool manager; do not vendor their caches or environments into
this repository.

Run from the repository root:

```bash
bash scripts/validate-manifest.sh
python3 -m unittest discover -s tests -v
python3 -m unittest discover -s runtime/tests -v
bash -n scripts/*.sh
shellcheck scripts/*.sh
ruff check --no-cache scripts tests runtime/tests
ruff format --check --no-cache scripts tests runtime/tests
basedpyright
git diff --check
```

`pyrightconfig.json` defines the checked production scripts and regression-test directories. It
uses standard type checking, keeps implicit string concatenation as an error, and disables only
unused-call-result diagnostics because command builders, filesystem setup, and `unittest`
assertions intentionally discard many successful return values.

Never add model weights, native runtimes, generated archives, credentials, or local caches to git.
Do not publish a release from an unreviewed or partially populated manifest.

Commits use Michel Abboud with `29182417+michelabboud@users.noreply.github.com`. Codex-authored
commits end with `Co-Authored-By: Codex <noreply@openai.com>`. Derive checkpoint and release tags
from the bare value in `VERSION`; never move a published tag.
