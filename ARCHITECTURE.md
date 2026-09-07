# Architecture

## Purpose

This repository is the offline, checksum-pinned artifact companion for `the-one-mcp`. Git stores
manifests, attribution, licenses, and deterministic tooling. Large model and native-runtime files
belong in immutable GitHub Release assets, never in git history.

## Trust boundaries

- `models-manifest.toml` is the authoritative mapping from FastEmbed variants to cache artifacts,
  required files, upstream revisions, release assets, sizes, and SHA-256 digests.
- `runtime/*/manifest.toml` independently describes target-specific ONNX Runtime archives.
- Download/install tools must verify an archive before publishing files into a trusted cache.
- Packaging tools must include only an explicitly declared artifact inventory; ambient cache files
  are untrusted and must never be swept into a release.
- Empty hashes or unresolved upstream revisions are fail-closed release blockers.

## Artifact lifecycle

1. Audit the exact upstream model revision and licensing.
2. Materialize the declared cache files outside the git repository.
3. Validate the complete declared inventory and reject unexpected content.
4. Build deterministic archives in staging and compute their exact digests.
5. Independently review provenance, archive safety, and checksums.
6. Upload only to an explicitly existing release, then verify every remote asset.

Runtime installation follows the same principle: one verified archive is safely extracted to a
staging directory and atomically published at `ORT_CACHE_DIR/dfbin/<target>/<sha256>`.

## Related decisions

Architecture decisions are indexed in [docs/adr/README.md](docs/adr/README.md). The current work is
tracked by [PLAN.md](PLAN.md).
