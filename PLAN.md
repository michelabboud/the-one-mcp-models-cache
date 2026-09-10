# Plan Index

| Plan | Description | Status | Written | Approved | Last updated |
|---|---|---|---|---|---|
| [FastEmbed 6 and ORT rc13 cache](docs/plans/2026-09-08-fastembed-6-ort-cache.md) | Build a provenance-complete, fail-closed artifact cache for `the-one-mcp` FastEmbed 6.0.2 and `ort-sys` 2.0.0-rc.13. | source-checkpoint closeout in progress; publication blocked | 2026-09-08 | 2026-09-08 | 2026-09-10 |

Michel approved this work directly in the conversation on 2026-09-08. No separate plan is active.

The second-pass repair now binds upload to the canonical manifests and their exact committed bytes,
validates the canonical GitHub origin before contacting it, requires all six accepted/candidate
provenance maps to agree before preparation, rejects lexical aliases and symlink ancestors for ORT
cache roots, constrains Hugging Face metadata/blob responses to bounded exact-host HTTPS, and bounds
model and runtime archive expansion. Descriptor-anchored ORT publication and closed runtime-schema
validation now address the last review's path-race and fail-open admission findings. Newest repairs
also cover publish-time substitution with original preservation, raw PAX/GNU and negative-size
prevalidation, the exact rc13 tuple, and 16 MiB manifest/1 GiB runtime-payload bounds. The prior
94/23/117 test evidence is historical. The newest repair adds durable model/runtime directory
publication and bounded model-source snapshots; its local gate passed 131 central and 38 runtime
tests. The bounded-staging repair incrementally validates the exact one-library runtime output and
retains runtime/model recovery trees without recursive inventory. The newest direct-scanner repair
also removes `Path.iterdir()`'s eager `os.listdir()` materialization from reviewed release
admission; exact, unexpected, duplicate, and over-count inventories are covered. Its local gate
passed 162 central and 47 runtime tests (209 total). The root gate, isolated Linux ORT probe,
candidate freeze, and fresh independent specification/quality plus security/architecture reviews
accepted this exact source candidate for checkpoint closeout. Windows platform behavior has a
stateful fake but no native-host result; all model assets and
release publication remain blocked.

The tooling-validated payload count remains 43 (39 model plus four runtime), but the final
publication inventory is unresolved. A **High publication blocker** requires exact per-model
cache/original license, copyright, and notice materials plus ONNX Runtime 1.28.0
`ThirdPartyNotices.txt` to be recovered and audited, followed by independent review of a
notice-delivery mechanism that accompanies direct downloads without altering payload bytes.
Those publication blockers do not accept or block the source checkpoint.

Version 6.0.2 is reserved solely for the governance-only checkpoint. Source/tooling checkpoint
6.0.3 is assigned after independent approval; it is not the future `v6.0.2` artifact release.

The source-acceptance sequence has completed for this candidate. The remaining source-closeout
steps are commit, annotated `checkpoint/6.0.3` tag, and exact-ref source push. Only after that
source checkpoint may publication work proceed; the 21/16/2 artifact-status distribution, Rozgo
`NOASSERTION`, notice delivery, artifact acquisition, and native-host qualification remain
publication blockers.

The governance documentation checkpoint now records the release-asset, schema-v3 provenance, and
platform fail-closed decisions in [docs/adr/](docs/adr/README.md). It does not accept the dirty
source/tooling candidate, close the root gate, or close either independent review.
