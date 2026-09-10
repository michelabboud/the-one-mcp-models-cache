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
- Schema v3 separately records the exact conversion/cache-repository license and provenance and
  the original-model license and provenance; neither may be substituted for the other.
- A current remote Hugging Face revision is comparison data, never proof of the revision embedded
  in a historical release archive.
- Required-file source evidence is independent of archive evidence and consists of six maps. The
  accepted baseline uses `upstream_file_sha256`, `upstream_lfs_sha256`, and
  `upstream_git_blob_oid`; the separate candidate uses `current_remote_file_sha256`,
  `current_remote_lfs_sha256`, and `current_remote_git_blob_oid`. File SHA-256 covers every required
  file, LFS SHA-256 covers LFS objects, and Git blob OIDs cover non-LFS objects. Current-remote maps
  are comparison data until explicit reviewed adoption. `file_sha256` describes prepared archive
  payload bytes and cannot establish their upstream source.
- The GTE `legacy_archive_*` fields are non-installable evidence copied from the baseline manifest.
  They cannot satisfy current v6 revision, archive-size, or archive-hash requirements.
- `meta.last_upstream_check` stays empty until a successful complete current upstream audit. A
  failed, partial, or model-filtered check cannot advance it; the old baseline date is retained
  separately as `meta.legacy_manifest_last_checked`.
- `meta.source_audited` is validated as a required, nonfuture ISO date for the FastEmbed
  source/fixture audit. It does not claim a current Hugging Face check.
- Preparation admits only `download-required` or `refresh-required` records with complete reviewed
  source evidence. The three current-candidate maps must be complete and identical to their
  accepted upstream counterparts after explicit reviewed adoption. `carry-forward` requires an
  immutable older `source_release_tag` distinct from the current release;
  provenance/revision-review records and already prepared/published records cannot enter
  preparation.
- Hugging Face API metadata and non-LFS blob bytes are accepted only from the exact HTTPS host,
  through bounded same-host redirects and bounded responses. Remote bytes never acquire authority
  merely because a redirect or declared response length supplied them.
- Model and runtime archive consumers enforce explicit compressed/logical byte, member-count,
  per-member, exact-inventory, duplicate, sparse/special-member, and trailing-data boundaries before
  publishing anything into a trusted cache.
- Model preparation applies per-member and cumulative logical-byte limits to the initial source
  inventory before staging and reapplies a bounded copy limit to each held source view. Initial
  oversize and growth during copying therefore fail before the candidate can be accepted.
- Model preparation inventories the held source artifact incrementally, admits at most 8,192
  entries and 32 relative path components, and rejects the first unexpected entry before scanning
  further. Held source and private-stage descriptors remain authoritative through metadata reads,
  copy, deterministic archive construction, and validation of the completed archive.
- A cache-directory rename is a publication commit point, not proof of crash durability. Model and
  runtime installers flush published files, the installed tree, both rename parents, and held cache
  ancestry before success. Any postpublication validation or sync failure is durability-unknown
  and retains the visible output and recovery material for explicit operator reconciliation.
- License identifiers and existing generic license copies are not a substitute for exact upstream
  license, copyright, and notice materials for each canonical cache/original repository or for
  ONNX Runtime 1.28.0 `ThirdPartyNotices.txt`.

## Binary payload unit and publication inventory

The tooling-validated binary payload unit is exactly 43 assets: the 39 `<model-key>.tar.gz`
archives derived from `models-manifest.toml` plus the four required `release_asset` entries in the
ORT runtime manifest. Future/optional runtime records are deliberately outside that set. Both
local and remote payload preflight must reject missing, extra, duplicate, renamed, wrong-sized, or
digest-mismatched assets.

This 43-payload unit is not by itself a complete publishable-release inventory. A **High release
blocker** requires recovery and audit of exact per-model cache/original license, copyright, and
notice materials plus ONNX Runtime 1.28.0 `ThirdPartyNotices.txt`. A notice-delivery mechanism must
then be independently reviewed so required notices accompany direct downloads without altering the
payload bytes. Whether that mechanism adds a separate release item is unresolved; the architecture
does not assign it a speculative asset number.

The release content and source are one unit. Upload accepts only the canonical repository model
manifest and requires both model/runtime manifest bytes to match their exact blobs in `HEAD`. The
release tag must equal `v<VERSION>`; `origin` must be the exact canonical configured GitHub
repository and is validated before `ls-remote`; the checked-out local branch must be named `main`
and track exactly `refs/remotes/origin/main`; the whole working tree, including untracked files,
must be clean; and the full 40-character local `HEAD` must equal pushed `origin/main`. The immutable
draft tag target must equal that commit before upload and after remote digest verification.
Validation of the right bytes against a stale/alternate manifest or the wrong source commit is a
failure.

## Artifact lifecycle

1. Audit the exact upstream model revision plus repository-specific license, copyright, and notice
   materials for both the cache and original model.
2. `check-updates.sh --apply` records the current candidate revision, timestamp, and three candidate
   provenance maps without changing the accepted upstream baseline. If a complete check finds that
   an archive-ready baseline changed, it invalidates archive authority as
   `revision-review-required`. After human review, adopt exactly one candidate as the new baseline
   with `check-updates.sh --model KEY --adopt-current`; the atomic offline transition copies the
   candidate into the `upstream_*` fields and moves it to `refresh-required`. Historical
   `provenance-required` records cannot use this path.
3. Materialize the declared cache files outside the git repository.
4. Incrementally inventory one explicit absolute cache source beneath held descriptors, reject
   unexpected, special, over-deep, or over-count content, then snapshot only the declared files
   into private descriptor-held staging.
5. Build deterministic portable archives from those held staged files with normalized modes,
   compute their exact digests, and validate the exact held archive before accepting it.
6. Independently review provenance, archive safety, and checksums.
7. Recover and audit ONNX Runtime 1.28.0 `ThirdPartyNotices.txt`; define and independently review
   how all required notices accompany direct downloads without changing payload bytes.
8. Preflight the complete reviewed binary payload set against the exact configured repository and
   draft tag, after the final publication inventory is resolved.
9. Upload manually because GitHub cannot make a multi-asset upload atomic, then verify the
   complete remote set and every GitHub-reported digest before any publication-state transaction.

The ORT helper installer currently supports Linux and macOS only and deliberately fails before
cache mutation on native Windows. Equivalent secure Windows installation, locking, and replacement
semantics must be implemented and then qualified on a real Windows host before Windows helper
support is advertised. The current stateful fake validates modeled behavior but is not native-host
support or evidence.

Preparation uses conservative durability semantics: it creates no-clobber archives, then commits
their manifest fields through one locked, validated atomic replacement. If that manifest
replacement becomes visible but the post-replace directory sync fails, the internal platform
uncertainty is translated to public `ManifestDurabilityUnknown`. All archives already created by
the transaction remain in place for explicit inspection and reconciliation; cleanup cannot safely
remove them while the manifest's durable state is unknown.

Runtime installation follows the same principle: `ORT_CACHE_DIR` must be a canonical absolute
non-root path with no existing symlink ancestor. One private immutable file snapshot is used for
both checksum verification and bounded decompression. Extraction admits only the declared root
library within explicit byte/member limits and rejects duplicates, sparse/special entries, and
trailing data. Cache-directory identity is revalidated before atomic no-clobber publication at
`ORT_CACHE_DIR/dfbin/<target>/<sha256>`. Success additionally requires flushing the published
library and directory plus the source/destination parents and cache ancestry. Failure during
postpublication validation or at that final durability boundary preserves the installed runtime
and reports `InstallDurabilityUnknown`.

The final security layer rejects publish-time payload substitution while preserving the validated
original, prevalidates raw PAX/GNU extension records and negative sizes before higher-level tar
parsing, and admits runtime metadata only when it matches the exact supported rc13 tuple. Release
manifest inputs are capped at 16 MiB, and reviewed runtime payload inputs are capped at 1 GiB before
their private snapshot copy.

## Related decisions

Architecture decisions are indexed in [docs/adr/README.md](docs/adr/README.md). The current work is
tracked by [PLAN.md](PLAN.md).
