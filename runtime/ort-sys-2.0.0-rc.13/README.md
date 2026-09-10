# ONNX Runtime native cache for ort-sys 2.0.0-rc.13

This directory describes byte-for-byte mirrors of the Pyke native archives selected by
`ort-sys` 2.0.0-rc.13 (`ONNX Runtime` 1.28.0). These are executable native runtime artifacts,
not model weights. They therefore use their own manifest and versioned asset-name prefix even
though the repository's intended future GitHub Release tag is `v6.0.2`. That tag and release do
not currently exist.

No runtime archive is stored in git. The intended GitHub Release assets and the original Pyke
URLs and SHA-256 values are recorded in [manifest.toml](manifest.toml).

## Intended v6 release set

| Rust target | ort-sys feature set | Provider | SHA-256 cache key |
|---|---|---|---|
| `x86_64-unknown-linux-gnu` | `none` | CPU | `e454f710...05fd68` |
| `aarch64-unknown-linux-gnu` | `none` | CPU | `06a050ab...44b35a` |
| `aarch64-apple-darwin` | `coreml` | CoreML | `6934874e...9674c7` |
| `x86_64-pc-windows-msvc` | `directml` | DirectML | `f7c654b3...0b527d` |

The Windows x86-64 row is authoritative binary-payload metadata, not a claim that the helper
installer supports native Windows. `scripts/install-ort-runtime.py` currently supports Linux and
macOS only and deliberately fails before cache mutation on native Windows. A secure Windows
installation implementation and real-host qualification are still blocked work.

`aarch64-pc-windows-msvc` + DirectML is retained under `[[future_archives]]` until it can be
validated on a suitable host. The-One currently builds that target with local embeddings disabled,
and this repository has no native Windows ARM64 host qualification. Pyke publishes no
`x86_64-apple-darwin` row for this ort-sys version; this is recorded under
`[[unavailable_targets]]` rather than represented by a fake fallback.

Pyke also publishes an optional Linux x86_64 WebGPU build:

- URL:
  <https://cdn.pyke.io/0/pyke:ort-rs/ms@1.28.0/x86_64-unknown-linux-gnu+webgpu.tar.lzma2>
- SHA-256: `68406bc32de516ee8baeaa4c5f2de2bb0031269f19ce8b76d64988c0498b93be`
- Cache destination:
  `${ORT_CACHE_DIR}/dfbin/x86_64-unknown-linux-gnu/68406bc32de516ee8baeaa4c5f2de2bb0031269f19ce8b76d64988c0498b93be/`

This build may matter for AMD eGPU experiments, but `the-one-mcp` does not enable ort-sys's
`webgpu` feature today. It is recorded under `[[optional_archives]]` for provenance and future
evaluation; it is not an intended v6 binary payload dependency and the installer intentionally
accepts only the four `[[archives]]` entries.

## Provenance and integrity

The archive URLs and hashes come from the packaged `ort-sys` 2.0.0-rc.13
`build/download/dist.tsv`, whose crate source commit is
`002f41a8e175eac7f6695ff361d2e51a50874c48`. The installed table used to prepare this manifest
has SHA-256 `c706a8bf67367fbec3ad7851d9b119f8830fbabe53696e20f4740131f7f59e78`.

Release assets must remain byte-for-byte copies of the source archives. Do not unpack and
recompress them: `ort-sys` uses the compressed archive SHA-256 both as an integrity check and as
the final cache-directory name.

The archives use a tar stream wrapped in raw LZMA2 with a 64 MiB dictionary. The build script
extracts the selected archive to:

```text
${ORT_CACHE_DIR}/dfbin/<Rust target>/<archive SHA-256>/
```

## Installing an already downloaded release asset

After the `v6.0.2` assets have actually been published, download the matching target from GitHub
rather than the Pyke CDN:

```bash
gh release download v6.0.2 \
  -R michelabboud/the-one-mcp-models-cache \
  -p 'onnxruntime-1.28.0-ort-sys-2.0.0-rc.13-x86_64-unknown-linux-gnu.tar.lzma2'
```

Set `ORT_CACHE_DIR` explicitly to the same absolute, lexically canonical, symlink-free directory
that Cargo will see, then run:

```bash
export ORT_CACHE_DIR="/absolute/path/to/ort.pyke.io"
python3 scripts/install-ort-runtime.py \
  --archive /path/to/onnxruntime-1.28.0-ort-sys-2.0.0-rc.13-x86_64-unknown-linux-gnu.tar.lzma2 \
  --target x86_64-unknown-linux-gnu \
  --feature-set none
```

For macOS use `--feature-set coreml`. Do not use this helper to install the Windows DirectML
archive: native Windows installation is not implemented and fails closed before cache mutation.
The script requires Python 3.11+, performs no download, rejects an
unset/relative/root/aliased `ORT_CACHE_DIR` and every symlink ancestor, verifies the authoritative
SHA-256 before making any cache directory, and detects target-directory substitution. Compressed
input, decompressed output, member count, per-member and cumulative logical size are bounded. The
installer rejects traversal, duplicate normalized names, sparse/symlink/hardlink/special members,
trailing compressed data, and every file other than the single expected root library. Extraction
is staged on the destination filesystem and a pre-existing hash directory is never replaced.
The manifest loader also requires the exact supported rc13 tuple, including `ort-sys`
2.0.0-rc.13, its pinned source commit and distribution-table digest, ONNX Runtime 1.28.0, the raw
LZMA2 format and 64 MiB dictionary, and the canonical repository/tag/URL/license/cache-template
metadata.

## Publication boundary

The metadata does not prove that an asset has been mirrored, uploaded, or tested on its target
operating system. Before publishing, obtain each byte-identical archive from a network that can
reach Pyke, independently verify its SHA-256 against the manifest, upload it under the exact
`release_asset` name to `v6.0.2`, and disclose that the pinned ort-sys dependency is a release
candidate. The Windows asset must not be advertised as installable through this helper until its
secure native implementation and qualification are complete. No Pyke CDN archive was downloaded
while preparing these files.

Publication is also blocked until the exact ONNX Runtime 1.28.0 `ThirdPartyNotices.txt` material is
recovered and audited and an independently reviewed notice-delivery mechanism accompanies direct
downloads without changing these byte-identical runtime payloads. Whether that mechanism adds a
separate release item is unresolved; the final publishable inventory therefore remains
unresolved.

## License

ONNX Runtime 1.28.0 is Copyright Microsoft Corporation and licensed under the MIT License. See
[LICENSE](LICENSE) and [ATTRIBUTION.md](ATTRIBUTION.md). Pyke/ort is the build distributor and
manifest source; the `ort-sys` crate itself is licensed `MIT OR Apache-2.0`.
