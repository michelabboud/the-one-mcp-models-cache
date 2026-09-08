# ADR 0001: Store model and runtime payloads as release assets, not Git blobs

**Status:** Accepted — 2026-09-08

## Context

The cache repository distributes large ONNX model archives and target-specific ONNX Runtime
archives. These payloads are checksum-pinned binary artifacts with a separate lifecycle from
manifests, attribution, licenses, and deterministic tooling. Putting them in Git history would
make every clone carry release-scale binary history, complicate immutable artifact verification,
and make a corrected payload expensive to supersede without rewriting history.

## Decision

Keep source-controlled manifests, attribution, licenses, and tooling in Git. Publish reviewed
model and runtime payloads only as immutable GitHub Release assets. The tooling-validated binary
payload set is exactly 43 assets: 39 model archives plus four required runtime `release_asset`
entries. This count is not a declaration of the final publishable-release inventory: the required
notice-delivery design remains a High release blocker.

## Alternatives rejected

- **Commit payloads as Git blobs:** rejected because clone and history cost scale with large binary
  artifacts and source history is not a practical immutable release-asset transport.
- **Download direct from upstream at install time:** rejected because upstream bytes and revisions
  can change; offline operation and checksum-pinned reproducibility require reviewed release
  assets.
- **Publish a partial release while unresolved groups remain:** rejected because 21 groups are
  `download-required`, 16 are `provenance-required`, and two are `refresh-required`; a partial
  inventory would violate the complete-set contract.

## Consequences

Release tooling must fail closed on missing, extra, duplicate, renamed, wrong-sized, or
digest-mismatched assets. Git history remains small and auditable, while payload availability,
notice delivery, provenance, independent review, and release publication remain distinct gates.
No `v6.0.2` tag or GitHub Release exists under this decision.
