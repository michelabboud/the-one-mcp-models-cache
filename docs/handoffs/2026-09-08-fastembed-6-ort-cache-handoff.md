# FastEmbed 6 and ORT Cache Handoff

## Repository state

The pre-governance `main` began this lane at `7ba0093`; the committed governance baseline is
`71af438` at version 6.0.1 and tag `checkpoint/6.0.1`. FastEmbed 6.0.2 model-cache and ORT rc13
runtime changes remain dirty, unaccepted working-tree changes. Version 6.0.2 is reserved solely
for the governance-only checkpoint, not source/tooling. Task 3 must recompute the source
checkpoint version after source acceptance; 6.0.3 is expected but not assigned.

## Review and model routing

Terra-high is the controller. Sol-xhigh owns risk-bearing source, security, and platform work;
a fresh Sol reviewer performs the specification/quality review. A fresh Astra-xhigh reviewer then
performs the final security/architecture review from the file-based frozen-candidate evidence. That
fresh Astra review is not this exact live Ari session and must independently establish its verdict.

## Verified done

- The public repository and historical `fastembed-v4` release were inspected.
- The active plan and repository baseline were documented.
- The One already pins FastEmbed 6.0.2; the cache repository upgrade is the remaining artifact lane.

## Locally repaired

- Runtime checksum/decompression now consumes one immutable private descriptor and installs with
  atomic no-clobber semantics.
- Model tooling uses strict identifiers, exact revision/file/LFS checks, curated deterministic
  staging, atomic no-clobber installs, and one locked validated manifest transaction.
- Release upload is separated from preparation and intentionally manual; preflight and remote
  digest verification require the complete reviewed binary payload set, matching git origin, and
  exact draft tag.
- Schema v3 separates original-model from conversion/cache-repository licensing and provenance;
  an in-repository FastEmbed 6.0.2 fixture covers all represented registry mappings.
- The two GTE records preserve their exact baseline tag, recorded version, declared MiB size, and
  SHA-256 in non-installable `legacy_archive_*` fields. Current v6 revision/size/hash fields stay
  blank and `refresh-required`.
- `last_upstream_check` is honestly empty because no complete current Hugging Face audit occurred;
  the baseline's 2026-04-04 date is retained separately as `legacy_manifest_last_checked`.
- Every model has six upstream/current provenance maps: file SHA-256, LFS SHA-256, and non-LFS Git
  blob OID maps. The three `current_remote_*` maps are candidates only; they never supply historical
  provenance or bypass explicit reviewed-baseline adoption.
- The tooling-validated binary payload set combines all 39 model archives with the four required
  ORT `release_asset` entries, exactly 43 payloads bound to the clean pushed commit and immutable
  draft tag target. This count does not finalize the publishable-release inventory.
- Implementers report a 135/135 local cache-candidate test run. That report is implementation
  evidence only: the cache root full-gate rerun and the fresh independent specification/security
  reviews remain pending.

## Final-review findings and repair evidence

The current repair responds to review findings in seven connected areas: upstream-change
invalidation and explicit adoption; combined model/runtime binary-payload preflight; immutable
source binding; race-aware full dry audit and selection preflight; canonical roots plus
Windows-equivalent locking/replacement; GTE legacy/current provenance separation and honest audit
dating; and manifest-mode preservation.

The second review found additional gaps: preparation was not sufficiently state-gated;
required-file source bytes lacked independent baseline/candidate SHA-256 and non-LFS Git blob
identity; release binding did not require the exact origin, main branch, full 40-character SHA, and
whole-tree cleanliness; uncertain post-replace durability could discard recoverable archives;
`source_audited` was not validated; and carry-forward did not require an older source tag. The
Rozgo BGE-reranker-v2-m3 conversion repository also has no declared license metadata.

The next independent review required canonical model/runtime manifest bytes to match both the
current files and exact `HEAD` blobs throughout release verification, and required the canonical
GitHub origin to be validated before any contact. It also found fail-open license/schema admission,
incomplete six-map preparation, unbounded or insufficiently exact model/ORT extraction, permissive
Hugging Face metadata redirects, and normalized rather than rejected ORT root aliases. The
second-pass repair closes those paths with adversarial RED/GREEN tests.

The newest repair rejects publish-time payload substitution while preserving the validated
original, prevalidates raw PAX/GNU extension records and negative sizes, requires the exact rc13
tuple, caps release manifests at 16 MiB, and caps reviewed runtime payloads at 1 GiB before their
private snapshot copy. Implementers report 135/135 local tests for the current candidate, but the
root full gate has not rerun it and no fresh independent specification/security review has approved
that frozen candidate. Manifest audit still covers 39/39 groups and 43 exact binary payloads: 21 are download-required, 16
provenance-required, and 2 refresh-required; all six provenance maps are empty for every unresolved
group; Rozgo is the sole `NOASSERTION`. The helper installer deliberately rejects native Windows
before cache mutation. A read-only native Linux x86_64 real-archive probe is recorded below;
macOS and Windows coverage is simulated only and both require real-host qualification. No model
artifact was downloaded, and publication remains blocked.

The remaining **High publication blocker** is publication licensing and notice delivery. Recover
and audit the exact license, copyright, and notice materials for every canonical model
cache/original repository and ONNX Runtime 1.28.0 `ThirdPartyNotices.txt`, then define and
independently review a mechanism that accompanies direct downloads without altering model/runtime
payload bytes. Whether that mechanism adds a separate release item is unresolved, so the final
publication inventory is not yet known. This does not block source acceptance.

A separate read-only real-archive probe used the operator-provided Linux x86_64 ORT archive from
outside the repository. It installed exactly one 105,481,448-byte `libonnxruntime.a` at the
manifest-bound digest path inside a new isolated `/tmp` cache. The 101 MiB test cache was removed
and its absence verified after the probe; the source archive was not modified.

## Next steps

Source acceptance must proceed in this exact order:

1. Run the root full gate.
2. Run the real native ORT probe.
3. Freeze the ordered candidate fingerprint.
4. Obtain fresh Sol specification/quality and Astra security/architecture reviews of that frozen
   candidate.
5. Repair every finding, then re-freeze and repeat the required reviews whenever the candidate
   changes.
6. Recompute the source checkpoint version in Task 3, then commit, tag, and push the source
   checkpoint. Version 6.0.3 is expected but not assigned.

Only after the source checkpoint may publication work proceed. Publication remains blocked by the
21 `download-required`, 16 `provenance-required`, and two `refresh-required` groups; Rozgo
`NOASSERTION`; exact cache/original license, copyright, and notice recovery including ONNX Runtime
1.28.0 `ThirdPartyNotices.txt`; independently reviewed notice delivery without payload mutation;
artifact acquisition; and native-host qualification. Recover exact `refs/main` revisions from all
16 verified historical release archives without substituting current Hugging Face HEAD. Obtain,
pin, and verify the 21 new plus two refreshed GTE artifact groups outside git, and keep the Rozgo
BGE-reranker-v2-m3 ONNX export blocked until redistribution rights are independently established.
These are publication blockers, not source-checkpoint blockers.

### Schema expectations to integrate

- Accept an empty `meta.last_upstream_check`; when nonempty it remains a valid nonfuture UTC date.
- A successful complete current `check-updates.sh --apply` transaction records the candidate
  revision, timestamp, and three `current_remote_*` provenance maps without adopting the accepted
  baseline, and writes today's UTC date. Failed, partial, or model-filtered checks do not advance
  the global date.
- Preserve `meta.legacy_manifest_last_checked` as historical evidence only.
- Require all six provenance maps on all 39 model records. The three upstream/current pairs are
  file SHA-256, LFS SHA-256, and non-LFS Git blob OID; unresolved records keep all six empty.
- Validate the five GTE `legacy_archive_*` fields as immutable, non-installable evidence and forbid
  them from satisfying current `refresh-required` revision, size, or SHA requirements.
- Derive binary-payload preflight from exactly 39 model asset names plus four required runtime
  `release_asset` names; exclude `future_archives` and `optional_archives`. Do not treat the 43
  payloads as a complete publishable-release inventory until notice delivery is designed and
  independently reviewed.
- Bind any publication verification to matching `VERSION` and the unchanged draft-tag target
  before and after remote verification, together with the exact Git constraints below.
- Require preparation status to be exactly `download-required` or `refresh-required` with complete
  accepted source evidence.
- Cover every required file with all six accepted/candidate provenance maps; archive payload hashes
  are a separate evidence layer.
- Require exact configured origin, the checked-out local branch named `main` and tracking exactly
  `refs/remotes/origin/main`, whole-tree cleanliness including untracked files, and equality of full
  40-character `HEAD` and pushed `origin/main`.
- Commit archive metadata through one locked, validated atomic manifest replacement. Translate an
  internal post-replace sync failure to public `ManifestDurabilityUnknown`, retain all archives
  already created by the transaction, and reconcile the visible manifest state explicitly.
- Validate `source_audited` as a required nonfuture ISO date distinct from upstream-check dating.
- Require every `carry-forward` entry to reference an older immutable source tag, never the current
  target tag.
- Treat the Rozgo BGE-reranker-v2-m3 conversion license as `NOASSERTION` and block redistribution;
  the original BAAI model's official Apache-2.0 license does not cover the separate export.

## Boundaries

No user, project, or MAI database may be accessed. Large cache/runtime artifacts stay outside git.
No partial release is authorized. Version 6.0.2 is governance-only and does not assign or accept a
source/tooling candidate. Task 3 must recompute the source checkpoint version after the required
source-acceptance sequence; 6.0.3 is expected but unassigned. Do not create an artifact tag or
GitHub Release until every artifact, provenance, license, notice-delivery, verification, and review
gate has closed.
