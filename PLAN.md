# Plan Index

| Plan | Description | Status | Written | Approved | Last updated |
|---|---|---|---|---|---|
| [FastEmbed 6 and ORT rc13 cache](docs/plans/2026-09-08-fastembed-6-ort-cache.md) | Build a provenance-complete, fail-closed artifact cache for `the-one-mcp` FastEmbed 6.0.2 and `ort-sys` 2.0.0-rc.13. | running | 2026-09-08 | 2026-09-08 | 2026-09-08 |

Michel approved this work directly in the conversation on 2026-09-08. No separate plan is active.

The second-pass repair now binds upload to the canonical manifests and their exact committed bytes,
validates the canonical GitHub origin before contacting it, requires all six accepted/candidate
provenance maps to agree before preparation, rejects lexical aliases and symlink ancestors for ORT
cache roots, constrains Hugging Face metadata/blob responses to bounded exact-host HTTPS, and bounds
model and runtime archive expansion. Descriptor-anchored ORT publication and closed runtime-schema
validation now address the last review's path-race and fail-open admission findings. Newest repairs
also cover publish-time substitution with original preservation, raw PAX/GNU and negative-size
prevalidation, the exact rc13 tuple, and 16 MiB manifest/1 GiB runtime-payload bounds. The prior
94/23/117 test evidence is stale for this final candidate; the root full-gate rerun and final
independent re-review remain pending. Windows platform behavior has a stateful fake but no
native-host result; all model assets and release publication remain blocked.

The tooling-validated payload count remains 43 (39 model plus four runtime), but the final
publication inventory is unresolved. A **High publication blocker** requires exact per-model
cache/original license, copyright, and notice materials plus ONNX Runtime 1.28.0
`ThirdPartyNotices.txt` to be recovered and audited, followed by independent review of a
notice-delivery mechanism that accompanies direct downloads without altering payload bytes.
Those publication blockers do not accept or block the source checkpoint.

Version 6.0.2 is reserved solely for the governance-only checkpoint; it is not assigned to the
dirty, unaccepted source/tooling candidate. Task 3 must recompute the source checkpoint version
after the source-acceptance sequence. Version 6.0.3 is the current expectation, not an assigned
version or a promised tag.

The source-acceptance sequence is: root full gate; real native ORT probe; freeze the ordered
candidate fingerprint; fresh Sol specification/quality and Astra security/architecture reviews;
repairs and re-freeze as required; then source checkpoint commit, tag, and push. Only after that
source checkpoint may publication work proceed; the 21/16/2 artifact-status distribution, Rozgo
`NOASSERTION`, notice delivery, artifact acquisition, and native-host qualification remain
publication blockers.

The governance documentation checkpoint now records the release-asset, schema-v3 provenance, and
platform fail-closed decisions in [docs/adr/](docs/adr/README.md). It does not accept the dirty
source/tooling candidate, close the root gate, or close either independent review.
