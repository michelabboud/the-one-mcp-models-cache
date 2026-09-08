# Glossary

- **Accepted baseline**: the reviewed `upstream_*` provenance values that authorize a later
  archive preparation; a current remote observation does not become a baseline automatically.
- **Adoption**: the explicit, offline `--adopt-current` transition that copies one reviewed
  candidate provenance set into the accepted baseline.
- **Artifact group**: one unique Hugging Face cache repository and its single declared release
  archive; multiple FastEmbed variants can share one group.
- **Binary payload set**: the tooling-validated 43 files: 39 model archives and four required ORT
  runtime archives. It is not yet the final publishable-release inventory.
- **Cache repository**: the conversion or packaging repository that supplies the cached ONNX
  files, distinct from the original-model repository and its licensing.
- **Candidate provenance**: the separate `current_remote_*` maps recorded by a complete upstream
  check for comparison and review; they have no release or preparation authority by themselves.
- **Carry-forward**: a fully proven historical archive that remains installable only through an
  immutable older `source_release_tag`, never through the current intended release tag.
- **Current remote revision**: the observed current Hugging Face commit; it cannot backfill the
  immutable revision embedded in a historical archive.
- **FastEmbed cache group**: an artifact group mapped to one or more FastEmbed API variants and
  their declared runtime files.
- **Immutable release binding**: the requirement that canonical manifest bytes, `VERSION`, clean
  pushed `main`, and the unchanged draft-tag target all identify the same source commit.
- **Legacy archive evidence**: non-installable historical tag, size, and hash values retained in
  `legacy_archive_*` fields; it cannot satisfy v6 provenance or refresh requirements.
- **Native qualification**: evidence produced on the operating system being supported. A fake or
  simulated platform test is useful regression coverage but is not native qualification.
- **Original model**: the upstream model source, whose license and attribution are recorded
  independently from the conversion/cache repository.
- **Prepared archive**: a deterministic local archive ready for independent review; it is not a
  published release asset.
- **Provenance maps**: six per-file evidence maps: accepted and candidate file SHA-256, LFS
  SHA-256, and non-LFS Git blob OIDs. Prepared-archive hashes are a separate evidence layer.
- **Release asset**: a large immutable binary attached to a GitHub Release. Model and runtime
  payloads are release assets, never Git blobs.
- **Schema v3**: the manifest format that separates licensing layers, accepted and candidate
  provenance, explicit adoption, artifact lifecycle, and immutable release binding.
- **Source candidate**: uncommitted or unaccepted tooling/documentation changes awaiting the
  root-owned gate and independent reviews; it is neither a checkpoint nor a release.
- **Transactional publication**: fail-closed preparation and verification that bind one reviewed
  source identity and complete payload set before any manual multi-asset upload is considered.
