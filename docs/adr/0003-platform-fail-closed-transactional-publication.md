# ADR 0003: Keep publication transactional and fail closed by platform qualification

**Status:** Accepted — 2026-09-08

## Context

Archive installation and manifest publication must preserve verified bytes, avoid clobbering an
existing cache, and expose uncertain durability rather than guessing. Security-sensitive
filesystem semantics differ by operating system. The current evidence includes a read-only native
Linux x86_64 real-archive probe, while macOS and Windows coverage is simulated and neither has a
real-host qualification result.

## Decision

Use no-clobber archive creation, locked validated atomic manifest replacement, and explicit
reconciliation when post-replace durability is uncertain. If a replacement becomes visible but
directory sync cannot prove durability, surface `ManifestDurabilityUnknown` and retain already
created archives for inspection; do not auto-clean up the potentially recoverable evidence.

Treat native platform support as fail closed until verified on a real host. Native Linux evidence
is limited to the recorded isolated real-archive probe. macOS and Windows behavior remains
simulated pending real-host qualification; neither simulation is evidence that native semantics
are safe. The helper installer must continue to reject native Windows before cache mutation until
equivalent secure traversal, locking, and atomic replacement behavior is both implemented and
qualified.

## Alternatives rejected

- **Treat cross-platform unit fakes as native qualification:** rejected because they cannot prove
  host filesystem, locking, and replacement behavior.
- **Roll back or delete archives automatically after uncertain durability:** rejected because it
  can discard the only recoverable copy while the visible manifest state needs reconciliation.
- **Allow best-effort platform installation after an unsupported path:** rejected because cache
  mutation without platform-qualified transactional semantics weakens the trust boundary.

## Consequences

Linux probe evidence, macOS simulation, and Windows simulation must be reported as separate
evidence states. A native macOS host run and a native Windows host run remain blockers; Windows
helper support is not advertised. Manual multi-asset publication remains non-atomic at GitHub, so
the repository verifies the complete reviewed set and immutable source binding before and after
manual upload rather than claiming an atomic remote upload transaction.
