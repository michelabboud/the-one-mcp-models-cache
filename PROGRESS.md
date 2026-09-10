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
ONNX Runtime rc13 bootstrap completed source checkpoint 6.0.3 at commit `a665b9e`, annotated tag
`checkpoint/6.0.3`, and pushed `origin/main`. It remains unpublished: the 6.0.2 artifact release
is separately blocked by provenance, licensing, notices, asset acquisition, and native-host
qualification.

The source-acceptance order completed as root full gate; real native ORT probe; ordered
candidate-fingerprint freeze; fresh Sol specification/quality and Astra security/architecture
reviews; checkpoint commit; annotated tag; and source push. The historical `fastembed-v4`
release remains the only model-asset release. The 21 `download-required`, 16
`provenance-required`, and two `refresh-required` groups; Rozgo `NOASSERTION`; exact
license/copyright/notice recovery and notice delivery; artifact acquisition; and native-host
qualification are publication blockers only, not source-checkpoint blockers. The helper installer
supports Linux/macOS only and deliberately fails before cache mutation on native Windows. Its
current Windows platform evidence is a stateful fake, not native support or a native-host test. No
model artifact was downloaded during this repair.

## 2026-09-09 final deep-review repair

- The deep review of composite `31d401d9a33aa5f3319c5a950557dc94ed8f76b5283600997f0ff2b1f2367f1a`
  withheld approval on three High transaction findings: the decompressed tar was checked only after
  runtime publication; archive publication reopened a pathname without binding the published bytes
  to the reviewed size and digest; and `command_sync` delegated workspace teardown to recursive
  `TemporaryDirectory` cleanup that could delete a foreign replacement.
- The repair rechecks the held tar before the no-clobber rename; snapshots archive sources with
  bounded `O_NONBLOCK`/`O_NOFOLLOW` reads and verifies the held output against the expected size and
  SHA-256 before linking; and conservatively retains both audit and preparation workspaces rather
  than performing an unconditioned recursive pathname deletion.
- Focused RED was one assertion failure plus four errors across five regressions, including a
  separately added audit-command replacement case. The same five are GREEN after the repair. The
  complete local gate is manifest 39 groups / 43 binary payloads, central 124/124, runtime 36/36
  (160 tests total), shell syntax, ShellCheck, Ruff check/format,
  basedpyright with zero diagnostics, and `git diff --check`.
- The prior review verdict remains rejected for its exact fingerprint; this repair creates a new
  candidate and does not self-approve it. A fresh fingerprint is recorded in the active SDD ledger,
  and independent specification/quality plus security/architecture re-review remain required. The
  real native archive probe was not rerun because this repair lane forbids external cache mutation.
  No network, artifact download, database action, commit, tag, push, upload, or release occurred.

## 2026-09-09 cache durability and snapshot bounds repair

- Closed two Medium review findings without expanding publication scope. Runtime and model installs
  now flush each published regular file, the installed directory tree, both rename parents, and the
  held cache ancestry before returning success. A failure after the no-clobber rename is reported as
  durability-unknown; the visible output and private recovery material remain for reconciliation.
- `snapshot_cache_artifact` now rejects an initially oversized member or cumulative required-file
  payload before it creates staging. Each subsequent private copy also receives the remaining
  per-member/cumulative bound, so a source that grows after initial inventory cannot overrun the
  accepted budget.
- Focused RED was four test methods with four failures and one missing-class error. The unchanged
  four-method selection then passed GREEN. The complete local gate passed manifest 39/43, central
  131/131, runtime 38/38 (169 total), shell syntax, ShellCheck, Ruff check/format, basedpyright with
  zero diagnostics, and staged/unstaged diff checks.
- This repair is not candidate acceptance. Fresh independent specification/quality and
  security/architecture review remain required. No network, external cache mutation, artifact
  download, database action, commit, tag, push, upload, or release occurred.

## 2026-09-09 descriptor-bound preparation repair

- Closed one High and two Medium deep-review findings. Preparation now keeps held descriptors for
  cache ancestry, `refs/main`, required source files, staged files, the archive parent, and the
  validation tree through metadata reads, copy, deterministic archive construction, and completed
  archive validation. It performs no authoritative preparation write, chmod, or validation through
  a replaceable child pathname.
- Replaced the unbounded `os.walk` materialization/sort with incremental descriptor-relative
  inventory. Admission is capped at 8,192 entries and 32 relative path components, and the first
  unexpected entry is rejected without consuming the rest of the untrusted iterator.
- Model `CacheError` and runtime `InstallerError` raised after publication now join operating-system
  failures in the public durability-unknown classification. Visible installed output and recovery
  staging remain available for explicit reconciliation.
- Focused RED selected five methods and exited 1 with four failures and two errors. The final
  exact-site tightening separately reproduced two leaked postpublication domain errors before both
  passed GREEN. The final eight-method focused selection, including inherited byte-bound checks and
  held-stage pathname substitution, passed GREEN. The complete local gate passed manifest 39/43,
  central 136/136,
  runtime 39/39 (175 total), shell syntax, ShellCheck, Ruff check/format, basedpyright with zero
  diagnostics, and staged/unstaged diff checks.
- This repair creates another unaccepted candidate. Fresh independent specification/quality and
  security/architecture review remains required. No network, external cache mutation, artifact
  download, database action, commit, tag, push, upload, or release occurred.

## 2026-09-09 extracted-output binding and publication-state repair

- Closed the final High and Medium cache-review findings. Runtime and model extraction now retain
  digest, filesystem identity, size, and mutable-state evidence captured by rereading each written
  output leaf. Both installers validate the exact final staged inventory against that evidence
  before the no-clobber rename and reopen and rehash the exact published inventory before accepting
  durability.
- Each atomic rename helper now sets a caller-owned publication tracker immediately after its
  no-clobber syscall succeeds, before any helper-local post-rename validation. Every subsequent
  helper, validation, synchronization, descriptor-close, and nested or outer context-exit failure
  is classified as durability-unknown. Visible output and private recovery state remain intact for
  explicit reconciliation.
- Eight focused model/runtime methods were RED before implementation: four output replacement or
  same-inode rewrite attacks reached publication, while four post-rename helper/context failures
  escaped with ordinary retry-safe errors. A ninth RED proved the outer model cache-root context
  could also leak an ordinary error after publication. All nine are GREEN after the repair.
- The complete no-external/no-Git local gate passed manifest 39/43, central 141/141, runtime 43/43
  (184 tests total), shell syntax, ShellCheck, Ruff check/format, and basedpyright with zero
  diagnostics. Git diff checks were intentionally excluded by the lane's no-Git boundary.
- This repair creates another unaccepted candidate. Fresh independent specification/quality and
  security/architecture review remains required. No network, external cache mutation, artifact
  download, database action, Git mutation, upload, or release occurred.

## 2026-09-10 bounded staging-inventory repair

- A fresh deep review withheld approval on one Medium resource-bound finding. Runtime final-output
  validation materialized an attacker-controlled directory before enforcing its exact
  single-library contract, while runtime and model staging finalizers recursively inventoried
  recovery trees that could not be deleted safely by identity.
- Five focused regressions were RED at the three runtime validation and two retained-staging
  `os.listdir` boundaries. GREEN incrementally consumes the runtime root, rejects the first
  unexpected entry or any second entry immediately, and closes its scanner. Runtime/model staging
  now verifies the owned root identity and preserves it without descending into its contents.
- The complete no-external/no-Git local gate passed manifest 39 groups / 43 binary payloads;
  central 153/153; runtime 47/47; total 200/200; shell syntax, ShellCheck, Ruff check/format, and
  basedpyright with zero diagnostics. Git diff and candidate fingerprint checks were intentionally
  excluded by the assigned lane.
- This repair creates another unaccepted candidate. Fresh independent specification/quality and
  security/architecture review remain required before source-checkpoint closeout. No network,
  external cache mutation, artifact download, database action, Git mutation, upload, or release
  occurred.

## 2026-09-10 manifest and archive transaction-state repair

- Closed one High and two Medium deep-review findings. Atomic manifest replacement now hashes the
  held temporary descriptor against the prospective content and requires stable mutable state
  around both pre-exchange and post-exchange reads. An equal-size in-place rewrite at exchange is
  rejected; successful rollback restores the original and retains the rejected candidate.
- Archive publication records a successful descriptor link or no-clobber rename inside the helper
  at the syscall boundary. Post-commit identity checks, output/source context exits,
  synchronization, descriptor cleanup, and failed rollback now become
  `PlatformFileDurabilityUnknown`, with the visible release-named output reported as recovery.
  Manifest update separately records a successful replacement return before advisory-lock exit, so
  a later lock-release failure becomes `ManifestDurabilityUnknown` and preserves prepared archives.
- Six focused regressions were RED with one assertion failure and five ordinary-error escapes. All
  six passed GREEN. Two inherited rollback-failure tests were tightened to the same committed-state
  contract. The complete no-external/no-Git gate passed manifest 39/43, central 147/147, runtime
  43/43 (190 tests total), shell syntax, ShellCheck, Ruff check/format, and basedpyright with zero
  diagnostics. Git diff checks were intentionally excluded by the lane boundary.
- This repair creates another unaccepted candidate. Fresh independent specification/quality and
  security/architecture review remains required. No network, external cache mutation, artifact
  download, database action, Git mutation, upload, or release occurred.

## 2026-09-10 bounded acquisition and reviewed-inventory repair

- Closed two Medium acquisition/preflight findings. Model downloads no longer give `gh` a staging
  pathname or `--clobber`; the subprocess emits the one exact asset to stdout while the tool writes
  through a descriptor-relative `O_EXCL` leaf. The signed expected size and 8 GiB absolute cap are
  checked before launch and during transfer, with an extra byte detected before it is written.
- A preexisting leaf blocks launch. A replacement raced over the held output is detected by
  filesystem identity and retained, never unlinked by pathname. The subsequent archive snapshot
  remains the independent size/SHA-256 admission boundary.
- Reviewed release admission now bounds the untrusted directory scan to the trusted inventory
  cardinality—43 files for the repository candidate—and immediately rejects the first unexpected,
  duplicate, or over-count entry. Missing files still fail before any GitHub access.
- Focused RED was eight methods: three expected assertion failures and five expected errors. The
  unchanged selection passed 8/8 GREEN, and the broader security class passed 128/128. The complete
  no-external/no-Git local gate passed manifest 39/43, central 161/161, runtime 47/47 (208 total),
  shell syntax, ShellCheck, Ruff check/format, and basedpyright with zero diagnostics.
- This source/test/documentation change creates another unaccepted candidate. Fresh independent
  specification/quality and security/architecture review remain required before source-checkpoint
  closeout. No network, external cache mutation, artifact download, database action, Git mutation,
  upload, or release occurred.

## 2026-09-10 direct reviewed-artifact scanner repair

- Closed the remaining Medium resource-bound finding in `_reviewed_artifacts`. The prior
  `Path.iterdir()` loop looked incremental but `pathlib` implemented it with eager `os.listdir()`,
  materializing an attacker-controlled release directory before the first admission check.
- Four focused regressions cover exact-set acceptance and immediate unexpected, duplicate, and
  over-count rejection. All four forbid `os.listdir`; the three synthetic invalid streams also
  prove the context-managed scanner closes without consuming their tail. RED failed 4/4 at the
  eager-list boundary; the unchanged selection passed 4/4 GREEN after switching to direct
  `os.scandir()`.
- The broader security class passed 129/129. The complete no-external/no-Git local gate passed
  manifest 39/43, central 162/162, runtime 47/47 (209 total), shell syntax, ShellCheck, Ruff
  check/format, and basedpyright with zero diagnostics. Git diff and whole-candidate fingerprint
  checks were intentionally excluded by the assigned lane.
- This repair creates another unaccepted candidate. Fresh independent specification/quality and
  security/architecture review remain required before source-checkpoint closeout. No network,
  external cache mutation, artifact download, database action, Git mutation, upload, or release
  occurred.
