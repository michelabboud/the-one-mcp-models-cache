# FastEmbed 6 and ORT Cache Handoff

## Repository state

`main` began at `7ba0093`. The governance baseline is version 6.0.1. FastEmbed 6.0.2 model-cache
and ORT rc13 runtime changes remain working-tree changes until their reviews and verification pass.

## Verified done

- The public repository and historical `fastembed-v4` release were inspected.
- The active plan and repository baseline were documented.
- The One already pins FastEmbed 6.0.2; the cache repository upgrade is the remaining artifact lane.

## In progress

- Independent cache specification/provenance and security reviews.
- Repairs for archive TOCTOU, declared-file-only packaging, safe path grammar, transactional cache
  publication, and historical provenance handling.
- Independent final Rust review and clean full gate in `the-one-mcp`.

## Next steps

1. Close every reproduced review finding with a focused regression.
2. Run the full local cache gate and review the final diff.
3. Bump to 6.0.2, update all status documents, commit, tag `checkpoint/6.0.2`, and push.
4. Obtain and verify all missing large assets before any `v6.0.2` release is created.

## Boundaries

No user, project, or MAI database may be accessed. Large cache/runtime artifacts stay outside git.
No partial release is authorized.
