# Progress

## 2026-09-08 security remediation

- Added the missing governance entrypoints and append-only ADRs for release-asset storage,
  schema-v3 six-map provenance/adoption plus immutable source/release binding, and transactional
  platform fail-closed behavior. This documentation work does not accept the source candidate or
  replace its root-owned gate and independent reviews.
- Added RED-before-GREEN coverage for archive path swaps, no-clobber publication, curated
  packaging, exact provenance, strict path grammar, atomic install/manifest behavior, malformed
  upstream metadata, and fail-closed release preflight.
- Migrated the model manifest to schema v3 with split original/cache licensing and provenance,
  per-variant dimensions, and an audited FastEmbed 6.0.2 fixture covering all 48 represented
  variants across 39 artifact groups.
- Historical `fastembed-v4` release hashes are retained, but all 16 entries remain
  `provenance-required` until their exact embedded revisions are independently recovered.
- Preserved the two GTE baseline records as non-installable `legacy_archive_*` evidence copied
  from commit `71af438`. Their current FastEmbed 6 revision, size, and SHA fields remain empty and
  `refresh-required`.
- Final review found gaps in changed-upstream invalidation/adoption, combined payload preflight,
  immutable source binding, complete dry audit/selection preflight, canonical cross-platform roots
  and locking, GTE evidence separation, upstream-check dating, and manifest-mode preservation.
  A second review then found preparation-state, independent required-file source-evidence,
  exact-repository/source-binding, post-replace durability-uncertainty, `source_audited`, and
  carry-forward source-tag gaps. A further independent review found that upload could consume a
  noncanonical or stale manifest, origin was contacted before it was validated, preparation did not
  enforce agreement across all six provenance maps, ORT cache roots normalized rather than rejected
  aliases/symlink ancestors, and network/archive inputs needed explicit resource bounds. The
  second-pass repair closes those gaps. The final hardening pass additionally closes descriptor
  races through derived ORT cache components, bounds archive headers and pre-copy input growth,
  rejects noncanonical member/framing aliases, and validates the complete closed runtime schema.
  The newest repair rejects publish-time payload substitution while preserving the validated
  original, prevalidates raw PAX/GNU extension records and negative sizes, requires the exact rc13
  tuple, and caps release manifests at 16 MiB and reviewed runtime payloads at 1 GiB. The prior
  implementers report a 135/135 local test run for the current candidate, but that run is not
  root-owned evidence and does not replace the still-pending root full-gate rerun or final
  independent specification/security re-review.
- A read-only real-archive probe used the operator-provided Linux x86_64 ORT archive from outside
  the repository. The installer produced exactly one 105,481,448-byte `libonnxruntime.a` at the
  manifest-bound digest path in a new isolated `/tmp` cache. The 101 MiB test cache was then
  removed and its absence verified; the source archive was not modified.
- The tooling-validated binary payload set is exactly 43 assets: 39 model archives plus four
  required ONNX Runtime archives. Source verification must bind that exact set to `VERSION`, the configured
  GitHub `origin`, the checked-out local `main` branch tracking exactly
  `refs/remotes/origin/main`, a whole-tree-clean state, a full 40-character `HEAD` equal to pushed
  `origin/main`, and the unchanged immutable draft-tag target.
- **High release blocker:** the 43 binary payloads are not by themselves a complete publishable
  inventory. Before v6 publication, recover and audit exact license, copyright, and notice
  materials for every canonical model cache/original repository and ONNX Runtime 1.28.0
  `ThirdPartyNotices.txt`; then define and independently review notice delivery that accompanies
  direct downloads without altering payload bytes. Whether that design adds a separate release
  item is unresolved, so the final publication inventory remains unresolved.
- No complete current Hugging Face audit has run, so `last_upstream_check` is empty. The prior
  2026-04-04 baseline date is historical evidence only. The three `current_remote_*` provenance
  maps are candidate comparison data and never prove historical archive provenance.
- Required files independently carry all six provenance maps: upstream/current content SHA-256,
  upstream/current LFS SHA-256, and upstream/current Git blob OIDs for non-LFS objects. The Rozgo
  BGE-reranker-v2-m3 ONNX cache has no license metadata; its conversion license is `NOASSERTION`
  and redistribution remains blocked, while the official BAAI original declares Apache-2.0.
- Preparation is limited to reviewed `download-required`/`refresh-required` records.
  All six upstream/current provenance maps must be complete and identical after reviewed adoption.
  `carry-forward` requires an older immutable source tag. Preparation records archives through one
  locked, validated atomic manifest replacement; internal durability uncertainty is exposed as
  `ManifestDurabilityUnknown`, with every already-created archive retained for reconciliation.
- Manifest audit covers 39/39 groups and the exact 43-binary-payload set. All six
  upstream/current provenance maps remain empty for every unresolved group; statuses are 21
  `download-required`, 16 `provenance-required`, and 2 `refresh-required`. Rozgo is the sole
  `NOASSERTION` cache license. Manifest and script modes are preserved. The root follow-up scan
  found no generated Python, Ruff, or pytest cache residue.
- Release preflight accepts only the canonical `models-manifest.toml`, verifies both model and
  runtime manifest bytes against the exact HEAD blobs, and validates the canonical GitHub origin
  before `ls-remote`. Hugging Face metadata and non-LFS blob reads stay on the exact HTTPS host with
  bounded redirects and response sizes. Model and ORT extraction enforce compressed/logical byte,
  member-count, per-member, exact-inventory, raw PAX/GNU/negative-size, and sparse/trailing-data
  limits. Release manifest reads are capped at 16 MiB and reviewed runtime payloads at 1 GiB.
- No large artifact was downloaded into or committed to this repository, and no task commit, tag,
  push, release, upload, or database access was performed for the in-progress repair.

## Current repository state

The governance foundation is established. The FastEmbed 6.0.2 model manifest, cache tooling, and
ONNX Runtime rc13 bootstrap are in progress and remain unpublished. Version 6.0.2 is reserved for
the governance-only checkpoint, not assigned to this dirty, unaccepted source/tooling candidate.
Task 3 must recompute the source checkpoint version after source acceptance; 6.0.3 is expected but
not assigned.

The source-acceptance order is root full gate; real native ORT probe; ordered candidate-fingerprint
freeze; fresh Sol specification/quality and Astra security/architecture reviews; repairs and
re-freeze as needed; then source checkpoint commit, tag, and push. The historical `fastembed-v4`
release remains the only model-asset release. The 21 `download-required`, 16
`provenance-required`, and two `refresh-required` groups; Rozgo `NOASSERTION`; exact
license/copyright/notice recovery and notice delivery; artifact acquisition; and native-host
qualification are publication blockers only, not source-checkpoint blockers. The helper installer
supports Linux/macOS only and deliberately fails before cache mutation on native Windows. Its
current Windows platform evidence is a stateful fake, not native support or a native-host test. No
model artifact was downloaded during this repair.
