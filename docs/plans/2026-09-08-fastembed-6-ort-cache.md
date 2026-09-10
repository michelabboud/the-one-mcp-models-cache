# FastEmbed 6.0.2 and ORT rc13 Cache Plan

**Status:** Source checkpoint complete at `checkpoint/6.0.3`; publication blocked

**Written:** 2026-09-08

**Approved:** 2026-09-08 by Michel in the active conversation

**Last updated:** 2026-09-10

## Goal

Provide `the-one-mcp` with an independently auditable, offline-capable cache for every FastEmbed
6.0.2 model artifact it advertises and every ONNX Runtime rc13 target needed by its supported
release matrix. The current helper-installer milestone is intentionally Linux/macOS-only; the
Windows x86-64 asset remains in the planned binary payload set, while secure native Windows
installation and real-host qualification are explicit blockers.

## Tasks

1. Establish the repository governance and security baseline as version 6.0.1.
2. Map all FastEmbed 6.0.2 variants to unique Hugging Face cache artifacts and exact required files.
3. Carry forward only historical archives whose bytes, source release, and provenance are verified.
4. Add checksum-pinned ORT target metadata and a safe, offline Linux/macOS installer; keep native
   Windows installation fail-closed until its separate secure implementation and qualification.
5. Make downloads, preparation, extraction, and upload fail closed and transactional.
6. Run independent specification and security reviews; repair every blocker.
7. Recover and audit the exact per-model cache/original license, copyright, and notice materials
   and ONNX Runtime 1.28.0 `ThirdPartyNotices.txt`; define and independently review notice delivery
   for direct downloads without changing payload bytes. This is a **High release blocker**.
8. Populate missing large assets manually or through approved upstream access, verify them, and only
   then publish a complete v6 release.

### Final frozen-diff repair history

### Source acceptance outcome (2026-09-10)

The repaired source candidate passed the root-owned manifest gate (39 groups / 43 binary payloads),
162 central tests, 47 runtime tests, ShellCheck, Ruff check/format, and basedpyright with zero
diagnostics. An isolated native Linux x86_64 ORT probe installed the manifest-bound archive without
modifying the shared cache. After the ordered candidate fingerprint was frozen, fresh independent
specification/quality and deep security/architecture reviews approved the source candidate for a
source-only checkpoint.

`VERSION` 6.0.3 was committed as `a665b9e`, annotated `checkpoint/6.0.3`, and pushed to
`origin/main`; the peeled remote tag resolves to that exact commit. This approval does not
authorize an artifact tag, model upload, GitHub Release, or publication work. The publication
blockers in Tasks 7 and 8 remain unchanged.

Before version closeout, the final review requires the following verified repairs:

1. Make upstream checks invalidate every archive-ready state when provenance changes, and require a
   separate reviewed adoption transition before rebuilding against the new revision and LFS hashes.
2. Treat all 39 model archives and all four required ONNX Runtime archives as one exact binary
   payload set for local and remote preflight, without presenting that set as the complete
   publishable-release inventory.
3. Bind release verification to `VERSION`, a clean committed release-critical tree, pushed `HEAD`,
   and the immutable draft tag target; recheck that target after remote verification.
4. Make dry sync a complete, race-aware cache audit and preflight an entire download selection before
   its first network or filesystem mutation.
5. Canonicalize every explicit cache/artifact root and reject aliases and symlink ancestors.
   Provide equivalent secure installation, manifest locking, and atomic replacement semantics on
   native Windows as a separate blocked platform task; until then the installer fails closed there.
6. Preserve baseline GTE archive evidence in non-installable `legacy_archive_*` fields, keep the
   still-unknown FastEmbed 6.0.2 revision/size/hash fields blank and `refresh-required`, allow an
   empty `last_upstream_check`, update that date only after a successful complete current audit,
   and preserve manifest permissions.
7. Run focused RED/GREEN regressions followed by the expanded cache/runtime, manifest, shell, Ruff,
   formatting, basedpyright, and diff gates.

### Review repair rounds (implemented locally; final re-review pending)

The second review required these additional repairs for the current locally verified candidate:

1. Admit preparation only from `download-required` or `refresh-required` with complete reviewed
   source authority; reject provenance/revision-review, carry-forward, prepared, and published
   states.
2. Bind every required file independently with all six provenance maps: upstream/current file
   SHA-256, upstream/current LFS SHA-256, and upstream/current Git blob OIDs for non-LFS objects.
   Prepared `file_sha256` values cannot substitute for source evidence.
3. Require the exact configured GitHub `origin`, the checked-out local branch named `main` and
   tracking exactly `refs/remotes/origin/main`, a clean whole working tree including untracked
   files, and a full 40-character `HEAD` equal to pushed `origin/main`; bind the immutable draft tag
   target before and after remote verification.
4. Commit prepared archive metadata through one locked, validated atomic manifest replacement.
   Translate internal post-replace durability uncertainty to public `ManifestDurabilityUnknown`
   and retain every already-created archive for explicit reconciliation.
5. Validate `source_audited` as a required nonfuture ISO date distinct from live upstream checks.
6. Require `carry-forward` to name an immutable older `source_release_tag` different from the
   current release tag.
7. Record `rozgo/bge-reranker-v2-m3` cache licensing as `NOASSERTION` and block redistribution;
   only the original BAAI source declares Apache-2.0.

The next independent review required the release path to bind the canonical model and runtime
manifest bytes to both the current files and their exact `HEAD` blobs before network access,
artifact review, and the final remote recheck. It also required the canonical GitHub origin to be
validated before contact; both model-license layers and the complete runtime schema to fail closed;
all six accepted/candidate evidence maps to agree before preparation; Hugging Face metadata and
blob redirects to remain on bounded exact-host HTTPS; model and ORT extraction to enforce bounded
input/output, member-count, per-member, exact-inventory, duplicate, sparse, special-member, and
trailing-data rules; and ORT cache roots to reject lexical aliases and symlink ancestors while
detecting target-directory substitution.

The latest Medium-finding repair makes the no-clobber directory rename an explicit durability
commit point. Runtime and model installers flush published files and directories, both rename
parents, and held cache ancestry before success; postpublication sync uncertainty retains recovery
state and fails the command. Model preparation also enforces initial per-member/cumulative source
bounds before staging and reapplies them during private copying to reject growth.

The subsequent deep review found one High preparation TOCTOU boundary and two Medium failure/resource
boundaries. The repair holds source, staged-file, archive, and validation descriptors across
metadata reads, copying, deterministic archive construction, and completed-archive validation;
classifies postpublication domain validation failures as durability-unknown while preserving the
visible output; and replaces whole-tree materialization/sorting with an incremental inventory capped
at 8,192 entries and 32 relative path components that rejects unexpected entries immediately.

The final cache review found that archive-input verification was not retained as evidence for the
actual extracted output leaves and that a successful atomic rename could remain invisible to its
caller until after helper-local validation. The repair rereads each written leaf and retains its
digest, filesystem identity, size, and mutable state; validates the exact staged inventory before
rename; and reopens and rehashes the exact published inventory during durability synchronization.
The atomic helpers set a caller-owned tracker immediately after the no-clobber syscall commits, so
all later helper, validation, sync, close, and context-exit failures are durability-unknown and keep
the visible output plus private recovery material. Nine focused regressions cover replacement,
same-inode rewrites, helper failures, and inner/outer context exits. The no-external/no-Git gate is
manifest 39/43, central 141/141, runtime 43/43 (184 tests), shell syntax, ShellCheck, Ruff
check/format, and zero basedpyright diagnostics; Git diff checks remain for the root lane.

The next deep review found one High manifest-candidate binding gap and two Medium commit-state
coverage gaps. Atomic manifest replacement now rehashes the held candidate against the exact
prospective bytes and requires stable mutable state before and after exchange, rejecting an
equal-size same-inode rewrite and rolling back to the preserved original. Archive link/rename and
manifest replacement trackers are set at their respective commit boundaries and survive identity
checks, descriptor cleanup, source-context exit, and advisory-lock exit; any later failure is
durability-unknown and reports retained recovery. Six focused regressions were RED with one failure
and five ordinary-error escapes, then GREEN. The complete no-external/no-Git gate is manifest
39/43, central 147/147, runtime 43/43 (190 tests), shell syntax, ShellCheck, Ruff check/format, and
zero basedpyright diagnostics; Git diff checks remain outside this repair lane.

The latest Medium resource-bound repair makes runtime final-output validation incremental: exactly
one expected root library is accepted, and the first unexpected or additional entry is rejected
without consuming the remaining inventory. Runtime and model staging finalizers preserve their
identity-verified recovery roots without recursively enumerating contents that cannot be deleted
safely by identity. Five focused regressions were RED at the former materialization/traversal
boundaries and passed GREEN. The complete no-external/no-Git gate is manifest 39/43, central
153/153, runtime 47/47 (200 tests), shell syntax, ShellCheck, Ruff check/format, and zero
basedpyright diagnostics; Git diff checks remain outside this repair lane.

A prior local gate recorded 94/94 central-plus-platform tests and 23/23 ORT tests, 117 total, plus
the static checks. That evidence predates the newest repairs: publish-time substitution rejection
with original preservation, raw PAX/GNU and negative-size prevalidation, exact rc13-tuple
admission, a 16 MiB release-manifest cap, and a 1 GiB reviewed runtime-payload cap. The root full
gate must be rerun, and final independent specification/security re-review remains pending. The
39/39 manifest audit still validates 43 exact binary payloads, with 21 download/16 provenance/2
refresh statuses, six empty provenance maps per unresolved group, and Rozgo as the sole
`NOASSERTION`; 43 is not by itself a complete publishable-release inventory. The Windows suite
uses a stateful fake to exercise replacement/locking state transitions; native Windows host
qualification has not run, and the helper installer deliberately rejects native Windows before
cache mutation. No model artifacts were downloaded, and release publication remains blocked.

The 2026-09-10 acquisition/preflight repair closes two further Medium review findings. GitHub model
downloads now stream one pattern-selected asset to stdout and write it through a descriptor-relative
exclusive leaf, applying both the signed expected size and absolute archive cap during transfer and
preserving a foreign replacement. Reviewed release admission consumes the exact trusted inventory
incrementally, rejecting unexpected, duplicate, or over-count entries at their first appearance.
Eight focused regressions failed RED and passed 8/8 GREEN. The complete no-external/no-Git gate is
manifest 39/43, central 161/161, runtime 47/47 (208 tests), shell syntax, ShellCheck, Ruff
check/format, and zero basedpyright diagnostics. Fresh independent review remains required.

The subsequent direct-scanner repair closes the remaining Medium resource-bound finding in reviewed
release admission. `Path.iterdir()` had hidden an eager `os.listdir()` call before the otherwise
incremental checks. Admission now owns a context-managed `os.scandir()` iterator directly, accepts
the exact set without list materialization, and closes immediately on the first unexpected,
duplicate, or over-count entry. The four-method RED run failed 4/4 at the eager-list assertion and
passed 4/4 GREEN unchanged; the broader security class passed 129/129. The complete
no-external/no-Git gate is manifest 39/43, central 162/162, runtime 47/47 (209 tests), shell syntax,
ShellCheck, Ruff check/format, and zero basedpyright diagnostics. Git diff and candidate fingerprint
checks remain outside this lane, and fresh independent review remains required.

## Gates

- No network fetch or cache mutation occurs for an unknown checksum or unresolved source revision.
- Archives contain only explicitly declared regular files and safe internal directory structure.
- Hash verification and extraction consume one immutable snapshot of the downloaded archive.
- Existing cache data is never overwritten implicitly.
- A release is never created or partially replaced by validation tooling.
- Exact license, copyright, and notice materials for every canonical cache/original model pair and
  ONNX Runtime 1.28.0 `ThirdPartyNotices.txt` are recovered and audited before publication.
- A notice-delivery mechanism is independently reviewed and accompanies direct downloads without
  altering exact payload bytes; the final publication inventory remains unresolved until then.
- `--apply` records remote candidates without changing the accepted baseline; a remote revision is
  adopted only when its complete candidate provenance is reviewed and accepted with the separate
  explicit `--adopt-current` command before any rebuild.
- The binary payload set is exactly 43 files, with no missing, extra, or digest-mismatched model or
  runtime archive. This payload count does not finalize the publishable-release inventory.
- Publication remains blocked until `VERSION` matches the release tag and the exact pushed commit is
  the unchanged target of the verified draft release.
- All three `current_remote_*` provenance maps are candidate comparison data and never substitute
  for historical archive provenance or explicit reviewed adoption.
- The six accepted/candidate file SHA-256, LFS SHA-256, and Git blob OID maps cover the complete
  declared file set before preparation.
- Preparation is state-gated, and `carry-forward` always points to an older immutable source tag.
- Public `ManifestDurabilityUnknown` preserves all already-created archives after an atomic
  manifest replacement has visible but uncertain durable state.
- Model/runtime directory installation succeeds only after published files and directory commit
  points are flushed; postpublication sync uncertainty preserves the visible recovery tree.
- Model preparation enforces per-member and cumulative logical-byte bounds before staging and at
  each private-copy boundary.
- `source_audited` is a valid, nonfuture source-audit date and never impersonates an upstream check.
- The source/tooling candidate has no assigned closeout version or checkpoint. Recompute both from
  repository state only after final acceptance; the distinct target `v6.0.2` artifact tag and
  GitHub Release do not exist while release gates remain open.

## Non-goals

- Enabling AMD GPU execution in `the-one-mcp`; that requires a separate platform qualification task.
- Publishing a partial `v6.0.2` release while required artifacts remain unavailable.
