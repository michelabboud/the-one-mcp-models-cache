# Backlog

- 2026-09-08 — FastEmbed 6 / ORT cache final review — `running`: second-pass repairs bind upload to
  the canonical committed manifests, validate origin before contact, enforce six-map preparation,
  reject ORT cache-root aliases/symlink ancestors, and bound upstream responses plus model/runtime
  extraction. Descriptor-anchored ORT publication and complete runtime-schema/framing validation
  close earlier review findings. The newest security repair adds publish-time substitution/original
  preservation, raw PAX/GNU and negative-size prevalidation, exact rc13-tuple admission, and
  16 MiB manifest/1 GiB runtime-payload bounds. Implementers report a 135/135 local test run for
  the current candidate; it is not root-owned evidence. The root full-gate rerun and final
  independent re-review remain.
- 2026-09-08 — v6 publication notices — **High**, `blocked`: recover and audit exact per-model
  cache/original license, copyright, and notice materials plus ONNX Runtime 1.28.0
  `ThirdPartyNotices.txt`. Define and independently review a notice-delivery mechanism that
  accompanies direct downloads without altering model/runtime payload bytes. The tooling still
  validates exactly 43 binary payloads, but whether notice delivery adds a separate release item is
  unresolved; the final publishable-release inventory cannot be declared yet.
- 2026-09-08 — Rozgo BGE-reranker-v2-m3 cache license — `blocked`: the official conversion page
  declares no license metadata. Keep the cache layer `NOASSERTION` and do not redistribute it until
  its rights are independently established; the original BAAI Apache-2.0 declaration is not a
  license for the separate ONNX export.
- 2026-09-08 — secure native Windows installer and qualification — `blocked`: implement
  Windows-equivalent no-follow traversal, no-clobber publication, manifest locking, and atomic
  replacement, then run the complete suite on a real Windows host. The current helper deliberately
  fails before cache mutation on Windows; the stateful fake is regression evidence, not native-host
  support or qualification.
- 2026-09-08 — FastEmbed 6 / ORT cache plan — `open`: obtain and independently verify every new
  model archive and all four required ONNX Runtime archives before publishing. These are exactly
  43 binary payloads; final publication inventory remains separately blocked on reviewed notice
  delivery. Future Windows ARM64 and optional Linux WebGPU records are outside the payload set.
- 2026-09-08 — FastEmbed 6 / ORT cache plan — `open`: decide whether to enable and qualify a GPU
  execution provider in `the-one-mcp`; the current AMD eGPU is intentionally CPU-only.
- 2026-09-08 — Repository baseline — `open`: add CI after the local validation surface stabilizes;
  until then every checkpoint must run the documented local gate.
