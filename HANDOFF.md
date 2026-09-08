# Current Handoff

See [docs/handoffs/2026-09-08-fastembed-6-ort-cache-handoff.md](docs/handoffs/2026-09-08-fastembed-6-ort-cache-handoff.md).

- Repository governance baseline `71af438` is version 6.0.1 at `checkpoint/6.0.1`.
- Second-pass repairs bind release checks to the canonical committed manifests, validate origin
  before contact, require all six provenance maps before preparation, reject ORT root aliases and
  symlink ancestors, and bound Hugging Face responses plus model/runtime extraction. Newest repairs
  add publish-time substitution/original preservation, raw PAX/GNU and negative-size prevalidation,
  exact rc13-tuple admission, and 16 MiB manifest/1 GiB runtime-payload bounds. Implementers
  report a 135/135 local test run for the current candidate, but it is not root-owned evidence;
  the root full-gate rerun and final independent re-review are pending.
- Resume source acceptance in this exact order: root full gate; real native ORT probe; ordered
  candidate-fingerprint freeze; fresh Sol specification/quality and Astra security/architecture
  reviews; repairs and re-freeze as needed; then source checkpoint commit, tag, and push. Version
  6.0.2 is reserved for the governance-only checkpoint; the dirty source remains unaccepted. Task
  3 recomputes the source checkpoint version, with 6.0.3 expected but not assigned.
- After the source checkpoint, publication remains blocked by the 21 `download-required`, 16
  `provenance-required`, and two `refresh-required` groups; Rozgo `NOASSERTION`; exact
  license/copyright/notice recovery including ONNX Runtime 1.28.0 `ThirdPartyNotices.txt`; reviewed
  notice delivery; artifact acquisition; and native-host qualification. These are publication
  blockers, not source-checkpoint blockers. No model artifact was downloaded.
