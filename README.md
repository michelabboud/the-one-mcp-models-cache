# the-one-mcp-models-cache

Checksum-pinned ONNX model caches for
[the-one-mcp](https://github.com/michelabboud/the-one-mcp). Model weights are GitHub Release
assets, not git objects.

This manifest is aligned with the versions currently pinned by the-one-mcp: **FastEmbed 6.0.2**
and **`ort`/`ort-sys` 2.0.0-rc.13, which bind ONNX Runtime 1.28.0**. The application currently
uses CPU execution. An attached AMD eGPU is not active for these models because the the-one-mcp
build does not enable a DirectML or WebGPU execution-provider feature.

## Tooling prerequisites

Repository tooling requires Python 3.11 or newer; it uses the standard-library `tomllib` module and
does not require a Python package install for normal cache operations. The full maintainer gate also
requires Bash, ShellCheck, Ruff, and basedpyright. The historical 117-test run recorded on
2026-09-08 predates later repairs. The current 2026-09-10 direct reviewed-artifact scanner gate
used Python 3.12.3, ShellCheck 0.9.0, Ruff 0.15.18, and basedpyright 1.39.8 (Pyright 1.1.410):
manifest 39/43, central 162/162, runtime 47/47 (209 tests total), shell syntax, ShellCheck, Ruff
check/format, and basedpyright with zero diagnostics were green. The root then froze the candidate,
verified its diff, completed an isolated Linux ORT probe, and obtained fresh independent
specification/quality plus deep security/architecture approval for the source checkpoint.

Git is additionally required when a workflow verifies committed source identity. An authenticated
GitHub CLI is required only for GitHub downloads, remote release preflight, upload, verification,
or release operations. These conditional operational prerequisites are distinct from the local
test and static-analysis tools above.

## Migration status

The manifest targets a future FastEmbed 6 cache release with the canonical identity **`v6.0.2`**.
That target string is not evidence of a Git tag or GitHub Release. As of 2026-09-08, the only
repository checkpoint tag is **`checkpoint/6.0.1`**, the only model-asset GitHub Release is the
historical **`fastembed-v4`** release, and no `v6.0.2` tag or release exists. No script assumes that
release exists, and the sync tool will not create it. `checkpoint/6.0.3` records the reviewed
source/tooling checkpoint only; it is not a `v6.0.2` artifact tag or GitHub Release.

| State | Artifact groups | Availability |
|-------|----------------:|--------------|
| Historical `fastembed-v4` archives | 16 | Release hashes retained; exact embedded revisions still require recovery |
| New in FastEmbed 6.0.2 | 21 | Download required; intentionally no SHA-256 yet |
| Existing GTE archives needing quantized graphs | 2 | Refresh required; intentionally no SHA-256 yet |
| Total unique cache repositories | 39 | One archive per repository |

The 21 new artifact groups have a **rough, unverified 12.74 GiB raw estimate**, recorded on
2026-09-08 before archive compression. It is not derived from verified manifest byte counts and
must not be used for capacity or release approval until exact pinned files are measured. The
two GTE caches must be rebuilt because FastEmbed 6.0.2 also selects
`onnx/model_quantized.onnx`. Empty checksums are a release safety gate, not placeholders: the
download script refuses those artifacts before invoking GitHub or changing the cache.

The historical `fastembed-v4` tag and assets remain immutable. The 16 unchanged historical
entries retain their release-level archive evidence but are deliberately marked
`provenance-required`: the exact `refs/main` revisions embedded inside those archives have not
been recovered locally, and current Hugging Face HEAD is not valid historical evidence. The two
GTE entries instead remain `refresh-required` because FastEmbed 6 needs an additional quantized
graph. Their old `fastembed-v4` tag, recorded version, declared size in MiB, and SHA-256 survive
only in `legacy_archive_*` evidence fields; the current v6 revision, size, and hash fields stay
blank. Download and release tooling must never treat legacy evidence as an installable v6 archive.

No current upstream comparison was completed while constructing schema v3, so
`meta.last_upstream_check` is intentionally empty. `meta.legacy_manifest_last_checked` preserves
the baseline's 2026-04-04 historical value without misrepresenting it as a current 39-model audit.
A successful complete current check may write the UTC date atomically; a failed, partial, or
model-filtered check must not advance the global date.

## Coverage and defaults

The 39 artifact groups cover every cache repository needed by the-one-mcp's FastEmbed 6.0.2
registry:

| Type membership | Artifact groups | Default |
|-----------------|----------------:|---------|
| Text embedding | 29 | `BGE-large-en-v1_5` (1024 dimensions) |
| Reranker | 4 | `jina-reranker-v2-base-multilingual` |
| Image embedding | 5 | `nomic-embed-vision-v1_5` (768 dimensions) |
| Sparse embedding | 2 | `Splade_PP_en_v1` |

Membership counts total 40 because the single `BGE-M3` artifact serves both dense and sparse
variants. EmbeddingGemma is recorded at the FastEmbed 6.0.2 value of **768 dimensions**, with
full-precision, Q4, and quantized ONNX graphs plus their external-data files.

Run the manifest gate for the authoritative model list and exact runtime paths:

```bash
bash scripts/validate-manifest.sh
bash scripts/download-model.sh --list
```

## Binary payload inventory and publication blocker

The tooling currently validates exactly **43 binary payload assets** for the intended future
`v6.0.2` release:

- 39 model archives named `<models-manifest key>.tar.gz`; and
- the four `release_asset` values in
  `runtime/ort-sys-2.0.0-rc.13/manifest.toml` for Linux x86-64, Linux ARM64, Apple Silicon
  CoreML, and Windows x86-64 DirectML.

The four runtime asset names are:

- `onnxruntime-1.28.0-ort-sys-2.0.0-rc.13-x86_64-unknown-linux-gnu.tar.lzma2`
- `onnxruntime-1.28.0-ort-sys-2.0.0-rc.13-aarch64-unknown-linux-gnu.tar.lzma2`
- `onnxruntime-1.28.0-ort-sys-2.0.0-rc.13-aarch64-apple-darwin+coreml.tar.lzma2`
- `onnxruntime-1.28.0-ort-sys-2.0.0-rc.13-x86_64-pc-windows-msvc+directml.tar.lzma2`

The runtime manifest's Windows ARM64 `future_archives` entry and Linux WebGPU
`optional_archives` entry are provenance records, not members of this 43-payload set. Local and
remote payload preflight must derive the set from both manifests and reject any missing, extra,
duplicate, renamed, wrong-sized, or digest-mismatched payload.

The number 43 is not by itself a complete publishable-release inventory. The **High release
blocker** is to recover and audit the exact license, copyright, and notice materials for every
canonical model cache repository and original-model repository, plus ONNX Runtime 1.28.0
`ThirdPartyNotices.txt`. Then define and independently review a mechanism that makes the required
notices accompany every direct download without altering any model or runtime payload bytes.
Whether that design adds a separate release item is intentionally unresolved; the final
publication inventory cannot be declared until the design and review close.

Publication also binds content to source identity. `VERSION` must equal the manifest tag without
the `v`; upload must use the repository's canonical `models-manifest.toml`; and both that file and
the runtime manifest must match their exact blobs in `HEAD`. `origin` is validated as the exact
configured canonical GitHub repository before any `ls-remote` contact. The checked-out local branch
must be named `main` and track exactly `refs/remotes/origin/main`; the entire working tree,
including untracked files, must be clean; and the full 40-character `HEAD` must equal the pushed
`origin/main`. The existing immutable draft tag target must equal that exact commit before upload
and again after remote digest verification. An alternate/stale manifest, abbreviated SHA, clean
release-critical subset inside a dirty tree, or the right assets attached to another commit is not
the reviewed release.

## Download verified archives

The default command selects BGE-large, but currently fails closed because its historical archive
still needs exact embedded-revision provenance. Once an entry is `published`, the downloader
copies the release asset into a private immutable snapshot, checks its SHA-256 and byte size,
extracts only declared regular files into staging, verifies the exact revision and file/LFS
digests, and atomically installs without overwriting an existing cache:

```bash
# Default text embedding artifact
bash scripts/download-model.sh

# One artifact by manifest key
bash scripts/download-model.sh all-MiniLM-L6-v2

# Preflight every artifact of a type, then download only if the whole set is verified
bash scripts/download-model.sh --embeddings
bash scripts/download-model.sh --rerankers
bash scripts/download-model.sh --images
bash scripts/download-model.sh --sparse
```

`--all` and the type selectors are intentionally all-or-nothing at preflight: while any selected
manifest entry has no verified checksum, the command exits before downloading anything. The
cache destination must use one canonical absolute non-root spelling and must not traverse a
symlink ancestor. Set it in either:

1. `FASTEMBED_CACHE_DIR` (the current FastEmbed spelling)
2. `FASTEMBED_CACHE_PATH` (legacy compatibility)

A manual download must use the exact archive key and checksum from the manifest. For example,
the default filename is `BGE-large-en-v1_5.tar.gz`, not the display name with a dot.

Downloaded model archives are consumed from one verified immutable snapshot. Extraction accepts
only the exact declared file/directory inventory, rejects duplicate, noncanonical, sparse, and
special members, and enforces explicit compressed-archive, member-count, per-member, and total
logical-output limits before atomic no-clobber installation. Each written leaf is reread and bound
to its byte digest, filesystem identity, and mutable state. The exact final staged inventory is
revalidated before rename and the published inventory is reopened and rehashed before durability
is accepted. The installer flushes every published regular file and directory plus both rename
parents before it reports success. The rename helper records its commit immediately after the
no-clobber syscall succeeds; any later helper, validation, synchronization, descriptor-close, or
context-exit failure reports durability as unknown and preserves the installed tree for operator
recovery instead of claiming success or deleting the only visible copy.

## Cache and archive format

Schema v3 defines one release archive per unique Hugging Face repository. Multiple FastEmbed
variants share an artifact when their model files occupy one cache repository.

```text
models--ORG--REPOSITORY/
├── refs/
│   └── main
└── snapshots/
    └── UPSTREAM_REVISION/
        ├── model.onnx (or an onnx/ subdirectory)
        ├── tokenizer.json or preprocessor_config.json
        └── other required files declared by the manifest
```

Important schema fields:

- `types`, `fastembed_variants`, and `variant_dims` map each variant to the FastEmbed API surface;
  BGE-M3 is 1024-dimensional for its dense variant and `0` for its sparse variant.
- `model_files`, `additional_files`, and `required_files` describe the exact 6.0.2 runtime set.
- `upstream_revision` identifies the exact archived Hugging Face commit; `current_remote_revision`
  is a separately audited current HEAD and never backfills historical provenance.
- Six provenance maps bind accepted upstream baselines and separate current-remote candidates:
  `upstream_file_sha256` / `current_remote_file_sha256` cover every required file's bytes,
  `upstream_lfs_sha256` / `current_remote_lfs_sha256` record LFS object SHA-256 values, and
  `upstream_git_blob_oid` / `current_remote_git_blob_oid` record Git blob OIDs for non-LFS files.
  A repository commit alone is not sufficient file evidence, and the prepared archive's
  `file_sha256` map is not a substitute for upstream source evidence.
- `cache_repo_license`/`cache_attribution` describe the exact conversion/cache repository, while
  `original_model_license`/`original_attribution` describe the underlying model.
- `status` defines the artifact lifecycle:
  - `provenance-required` — historical archive evidence exists, but its embedded immutable upstream
    revision is unresolved; current HEAD cannot replace it.
  - `download-required` — the intended cache artifact has no verified archive yet.
  - `refresh-required` — a reviewed upstream baseline is selected, but the archive must be rebuilt.
  - `revision-review-required` — a complete upstream check found a different revision or LFS set,
    invalidated the old archive claims, and requires an explicit reviewed adoption decision.
  - `carry-forward` — an unchanged, fully proven historical archive remains installable from its
    immutable older `source_release_tag`; the source tag is required and must differ from the
    current manifest release tag.
  - `prepared` — a complete deterministic local archive is ready for independent review.
  - `published` — the reviewed archive belongs to the verified remote binary-payload set.
- `sha256` is mandatory for every downloadable artifact.
- `source_release_tag` keeps an unchanged archive resolvable from an older immutable release.
- `legacy_archive_*` fields are non-installable audit evidence only. They preserve a prior
  manifest's GTE tag/version/declared-size/hash facts while the v6 `upstream_revision`,
  `archive_size_bytes`, and `sha256` fields remain empty.
- `meta.last_upstream_check` is empty until one successful complete current audit. The historical
  baseline date lives separately in `meta.legacy_manifest_last_checked`.
- `meta.source_audited` is a required, valid, nonfuture ISO date for the FastEmbed source/fixture
  audit. It is distinct from the live Hugging Face check date and advances only after that source
  mapping is actually re-audited.

## Maintainer workflow

The tools separate read-only checks, local preparation, and remote effects.

```bash
# 1. Validate schema, paths, attribution, defaults, statuses, and checksums.
bash scripts/validate-manifest.sh

# 2. Compare exact Hugging Face revisions (read-only; never changes the audit date).
bash scripts/check-updates.sh

# Record current remote candidates without adopting them as the accepted upstream baseline, and
# invalidate genuinely changed archives. Only a complete successful transactional --apply run
# over all models writes the global UTC audit date.
bash scripts/check-updates.sh --apply

# After inspecting one candidate revision, timestamp, and all three candidate provenance maps,
# explicitly adopt that reviewed candidate as the accepted upstream baseline. This transition is
# offline, atomic, and never accepts a provenance-required historical entry.
bash scripts/check-updates.sh --model KEY --adopt-current

# 3. Audit a populated cache without creating dist/ or editing the manifest. Dry audit requires at
# least one explicit absolute discovery root.
bash scripts/sync-release.sh --model embeddinggemma-300m \
  --discover-cache /absolute/path/to/.fastembed_cache

# 4. Snapshot one explicit cache root, create a curated archive, and record its hashes.
bash scripts/sync-release.sh --model embeddinggemma-300m --prepare \
  --cache-source /absolute/path/to/.fastembed_cache

# 5. After independent review, preflight a complete already-prepared artifact set.
bash scripts/upload-release.sh --artifacts-dir /absolute/path/to/reviewed --preflight

# 6. After manual upload, verify the complete remote draft and every GitHub digest.
bash scripts/upload-release.sh --artifacts-dir /absolute/path/to/reviewed --verify-remote
```

Dry audit accepts only roots explicitly passed with `--discover-cache` and never mutates the
requested cache, manifest, or `dist/`. `--prepare` requires one explicit absolute non-root
`--cache-source`, snapshots a curated allowlist before validation, rejects unexpected or special
entries, rejects an initially oversized member or cumulative payload before creating staging, and
reapplies the same limits while copying so a growing source cannot bypass them. The source walk is
incremental, limited to 8,192 entries and 32 relative path components, and stops at the first
unexpected entry. Metadata reads, copies, deterministic archive construction, and completed-archive
validation stay anchored to held source/stage/archive descriptors; replaceable staging pathnames do
not regain authority. It uses a portable deterministic Python ustar/gzip packer with normalized
modes. It
refuses to clobber an existing archive and records all prepared models through one locked,
validated atomic manifest transaction. Audit and preparation print and retain their private
workspace because a portable recursive pathname cleanup cannot prove that the top-level entry was
not replaced; inspect and reconcile that exact path before any manual cleanup.
`sync-release.sh --upload` is disabled.

Preparation is state-gated. Only `download-required` or `refresh-required` entries with complete
reviewed upstream revision, timestamp, required-file SHA-256, and Git-object/LFS evidence may enter
`--prepare`. All three current-candidate provenance maps must also be complete and identical to the
accepted upstream maps, proving that explicit reviewed adoption occurred. `provenance-required` and
`revision-review-required` lack accepted source authority; `carry-forward` is already bound to an
older immutable release; and `prepared`/`published` must not be overwritten by another preparation
attempt.

Preparation creates each no-clobber archive before replacing the manifest through one locked,
validated atomic update. If the manifest replacement becomes visible but its post-replace directory
sync cannot prove durability, the internal platform error is translated to the public
`ManifestDurabilityUnknown` error. All archives already created by that preparation transaction are
retained for operator inspection and reconciliation; automatic rollback or cleanup could discard
the only recoverable copy while the manifest's durable state is unknown.

`--apply` records `current_remote_revision`, `current_remote_last_modified`, and all three current
candidate provenance maps; it does not adopt any candidate as the accepted baseline. For an
archive-ready record whose candidate differs from the accepted revision or provenance maps, it
also clears archive authority and moves the record to `revision-review-required`.

Current checks read Hugging Face model metadata and non-LFS blobs only from the exact
`https://huggingface.co` host. Redirects remain on that host and use HTTPS, their count is bounded,
and metadata/blob response sizes are capped before those bytes enter provenance decisions.

`--adopt-current` is the separate deliberate reviewed-baseline transition, not a network check and
not automatic approval. It requires exactly one explicit `--model`, refuses
`provenance-required` records, requires a previously validated candidate with complete required-file
evidence, and refuses an archive-ready record until `--apply` has invalidated changed archive
claims. After the operator reviews the candidate revision, timestamp, and provenance maps,
adoption atomically copies them into the corresponding `upstream_*` baseline fields, clears any
obsolete `source_release_tag`, and moves
`revision-review-required` to `refresh-required`. It does not recreate an archive, publish an
asset, or advance the global upstream-check date.

`upload-release.sh` never creates or regenerates archives and never performs automated multi-asset
publication because GitHub does not provide an atomic upload transaction. It validates the
complete reviewed binary payload set before GitHub access, accepts only the canonical model
manifest, verifies both manifest byte streams against their exact HEAD blobs, and requires the
manifest repository to match a canonical GitHub `origin` before contacting that origin. It accepts
only the exact draft tag, refuses asset collisions, and can verify the complete remote set and
GitHub-reported SHA-256 digests after a manual upload. It does not change manifest status.

The newest hardening also rejects publish-time payload substitution while preserving the validated
original, prevalidates raw PAX/GNU extension records and negative tar sizes before higher-level tar
parsing, admits only the exact supported rc13 metadata tuple, caps each release manifest at 16 MiB,
and caps each reviewed runtime payload at 1 GiB before its private snapshot copy.

The final deep-review repair adds three later transaction boundaries: the installer rechecks the
held decompressed tar before atomic payload publication; model archive publication consumes a
bounded nonblocking no-follow snapshot, binds it to the reviewed size and SHA-256, and rehashes the
held output before linking; and audit and preparation retain command workspaces when identity-safe
recursive cleanup is unavailable, including a foreign top-level replacement.

Before creating or publishing `v6.0.2`:

1. Populate all 21 new caches and refresh both GTE caches outside git (about 12.74 GiB raw plus
   the GTE downloads).
2. Recover and verify embedded revisions from every historical `fastembed-v4` archive; never
   substitute current Hugging Face HEAD. Record current remote metadata separately with
   `check-updates.sh --apply`.
3. Inspect each changed candidate revision, timestamp, and three provenance maps, then adopt it with
   `bash scripts/check-updates.sh --model KEY --adopt-current` before rebuilding.
4. Run a read-only sync audit with an explicit `--discover-cache` root, then prepare deterministic
   archives.
5. Recover and audit exact per-model cache/original license, copyright, and notice materials and
   ONNX Runtime 1.28.0 `ThirdPartyNotices.txt`; resolve Rozgo's `NOASSERTION` separately.
6. Define and independently review how required notices accompany direct downloads without
   changing the exact payload bytes. Do not finalize the publication inventory until that design
   closes.
7. Independently verify generated archive SHA-256 values and extraction safety. The prior
   94/94 central-plus-platform and 23/23 ORT result (117 total) is retained as historical evidence.
   The current direct-scanner repair gate is 162/162 central and 47/47 runtime (209 total), with the
   complete non-Git local static gate green; the frozen candidate has since passed the root gate,
   isolated Linux ORT probe, and fresh independent review for source-checkpoint closeout. The
   manifest still records 21
   download/16 provenance/2 refresh statuses, all six provenance maps remain empty for every
   unresolved group, and Rozgo remains the sole `NOASSERTION`. The helper installer supports
   Linux/macOS only and deliberately fails closed before cache mutation on native Windows; its
   Windows behavior has only a stateful fake, not a native Windows host result. No model artifact
   was downloaded during this repair, and publication remains blocked.
8. Verify the exact 43-binary-payload set and the exact clean, pushed source binding.
9. After the final publication inventory is resolved, create the intended `v6.0.2` draft GitHub
   Release explicitly; tooling will not create it.
10. Preflight the complete reviewed 43-payload set, upload it manually without clobbering, deliver
    the independently reviewed notices, and run remote verification before any separate reviewed
    transaction marks entries published.

## ONNX Runtime bootstrap

Model archives do not include the ONNX Runtime native static library. Use
`python3 scripts/install-ort-runtime.py --help` for the separate, checksum-pinned runtime
bootstrap workflow. `ORT_CACHE_DIR` must use one canonical absolute non-root spelling and cannot
traverse an existing symlink ancestor. The installer consumes one checksum-verified immutable
snapshot; bounds compressed and decompressed bytes, member count, per-member bytes, and total tar
bytes; rejects sparse, duplicate, special, unexpected, and trailing data; requires exactly the
declared root library; rereads the written leaf and binds its digest, identity, and mutable state;
rechecks the exact staged inventory, held decompressed tar, and cache-directory identity before
publication; and reopens and rehashes the exact published inventory before accepting durability.
Runtime binaries and their manifests live outside model artifact groups. After publication it
flushes the installed library, payload directory, both rename parents, and the held cache-directory
ancestry. The rename helper records the commit before any post-rename check. A later helper,
validation, synchronization, descriptor-close, or context-exit failure raises a durability-unknown
installation error and retains the visible runtime plus private recovery material; it is never
reported as a successful install.

## License and attribution

This git repository contains metadata and tooling, not model weights. Each family directory has
an `ATTRIBUTION.md` record and, where applicable, a license copy. The manifest separately records
original-model and exact conversion/cache-repository attribution and license fields.

Those metadata fields and existing generic license copies do not complete publication compliance.
Exact upstream license, copyright, and notice materials for every canonical cache/original pair,
plus ONNX Runtime 1.28.0 `ThirdPartyNotices.txt`, must be recovered and audited before publication.
The independently reviewed delivery mechanism must accompany direct downloads without changing
the checksum-pinned payload bytes; its effect on the final publication inventory is unresolved.

Models retain their upstream licenses and terms. In particular, EmbeddingGemma declares the
custom Gemma terms rather than an open-source SPDX license; review the canonical terms before
redistribution. This project does not claim ownership of upstream models or ONNX conversions.

FastEmbed's selected [`rozgo/bge-reranker-v2-m3`](https://huggingface.co/rozgo/bge-reranker-v2-m3)
cache is an ONNX export of
[`BAAI/bge-reranker-v2-m3`](https://huggingface.co/BAAI/bge-reranker-v2-m3). The BAAI source page
declares Apache-2.0, but the official Rozgo page declares no cache-repository license metadata.
That conversion layer is `NOASSERTION`, and redistribution remains blocked until its rights are
resolved; the original model's license cannot be copied onto the export.

## Related projects

- [the-one-mcp](https://github.com/michelabboud/the-one-mcp)
- [fastembed-rs](https://github.com/Anush008/fastembed-rs)
- [Hugging Face Hub](https://huggingface.co/)
