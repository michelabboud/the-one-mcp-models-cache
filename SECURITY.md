# Security Policy

## Supported code and assets

Tooling security fixes land on the current `main` branch. Published tag and asset bytes are
immutable and are never patched in place. If a historical published asset is affected, it is
withdrawn and superseded by a newly reviewed release with new immutable
bytes. No v6 asset tag or GitHub Release currently exists, so no v6 asset release is supported.

## Reporting

Report vulnerabilities privately through GitHub Security Advisories for this repository. Do not
open a public issue containing exploit details, credentials, private URLs, or unpublished artifact
content.

## Scope

In scope: archive verification and extraction, cache installation, manifest/provenance integrity,
release packaging/upload behavior, path handling, and credential exposure by repository tooling.

Release tooling is intentionally fail-closed: it never automates non-atomic multi-asset upload,
never clobbers an asset or local reviewed archive, and never marks a partially uploaded manifest
published. Historical assets without a recovered exact embedded revision are not installable.

Publication also has a **High license/notice blocker**. Exact license, copyright, and notice
materials for every canonical model cache/original repository and ONNX Runtime 1.28.0
`ThirdPartyNotices.txt` must be recovered and audited. An independently reviewed mechanism must
make those notices accompany direct downloads without altering the checksum-pinned binary payload
bytes. The current 43-payload validation does not settle the final publishable-release inventory.

Out of scope: vulnerabilities in upstream models or runtimes that are not caused or amplified by
this repository. Those should be reported to the relevant upstream project, while compatibility or
pinning concerns may also be disclosed here.
