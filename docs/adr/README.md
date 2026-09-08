# Architecture Decision Records

Architecture decisions are numbered and append-only. A later decision supersedes an earlier one;
it does not rewrite the historical record.

| ADR | Decision | Status |
|---|---|---|
| [0001](0001-release-assets-not-git-blobs.md) | Store model and runtime payloads as release assets, not Git blobs. | Accepted 2026-09-08 |
| [0002](0002-schema-v3-provenance-adoption-and-release-binding.md) | Use schema v3 six-map provenance, explicit adoption, and immutable release binding. | Accepted 2026-09-08 |
| [0003](0003-platform-fail-closed-transactional-publication.md) | Keep publication transactional and fail closed by platform qualification. | Accepted 2026-09-08 |

Add a new `NNNN-slug.md` record when a decision has viable alternatives, substantial reversal
cost, or a non-obvious rejected option. Every record includes Context, Decision, Alternatives
rejected, Consequences, and Status.
