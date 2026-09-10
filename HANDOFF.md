# Current Handoff

See [docs/handoffs/2026-09-08-fastembed-6-ort-cache-handoff.md](docs/handoffs/2026-09-08-fastembed-6-ort-cache-handoff.md).

- Repository governance baseline is `de405458` at version 6.0.2 and `checkpoint/6.0.2`; the next
  source-only checkpoint completed as `checkpoint/6.0.3`.
- Source/tooling checkpoint 6.0.3 completed at `a665b9e` and annotated `checkpoint/6.0.3` after
  the 209-test gate, isolated Linux ORT probe, candidate freeze, and independent
  specification/quality plus deep security/architecture approval. Remote `origin/main` and the
  peeled tag resolve to that exact commit.
- Second-pass repairs bind release checks to the canonical committed manifests, validate origin
  before contact, require all six provenance maps before preparation, reject ORT root aliases and
  symlink ancestors, and bound Hugging Face responses plus model/runtime extraction. Newest repairs
  add publish-time substitution/original preservation, raw PAX/GNU and negative-size prevalidation,
  exact rc13-tuple admission, and 16 MiB manifest/1 GiB runtime-payload bounds. The final deep-review
  repair additionally gates runtime publication on a stable held decompressed tar, binds archive
  publication to a bounded no-follow source snapshot and verified output tuple, and retains
  ambiguous/foreign audit and preparation workspaces. The latest repair flushes published
  model/runtime files and directory commit points before success, preserves recovery state on
  postpublication validation/sync uncertainty, and bounds model snapshots before and during
  copying. Preparation now keeps source/stage/archive descriptors authoritative through archive
  validation and incrementally caps inventory at 8,192 entries and 32 path components. The latest
  repair binds every extracted leaf to reread digest/identity/state evidence, verifies the exact
  staged and published inventories, and records rename success inside each atomic helper so every
  later helper/context/sync/close failure is durability-unknown with output preserved. The newest
  repair binds exact prospective manifest bytes and stable mutable state through exchange, records
  archive link/rename and manifest replacement commit points, and translates post-commit identity,
  context, close, rollback, and advisory-lock exit failures to durability-unknown while reporting
  retained recovery. Runtime output validation now scans incrementally, accepts exactly one root
  library, and rejects the first extra entry without consuming an attacker-controlled tail.
  Runtime/model recovery staging is retained after a constant-work root identity check without
  recursive inventory. Reviewed release admission now directly owns a context-managed
  `os.scandir()` iterator instead of materializing `Path.iterdir()` through `os.listdir()`, and
  stops at the first unexpected, duplicate, or over-count entry.
- The current no-external/no-Git local gate is manifest 39/43, central 162/162, runtime 47/47 (209
  total), shell syntax, ShellCheck, Ruff check/format, and basedpyright with zero diagnostics. The
  exact source candidate subsequently passed root-owned diff/fingerprint verification, an isolated
  Linux ORT probe, and fresh independent reviews. The prior `31d401d9…` verdict remains rejected;
  it is historical evidence, not the accepted candidate.
- Source acceptance and checkpoint closeout are complete. Version 6.0.2 remains the
  governance-only checkpoint; `checkpoint/6.0.3` is the source/tooling checkpoint. Publication
  remains a separate blocked task.
- After the source checkpoint, publication remains blocked by the 21 `download-required`, 16
  `provenance-required`, and two `refresh-required` groups; Rozgo `NOASSERTION`; exact
  license/copyright/notice recovery including ONNX Runtime 1.28.0 `ThirdPartyNotices.txt`; reviewed
  notice delivery; artifact acquisition; and native-host qualification. These are publication
  blockers, not source-checkpoint blockers. No model artifact was downloaded.
