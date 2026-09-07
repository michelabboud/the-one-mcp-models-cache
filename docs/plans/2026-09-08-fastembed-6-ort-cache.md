# FastEmbed 6.0.2 and ORT rc13 Cache Plan

**Status:** Running

**Written:** 2026-09-08

**Approved:** 2026-09-08 by Michel in the active conversation

**Last updated:** 2026-09-08

## Goal

Provide `the-one-mcp` with an independently auditable, offline-capable cache for every FastEmbed
6.0.2 model artifact it advertises and every ONNX Runtime rc13 target needed by its supported
release matrix.

## Tasks

1. Establish the repository governance and security baseline as version 6.0.1.
2. Map all FastEmbed 6.0.2 variants to unique Hugging Face cache artifacts and exact required files.
3. Carry forward only historical archives whose bytes, source release, and provenance are verified.
4. Add checksum-pinned ORT target metadata and a safe, offline installer.
5. Make downloads, preparation, extraction, and upload fail closed and transactional.
6. Run independent specification and security reviews; repair every blocker.
7. Populate missing large assets manually or through approved upstream access, verify them, and only
   then publish a complete v6 release.

## Gates

- No network fetch or cache mutation occurs for an unknown checksum or unresolved source revision.
- Archives contain only explicitly declared regular files and safe internal directory structure.
- Hash verification and extraction consume one immutable snapshot of the downloaded archive.
- Existing cache data is never overwritten implicitly.
- A release is never created or partially replaced by validation tooling.
- Model/runtime licenses and upstream revisions are recorded before publication.

## Non-goals

- Enabling AMD GPU execution in `the-one-mcp`; that requires a separate platform qualification task.
- Publishing a partial `v6.0.2` release while required artifacts remain unavailable.
