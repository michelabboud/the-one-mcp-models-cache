# ONNX Runtime 1.32.0 — x86_64 Linux native libraries

Why this exists: FastEmbed 7.1.2 to 7.7.0 use `ort`/`ort-sys` 2.0.0-rc.15, which needs ONNX
Runtime 1.31 or newer. ort-sys downloads its prebuilt from `cdn.pyke.io`, and that CDN's Cloudflare
firewall blocked this host on 2026-11-14 ("Sorry, you have been blocked"). Microsoft's releases ship
only shared libraries, while the-one-mcp release binaries link ONNX Runtime statically.

Two artifacts, both recorded in `manifest.toml` with SHA-256:

- **Static, self-built, no telemetry.** Built from the official 1.32.0 source with `--no_telemetry`.
  ONNX Runtime 1.32's build enables Microsoft 1DS telemetry by default for native builds; a first
  build without the flag bundled the 1DS client, libcurl, mbedTLS and the
  `mobile.events.data.microsoft.com` collector, and was rejected.
- **Shared, Microsoft's official `onnxruntime-linux-x64-1.32.0.tgz`**, byte-identical to the GitHub
  release asset (digest verified). Kept for a possible move to dynamic linking.

Use the static one with `ORT_LIB_LOCATION=<extracted dir>/lib`. Local copies on the build host:
`~/.fastembed_cache/ort-archives/` (archives) and
`~/.fastembed_cache/ort-libs/onnxruntime-1.32.0-x86_64-unknown-linux-gnu/` (extracted, with
`SHA256SUMS`). ONNX Runtime is MIT licensed; its license and third-party notices travel inside the
source tree it was built from.

Status: published 2026-11-14 as GitHub release `ort-1.32.0` on the owner's word ("publish ort-1.32.0"); both assets re-downloaded and verified against the SHA-256 above.
