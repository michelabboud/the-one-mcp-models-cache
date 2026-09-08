# Changelog

All notable changes to the repository metadata and tooling are recorded here.
Third-party model and runtime versions are recorded separately in their manifests.

## [Unreleased]

### Changed

- Added governance entrypoints and append-only ADRs documenting release assets rather than Git
  blobs, schema-v3 six-map provenance with explicit adoption and immutable release binding, and
  fail-closed transactional platform qualification. These records do not accept the source
  candidate or create a release.
- Migrated the model inventory to fail-closed schema v3 for FastEmbed 6.0.2, with separate
  original-model and conversion/cache provenance, per-variant dimensions, candidate remote LFS
  hashes, strict statuses, and an exact 39-model registry fixture.
- Defined one exact tooling-validated binary payload set of 43 assets: 39 model archives and four
  required target-specific ONNX Runtime archives. This count does not by itself define the final
  publishable-release inventory.
- Tightened release verification to `VERSION`, the exact configured origin, the checked-out local
  branch named `main` and tracking exactly `refs/remotes/origin/main`, a clean whole working tree
  including untracked files, a full 40-character `HEAD` equal to pushed `origin/main`, and the
  unchanged immutable draft-tag target.
- Preserved the baseline GTE tag, recorded version, declared MiB size, and SHA-256 in distinct
  non-installable `legacy_archive_*` fields while leaving all current v6 provenance/archive fields
  empty and `refresh-required`.
- Made the absence of a current upstream audit explicit: `last_upstream_check` is empty, while the
  baseline's 2026-04-04 value survives only as `legacy_manifest_last_checked`.
- Added six independent required-file provenance maps: accepted/candidate file SHA-256, LFS
  SHA-256, and non-LFS Git blob OID maps. Archive payload hashes do not substitute for upstream
  source evidence.
- Required the six maps to be complete and to describe the same reviewed candidate before
  preparation; candidate recording remains separate from deliberate baseline adoption.
- Recorded that `rozgo/bge-reranker-v2-m3` declares no cache-repository license metadata. Its
  conversion license is `NOASSERTION` and redistribution stays blocked; the original BAAI model's
  official Apache-2.0 declaration applies only to the source model.
- Added a **High release blocker** requiring exact per-model cache/original license, copyright,
  and notice recovery/audit plus ONNX Runtime 1.28.0 `ThirdPartyNotices.txt`, followed by
  independent review of notice delivery for direct downloads without altering payload bytes. The
  mechanism's effect on the final publication inventory remains unresolved.

### Security

- Repaired final-review findings covering upstream revision adoption, the combined model/runtime
  inventory, immutable Git/release source binding, complete race-aware dry audit and selection
  preflight, canonical explicit roots, cross-platform manifest locking/atomic replacement, GTE
  legacy-evidence separation, and manifest-mode preservation.
- Second review found additional gaps in preparation-state admission, required-file source
  evidence, exact origin/main/full-SHA/whole-tree release binding, uncertain post-replace
  durability handling, `source_audited` validation, and carry-forward source-tag age. A further
  independent review found canonical-manifest/source binding, pre-contact origin validation,
  six-map preparation, ORT root canonicality, strict upstream-response, and bounded-extraction
  gaps; the second-pass repair closes them. The final hardening pass also uses descriptor-anchored
  ORT installation, bounds archive inspection before materialization/copy, rejects trailing or
  concatenated gzip data, and closes every runtime-manifest section. The newest repair rejects
  publish-time payload substitution while preserving the validated original, prevalidates raw
  PAX/GNU extension records and negative sizes, binds admission to the exact rc13 tuple, caps
  release manifests at 16 MiB, and caps reviewed runtime payloads at 1 GiB before snapshot copy.
  Implementers report a 135/135 local test run for the current candidate, but it is not a
  root-owned full-gate run or independent review. Both remain pending. The helper installer
  deliberately fails before cache mutation on native Windows; its Windows coverage uses a stateful
  fake, so neither native support nor a native-host result is claimed.
- Third-review documentation now distinguishes candidate recording from reviewed-baseline
  adoption: `--apply` records current-remote candidates and invalidates changed archive authority,
  while `--adopt-current` copies one reviewed candidate into the accepted upstream baseline.
- Preparation commits archive metadata through one locked, validated atomic manifest replacement.
  An internal post-replace durability failure becomes public `ManifestDurabilityUnknown`, and all
  archives already created by the transaction are retained for reconciliation.
- Release preflight requires the checked-out local branch itself to be `main`, tracking exactly
  `refs/remotes/origin/main`, in addition to the existing exact-origin and pushed-HEAD checks.
- Release preflight accepts only the canonical model manifest, binds both manifest files to their
  exact HEAD blobs, and validates the canonical GitHub origin before any `ls-remote` contact.
- Hugging Face API and non-LFS byte reads stay on the exact HTTPS host with bounded redirects and
  response sizes. Model and ORT extraction now bound input/output bytes, member count, per-member
  size, exact inventory, sparse entries, and trailing compressed data; ORT also rejects cache-root
  aliases and symlink ancestors.
- Manifest audit confirms 39/39 groups, the exact 43-binary-payload set, status distribution
  of 21 download/16 provenance/2 refresh, six empty provenance maps per unresolved group, and the
  sole Rozgo `NOASSERTION`. Manifest/script modes remain preserved, and the root follow-up scan
  found no generated Python, Ruff, or pytest cache residue.

### Checkpoint and release state

- Version 6.0.2 is reserved for the governance-only checkpoint and does not accept the dirty
  source/tooling candidate. Task 3 must recompute the source checkpoint version after the required
  source-acceptance sequence; 6.0.3 is expected but unassigned. The historical `fastembed-v4`
  model-asset release remains published. No v6 source checkpoint, v6 artifact tag, or GitHub
  Release is claimed by this governance correction.

## [6.0.1] - 2026-09-08

### Added

- Established the repository governance baseline: versioning, architecture, active plan,
  progress, handoff, backlog, security policy, contribution guide, environment reference, and
  explicit repository license.
- Clarified that repository-original tooling is proprietary while redistributed model/runtime
  artifacts retain their upstream licenses and terms.

### Historical note

The repository existed before this governance baseline. Existing commits and the immutable
`fastembed-v4` release remain historical artifacts and are not retroactively versioned.
