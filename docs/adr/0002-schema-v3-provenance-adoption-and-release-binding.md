# ADR 0002: Use schema v3 six-map provenance, explicit adoption, and immutable release binding

**Status:** Accepted — 2026-09-08

## Context

A repository commit alone cannot prove the bytes of every required upstream file. Nor can an
observed current Hugging Face revision establish the immutable revision embedded in a historical
archive. The repository needs to compare current upstream observations without silently replacing
an accepted baseline, and must prevent a correct payload set from being associated with an
alternate manifest or source commit.

## Decision

Schema v3 records six per-file provenance maps: accepted `upstream_file_sha256`,
`upstream_lfs_sha256`, and `upstream_git_blob_oid`; plus candidate
`current_remote_file_sha256`, `current_remote_lfs_sha256`, and
`current_remote_git_blob_oid`. File SHA-256 covers every required file, LFS SHA-256 records LFS
objects, and Git blob OIDs cover non-LFS files. Prepared archive `file_sha256` remains separate
archive evidence and cannot substitute for source provenance.

`check-updates.sh --apply` may record a complete candidate but never adopts it. An operator must
review one candidate and invoke the explicit offline `--adopt-current` transition before it
becomes the accepted baseline. Preparation requires complete, matching accepted and candidate
maps after adoption.

Publication binds immutable source and release identity together: `VERSION`, the canonical model
and runtime manifest bytes and their exact `HEAD` blobs, a clean local `main` tracking
`origin/main`, the full pushed `HEAD`, and the unchanged immutable draft-tag target must all
identify the same commit before upload and again after remote digest verification.

## Alternatives rejected

- **One revision or one archive hash as sufficient evidence:** rejected because neither binds each
  required upstream file and its LFS/non-LFS identity.
- **Automatically adopt an observed upstream candidate:** rejected because observation is not
  review and can silently replace historical source authority.
- **Bind only the release tag or only a clean release-critical subset:** rejected because a stale
  manifest, dirty untracked file, abbreviated SHA, or different pushed commit could otherwise be
  presented as the reviewed release.

## Consequences

Historical `provenance-required` records stay blocked until their embedded revisions are
recovered; current remote data cannot backfill them. Archive-ready state is invalidated when a
complete current audit discovers changed provenance, and a reviewed adoption is required before a
refresh. Release verification remains fail closed until all source and release bindings agree.
