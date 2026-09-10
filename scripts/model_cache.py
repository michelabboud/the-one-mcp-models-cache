#!/usr/bin/env python3
"""Fail-closed FastEmbed cache manifest, archive, and release tooling."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
import ctypes
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import errno
import gzip
import hashlib
import http.client
import io
import json
import os
from pathlib import Path, PurePosixPath
import posixpath
import re
import secrets
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
from typing import BinaryIO, IO, cast
import urllib.parse
import zlib

import tomllib

try:
    from platform_file import PlatformFileError, advisory_lock, atomic_replace_bytes
except ModuleNotFoundError:
    from scripts.platform_file import (  # type: ignore[import-not-found]
        PlatformFileDurabilityUnknown,
        PlatformFileError,
        advisory_lock,
        atomic_replace_bytes,
    )
else:
    from platform_file import PlatformFileDurabilityUnknown


SCHEMA_VERSION = 3
HASH_CHUNK_BYTES = 1024 * 1024
MODEL_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
REPO_PART_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")
CANONICAL_RELEASE_RE = re.compile(r"^v[0-9]+\.[0-9]+\.[0-9]+$")
LEGACY_SOURCE_RELEASE_TAG = "fastembed-v4"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DATE_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
RFC3339_UTC_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?Z$"
)
PATH_PART_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
VALID_TYPES = frozenset({"embedding", "reranker", "image", "sparse"})
VALID_STATUSES = frozenset(
    {
        "provenance-required",
        "download-required",
        "refresh-required",
        "revision-review-required",
        "carry-forward",
        "prepared",
        "published",
    }
)
INSTALLABLE_STATUSES = frozenset({"carry-forward", "published"})
ARCHIVE_READY_STATUSES = frozenset({"carry-forward", "prepared", "published"})
PREPARABLE_STATUSES = frozenset({"download-required", "refresh-required"})
MUTATING_SYNC_FLAGS = frozenset({"--prepare"})
AT_FDCWD = -100
AT_EMPTY_PATH = 0x1000
RENAME_NOREPLACE = 1
RENAME_EXCL = 0x00000004
RUNTIME_MANIFEST_RELATIVE = Path("runtime/ort-sys-2.0.0-rc.13/manifest.toml")
RUNTIME_SCHEMA_VERSION = 1
RUNTIME_COMPONENT = "onnxruntime-native-static"
RUNTIME_ARCHIVE_FORMAT = "tar+raw-lzma2"
RUNTIME_ORT_SYS_VERSION = "2.0.0-rc.13"
RUNTIME_ORT_SYS_SOURCE_COMMIT = "002f41a8e175eac7f6695ff361d2e51a50874c48"
RUNTIME_ORT_SYS_DIST_TABLE_SHA256 = (
    "c706a8bf67367fbec3ad7851d9b119f8830fbabe53696e20f4740131f7f59e78"
)
RUNTIME_ONNXRUNTIME_VERSION = "1.28.0"
RUNTIME_LICENSE = "MIT"
RUNTIME_LZMA2_DICTIONARY_BYTES = 64 * 1024 * 1024
REQUIRED_RUNTIME_ASSET_COUNT = 4
REVIEWED_RUNTIME_ARCHIVES = (
    (
        "x86_64-unknown-linux-gnu",
        "none",
        "CPU",
        "x86_64-unknown-linux-gnu.tar.lzma2",
        "https://cdn.pyke.io/0/pyke:ort-rs/ms@1.28.0/x86_64-unknown-linux-gnu.tar.lzma2",
        "onnxruntime-1.28.0-ort-sys-2.0.0-rc.13-x86_64-unknown-linux-gnu.tar.lzma2",
        "libonnxruntime.a",
        "e454f710f8a49f53aa5b4ff51e3454ae1835777e431c6c35c5255ce6f205fd68",
    ),
    (
        "aarch64-unknown-linux-gnu",
        "none",
        "CPU",
        "aarch64-unknown-linux-gnu.tar.lzma2",
        "https://cdn.pyke.io/0/pyke:ort-rs/ms@1.28.0/aarch64-unknown-linux-gnu.tar.lzma2",
        "onnxruntime-1.28.0-ort-sys-2.0.0-rc.13-aarch64-unknown-linux-gnu.tar.lzma2",
        "libonnxruntime.a",
        "06a050ab9137ccb32421d0cb49e9ccf72d9e18ab0aeb8f8d038d1b5cc844b35a",
    ),
    (
        "aarch64-apple-darwin",
        "coreml",
        "CoreML",
        "aarch64-apple-darwin+coreml.tar.lzma2",
        "https://cdn.pyke.io/0/pyke:ort-rs/ms@1.28.0/aarch64-apple-darwin+coreml.tar.lzma2",
        "onnxruntime-1.28.0-ort-sys-2.0.0-rc.13-aarch64-apple-darwin+coreml.tar.lzma2",
        "libonnxruntime.a",
        "6934874e2e953576d9c1db47ff1af39c62c4f4220dbe6f988e131f72879674c7",
    ),
    (
        "x86_64-pc-windows-msvc",
        "directml",
        "DirectML",
        "x86_64-pc-windows-msvc+directml.tar.lzma2",
        "https://cdn.pyke.io/0/pyke:ort-rs/ms@1.28.0/x86_64-pc-windows-msvc+directml.tar.lzma2",
        "onnxruntime-1.28.0-ort-sys-2.0.0-rc.13-x86_64-pc-windows-msvc+directml.tar.lzma2",
        "onnxruntime.lib",
        "f7c654b3729cb9e5ad2a36a0c38e5b48e63bf4eed22968931aed33a0ad0b527d",
    ),
)
RELEASE_ASSET_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,255}$")
HF_HOST = "huggingface.co"
RUNTIME_SOURCE_HOST = "cdn.pyke.io"
MAX_HF_API_BYTES = 8 * 1024 * 1024
MAX_HF_GIT_BLOB_BYTES = 256 * 1024 * 1024
MAX_HF_REDIRECTS = 3
MAX_MODEL_ARCHIVE_BYTES = 8 * 1024 * 1024 * 1024
MAX_MODEL_ARCHIVE_MEMBERS = 4096
MAX_MODEL_MEMBER_BYTES = 4 * 1024 * 1024 * 1024
MAX_MODEL_TOTAL_BYTES = 16 * 1024 * 1024 * 1024
MAX_CACHE_INVENTORY_ENTRIES = 8192
MAX_CACHE_INVENTORY_DEPTH = 32
MAX_RUNTIME_ARCHIVE_BYTES = 1024 * 1024 * 1024
MAX_RUNTIME_LABEL_BYTES = 256
MAX_RUNTIME_REASON_BYTES = 1024
MAX_RELEASE_MANIFEST_BYTES = 16 * 1024 * 1024
_WINDOWS = os.name == "nt"

TomlTable = dict[str, object]
FieldUpdate = tuple[str, str, object]


class CacheError(Exception):
    """An operator-actionable validation or cache operation failure."""


class ManifestDurabilityUnknown(CacheError):
    """The new manifest is visible, but crash durability could not be confirmed."""


@dataclass(frozen=True)
class ModelRecord:
    key: str
    name: str
    family: str
    types: tuple[str, ...]
    huggingface_repo: str
    huggingface_url: str
    cache_repo_license: str
    cache_attribution: str
    original_model_repo: str
    original_model_url: str
    original_model_license: str
    original_attribution: str
    fastembed_cache_dir: str
    fastembed_variants: tuple[str, ...]
    variant_dims: Mapping[str, int]
    model_files: tuple[str, ...]
    additional_files: tuple[str, ...]
    required_files: tuple[str, ...]
    default_for: tuple[str, ...]
    status: str
    source_release_tag: str
    legacy_archive_release_tag: str
    legacy_archive_recorded_version: str
    legacy_archive_declared_size_mb: int
    legacy_archive_sha256: str
    legacy_archive_evidence_commit: str
    upstream_revision: str
    upstream_last_modified: str
    current_remote_revision: str
    current_remote_last_modified: str
    upstream_lfs_sha256: Mapping[str, str]
    current_remote_lfs_sha256: Mapping[str, str]
    upstream_file_sha256: Mapping[str, str]
    current_remote_file_sha256: Mapping[str, str]
    upstream_git_blob_oid: Mapping[str, str]
    current_remote_git_blob_oid: Mapping[str, str]
    file_sha256: Mapping[str, str]
    archive_size_bytes: int
    sha256: str


@dataclass(frozen=True)
class Manifest:
    path: Path
    root: Path
    raw_bytes: bytes
    meta: Mapping[str, object]
    release_tag: str
    legacy_release_tag: str
    repository: str
    fastembed_version: str
    models: Mapping[str, ModelRecord]


@dataclass(frozen=True)
class SnapshotFile:
    relative_path: str
    staged_path: Path
    sha256: str
    staged_descriptor: int | None = None


@dataclass(frozen=True)
class CuratedSnapshot:
    model: ModelRecord
    staged_artifact: Path
    files: tuple[SnapshotFile, ...]
    artifact_descriptor: int | None = None


@dataclass(frozen=True)
class RemoteModel:
    revision: str
    last_modified: str
    lfs_sha256: Mapping[str, str]
    file_sha256: Mapping[str, str]
    git_blob_oid: Mapping[str, str]


@dataclass(frozen=True)
class ReleaseAssetRecord:
    name: str
    sha256: str
    expected_size: int | None
    component: str


@dataclass(frozen=True)
class ReleasePreflight:
    head_sha: str
    target_sha: str
    release: Mapping[str, object]


@dataclass(frozen=True)
class ReleaseTrustSnapshot:
    head_sha: str
    model_manifest_bytes: bytes
    runtime_manifest_bytes: bytes


@dataclass(frozen=True)
class ExtractedModelFileEvidence:
    """Byte and filesystem identity captured from one extracted model leaf."""

    identity: tuple[int, int]
    file_state: tuple[int, int, int, int, int]
    sha256: str


@dataclass
class RenamePublicationState:
    """Records the no-clobber rename commit point inside the atomic helper."""

    renamed: bool = False


@dataclass
class DownloadPublicationState:
    """Expose the current model publication to the outer cache-root boundary."""

    rename: RenamePublicationState | None = None
    destination: Path | None = None


def _table(value: object, field: str) -> TomlTable:
    if not isinstance(value, dict):
        raise CacheError(f"manifest field '{field}' must be a table")
    return cast(TomlTable, value)


def _string(value: object, field: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value):
        qualifier = "a string" if allow_empty else "a non-empty string"
        raise CacheError(f"manifest field '{field}' must be {qualifier}")
    return value


def _integer(value: object, field: str, *, minimum: int = 0) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise CacheError(f"manifest field '{field}' must be an integer >= {minimum}")
    return value


def _string_list(
    value: object, field: str, *, allow_empty: bool = False
) -> tuple[str, ...]:
    if not isinstance(value, list) or (not value and not allow_empty):
        raise CacheError(f"manifest field '{field}' must be a string array")
    result: list[str] = []
    for item in cast(list[object], value):
        result.append(_string(item, field))
    if len(result) != len(set(result)):
        raise CacheError(f"manifest field '{field}' contains duplicates")
    return tuple(result)


def _is_historical_source_release(source_tag: str, candidate_tag: str) -> bool:
    """Return whether a carry-forward source predates the candidate release.

    ``fastembed-v4`` predates the repository's semantic ``v*`` release series and is
    the sole historical non-semantic exception retained for legacy archive provenance.
    """
    if source_tag == LEGACY_SOURCE_RELEASE_TAG:
        return True
    if not CANONICAL_RELEASE_RE.fullmatch(source_tag):
        return False
    source_version = tuple(int(part) for part in source_tag[1:].split("."))
    candidate_version = tuple(int(part) for part in candidate_tag[1:].split("."))
    return source_version < candidate_version


def _string_map(value: object, field: str) -> dict[str, str]:
    table = _table(value, field)
    return {str(key): _string(item, f"{field}.{key}") for key, item in table.items()}


def _int_map(value: object, field: str) -> dict[str, int]:
    table = _table(value, field)
    return {str(key): _integer(item, f"{field}.{key}") for key, item in table.items()}


def _validate_repo_id(repo: str, field: str) -> None:
    if any(character in repo for character in ("\\", "|", "\0")):
        raise CacheError(f"invalid {field}: {repo!r}")
    parts = repo.split("/")
    if len(parts) != 2 or any(
        not REPO_PART_RE.fullmatch(part) or ".." in part for part in parts
    ):
        raise CacheError(f"invalid {field}: {repo!r}")


def _validate_relative_path(value: str, field: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if (
        not value
        or "\\" in value
        or "|" in value
        or "\0" in value
        or path.is_absolute()
        or any(
            part in {"", ".", ".."} or not PATH_PART_RE.fullmatch(part)
            for part in path.parts
        )
    ):
        raise CacheError(f"unsafe {field}: {value!r}")
    return path


def _validate_sha256(value: str, field: str, *, allow_empty: bool) -> None:
    if not value and allow_empty:
        return
    if not SHA256_RE.fullmatch(value):
        raise CacheError(
            f"manifest field '{field}' must be 64 lowercase hexadecimal characters"
        )


def _validate_revision(value: str, field: str, *, allow_empty: bool) -> None:
    if not value and allow_empty:
        return
    if not GIT_SHA_RE.fullmatch(value):
        raise CacheError(f"invalid upstream revision in '{field}': {value!r}")


def _validate_git_blob_oid(value: str, field: str) -> None:
    if not GIT_SHA_RE.fullmatch(value):
        raise CacheError(
            f"manifest field '{field}' must be a 40-character lowercase Git blob OID"
        )


def _require_resolved_license(value: str, field: str) -> None:
    if value != value.strip() or value.upper() in {
        "NOASSERTION",
        "NONE",
        "UNKNOWN",
        "UNRESOLVED",
    }:
        raise CacheError(f"{field} is unresolved")


def _require_model_licenses(model: ModelRecord, operation: str) -> None:
    try:
        _require_resolved_license(
            model.cache_repo_license, f"{model.key} cache repository license"
        )
        _require_resolved_license(
            model.original_model_license, f"{model.key} original model license"
        )
    except CacheError as error:
        raise CacheError(f"{error}; {operation} is forbidden") from error


def _require_adopted_current_provenance(model: ModelRecord, operation: str) -> None:
    if (
        not model.current_remote_revision
        or set(model.current_remote_file_sha256) != set(model.required_files)
        or model.current_remote_revision != model.upstream_revision
        or model.current_remote_last_modified != model.upstream_last_modified
        or model.current_remote_lfs_sha256 != model.upstream_lfs_sha256
        or model.current_remote_file_sha256 != model.upstream_file_sha256
        or model.current_remote_git_blob_oid != model.upstream_git_blob_oid
    ):
        raise CacheError(
            f"{model.key} candidate provenance must completely match the adopted "
            + f"baseline before {operation}"
        )


def _validate_nonfuture_date(value: object, field: str, *, allow_empty: bool) -> str:
    date_value = _string(value, field, allow_empty=allow_empty)
    if not date_value and allow_empty:
        return date_value
    if not DATE_RE.fullmatch(date_value):
        raise CacheError(f"{field} is invalid")
    try:
        parsed = datetime.strptime(date_value, "%Y-%m-%d").date()
    except ValueError as error:
        raise CacheError(f"{field} is invalid") from error
    if parsed > datetime.now(timezone.utc).date():
        raise CacheError(f"{field} must not be in the future")
    return date_value


def _validate_timestamp(value: str, field: str, *, allow_empty: bool) -> None:
    if not value and allow_empty:
        return
    if not RFC3339_UTC_RE.fullmatch(value):
        raise CacheError(f"invalid upstream timestamp in '{field}': {value!r}")
    try:
        parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError as error:
        raise CacheError(
            f"invalid upstream timestamp in '{field}': {value!r}"
        ) from error
    if parsed.tzinfo != timezone.utc:
        raise CacheError(f"invalid upstream timestamp in '{field}': {value!r}")


def _attribution_path(root: Path, value: str, field: str) -> None:
    relative = _validate_relative_path(value, field)
    candidate = root.joinpath(*relative.parts)
    try:
        file_stat = candidate.lstat()
    except FileNotFoundError as error:
        raise CacheError(f"manifest field '{field}' does not exist: {value}") from error
    if not stat.S_ISREG(file_stat.st_mode):
        raise CacheError(
            f"manifest field '{field}' must name a regular non-symlink file"
        )


def _validate_evidence_set(
    *,
    prefix: str,
    revision: str,
    required_files: tuple[str, ...],
    file_sha256: Mapping[str, str],
    lfs_sha256: Mapping[str, str],
    git_blob_oid: Mapping[str, str],
) -> None:
    evidence_present = bool(file_sha256 or lfs_sha256 or git_blob_oid)
    if evidence_present and not revision:
        raise CacheError(f"{prefix} records byte evidence without a revision")
    if not evidence_present:
        return
    required = set(required_files)
    if set(file_sha256) != required:
        raise CacheError(f"{prefix} byte evidence must cover every required file")
    lfs_files = set(lfs_sha256)
    git_files = set(git_blob_oid)
    if lfs_files & git_files or lfs_files | git_files != required:
        raise CacheError(
            f"{prefix} LFS/Git source evidence must partition every required file"
        )
    for relative, digest in lfs_sha256.items():
        if file_sha256[relative] != digest:
            raise CacheError(f"{prefix} LFS and byte SHA-256 evidence diverges")


def _parse_model(key: str, raw: TomlTable, root: Path) -> ModelRecord:
    if not MODEL_KEY_RE.fullmatch(key):
        raise CacheError(f"invalid model key: {key!r}")
    prefix = f"models.{key}"
    types = _string_list(raw.get("types"), f"{prefix}.types")
    if not set(types) <= VALID_TYPES:
        raise CacheError(
            f"manifest field '{prefix}.types' contains an unknown model type"
        )
    defaults = _string_list(
        raw.get("default_for"), f"{prefix}.default_for", allow_empty=True
    )
    if not set(defaults) <= set(types):
        raise CacheError(
            f"manifest field '{prefix}.default_for' must be a subset of types"
        )

    repo = _string(raw.get("huggingface_repo"), f"{prefix}.huggingface_repo")
    _validate_repo_id(repo, "huggingface_repo")
    repo_url = _string(raw.get("huggingface_url"), f"{prefix}.huggingface_url")
    if repo_url != f"https://huggingface.co/{repo}":
        raise CacheError(
            f"manifest field '{prefix}.huggingface_url' does not match huggingface_repo"
        )
    original_repo = _string(
        raw.get("original_model_repo"), f"{prefix}.original_model_repo"
    )
    _validate_repo_id(original_repo, "original_model_repo")
    original_url = _string(
        raw.get("original_model_url"), f"{prefix}.original_model_url"
    )
    allowed_original_urls = {
        f"https://huggingface.co/{original_repo}",
        f"https://github.com/{original_repo}",
    }
    if original_url not in allowed_original_urls:
        raise CacheError(
            f"manifest field '{prefix}.original_model_url' is not an exact source URL"
        )
    cache_license = _string(
        raw.get("cache_repo_license"), f"{prefix}.cache_repo_license"
    )

    cache_attribution = _string(
        raw.get("cache_attribution"), f"{prefix}.cache_attribution"
    )
    original_attribution = _string(
        raw.get("original_attribution"), f"{prefix}.original_attribution"
    )
    _attribution_path(root, cache_attribution, f"{prefix}.cache_attribution")
    _attribution_path(root, original_attribution, f"{prefix}.original_attribution")

    cache_dir = _string(raw.get("fastembed_cache_dir"), f"{prefix}.fastembed_cache_dir")
    expected_cache_dir = "models--" + repo.replace("/", "--")
    if cache_dir != expected_cache_dir or not MODEL_KEY_RE.fullmatch(
        cache_dir.replace(".", "_")
    ):
        raise CacheError(f"manifest field '{prefix}.fastembed_cache_dir' is invalid")

    variants = _string_list(
        raw.get("fastembed_variants"), f"{prefix}.fastembed_variants"
    )
    for variant in variants:
        if not re.fullmatch(
            r"^(?:EmbeddingModel|RerankerModel|ImageEmbeddingModel|SparseModel)::[A-Za-z0-9]+$",
            variant,
        ):
            raise CacheError(f"manifest field '{prefix}.fastembed_variants' is invalid")
    variant_dims = _int_map(raw.get("variant_dims"), f"{prefix}.variant_dims")
    if set(variant_dims) != set(variants):
        raise CacheError(
            f"manifest field '{prefix}.variant_dims' must cover every variant exactly"
        )
    for variant, dimensions in variant_dims.items():
        if variant.startswith(("RerankerModel::", "SparseModel::")) and dimensions != 0:
            raise CacheError(
                f"manifest field '{prefix}.variant_dims.{variant}' must be zero"
            )
        if (
            variant.startswith(("EmbeddingModel::", "ImageEmbeddingModel::"))
            and dimensions == 0
        ):
            raise CacheError(
                f"manifest field '{prefix}.variant_dims.{variant}' must be positive"
            )

    model_files = _string_list(raw.get("model_files"), f"{prefix}.model_files")
    additional_files = _string_list(
        raw.get("additional_files"), f"{prefix}.additional_files", allow_empty=True
    )
    required_files = _string_list(raw.get("required_files"), f"{prefix}.required_files")
    for relative in required_files:
        _validate_relative_path(relative, "required file")
    if not (set(model_files) | set(additional_files)) <= set(required_files):
        raise CacheError(
            f"manifest field '{prefix}.required_files' omits a model/additional file"
        )

    status_value = _string(raw.get("status"), f"{prefix}.status")
    if status_value not in VALID_STATUSES:
        raise CacheError(f"manifest field '{prefix}.status' is invalid")
    source_tag = _string(
        raw.get("source_release_tag", ""),
        f"{prefix}.source_release_tag",
        allow_empty=True,
    )
    if source_tag and not (
        CANONICAL_RELEASE_RE.fullmatch(source_tag)
        or source_tag == LEGACY_SOURCE_RELEASE_TAG
    ):
        raise CacheError(f"invalid source release tag: {source_tag!r}")

    legacy_archive_tag = _string(
        raw.get("legacy_archive_release_tag", ""),
        f"{prefix}.legacy_archive_release_tag",
        allow_empty=True,
    )
    legacy_archive_version = _string(
        raw.get("legacy_archive_recorded_version", ""),
        f"{prefix}.legacy_archive_recorded_version",
        allow_empty=True,
    )
    legacy_archive_size_mb = _integer(
        raw.get("legacy_archive_declared_size_mb", 0),
        f"{prefix}.legacy_archive_declared_size_mb",
    )
    legacy_archive_sha = _string(
        raw.get("legacy_archive_sha256", ""),
        f"{prefix}.legacy_archive_sha256",
        allow_empty=True,
    )
    legacy_evidence_commit = _string(
        raw.get("legacy_archive_evidence_commit", ""),
        f"{prefix}.legacy_archive_evidence_commit",
        allow_empty=True,
    )
    legacy_fields_complete = (
        legacy_archive_tag == LEGACY_SOURCE_RELEASE_TAG
        and bool(legacy_archive_version)
        and legacy_archive_size_mb > 0
        and bool(legacy_archive_sha)
        and bool(legacy_evidence_commit)
    )
    if (
        any(
            (
                legacy_archive_tag,
                legacy_archive_version,
                legacy_archive_size_mb,
                legacy_archive_sha,
                legacy_evidence_commit,
            )
        )
        and not legacy_fields_complete
    ):
        raise CacheError(f"{prefix} has incomplete legacy archive evidence")
    if legacy_fields_complete:
        try:
            datetime.strptime(legacy_archive_version, "%Y-%m")
        except ValueError as error:
            raise CacheError(
                f"manifest field '{prefix}.legacy_archive_recorded_version' is invalid"
            ) from error
        _validate_sha256(
            legacy_archive_sha,
            f"{prefix}.legacy_archive_sha256",
            allow_empty=False,
        )
        _validate_revision(
            legacy_evidence_commit,
            f"{prefix}.legacy_archive_evidence_commit",
            allow_empty=False,
        )

    revision = _string(
        raw.get("upstream_revision", ""),
        f"{prefix}.upstream_revision",
        allow_empty=True,
    )
    modified = _string(
        raw.get("upstream_last_modified", ""),
        f"{prefix}.upstream_last_modified",
        allow_empty=True,
    )
    current_revision = _string(
        raw.get("current_remote_revision", ""),
        f"{prefix}.current_remote_revision",
        allow_empty=True,
    )
    current_modified = _string(
        raw.get("current_remote_last_modified", ""),
        f"{prefix}.current_remote_last_modified",
        allow_empty=True,
    )
    _validate_revision(revision, f"{prefix}.upstream_revision", allow_empty=True)
    _validate_timestamp(modified, f"{prefix}.upstream_last_modified", allow_empty=True)
    _validate_revision(
        current_revision, f"{prefix}.current_remote_revision", allow_empty=True
    )
    _validate_timestamp(
        current_modified, f"{prefix}.current_remote_last_modified", allow_empty=True
    )
    if status_value == "carry-forward" and not revision:
        raise CacheError(
            f"{prefix}.upstream_revision is required for status carry-forward"
        )
    if bool(revision) != bool(modified):
        raise CacheError(
            f"{prefix} must record upstream revision and timestamp together"
        )
    if bool(current_revision) != bool(current_modified):
        raise CacheError(
            f"{prefix} must record current remote revision and timestamp together"
        )

    upstream_lfs = _string_map(
        raw.get("upstream_lfs_sha256", {}), f"{prefix}.upstream_lfs_sha256"
    )
    current_remote_lfs = _string_map(
        raw.get("current_remote_lfs_sha256"),
        f"{prefix}.current_remote_lfs_sha256",
    )
    upstream_file = _string_map(
        raw.get("upstream_file_sha256"), f"{prefix}.upstream_file_sha256"
    )
    current_remote_file = _string_map(
        raw.get("current_remote_file_sha256"),
        f"{prefix}.current_remote_file_sha256",
    )
    upstream_git = _string_map(
        raw.get("upstream_git_blob_oid"), f"{prefix}.upstream_git_blob_oid"
    )
    current_remote_git = _string_map(
        raw.get("current_remote_git_blob_oid"),
        f"{prefix}.current_remote_git_blob_oid",
    )
    file_sha = _string_map(raw.get("file_sha256", {}), f"{prefix}.file_sha256")
    if upstream_lfs and not revision:
        raise CacheError(f"{prefix} records upstream LFS hashes without a revision")
    if current_remote_lfs and not current_revision:
        raise CacheError(f"{prefix} records candidate LFS hashes without a revision")
    for field_name, digests in (
        ("upstream_lfs_sha256", upstream_lfs),
        ("current_remote_lfs_sha256", current_remote_lfs),
        ("upstream_file_sha256", upstream_file),
        ("current_remote_file_sha256", current_remote_file),
        ("file_sha256", file_sha),
    ):
        if not set(digests) <= set(required_files):
            raise CacheError(
                f"manifest field '{prefix}.{field_name}' has an undeclared file"
            )
        for relative, digest in digests.items():
            _validate_relative_path(relative, "digest file")
            _validate_sha256(
                digest, f"{prefix}.{field_name}.{relative}", allow_empty=False
            )
    for field_name, object_ids in (
        ("upstream_git_blob_oid", upstream_git),
        ("current_remote_git_blob_oid", current_remote_git),
    ):
        if not set(object_ids) <= set(required_files):
            raise CacheError(
                f"manifest field '{prefix}.{field_name}' has an undeclared file"
            )
        for relative, object_id in object_ids.items():
            _validate_relative_path(relative, "Git blob file")
            _validate_git_blob_oid(object_id, f"{prefix}.{field_name}.{relative}")
    _validate_evidence_set(
        prefix=f"{prefix}.upstream",
        revision=revision,
        required_files=required_files,
        file_sha256=upstream_file,
        lfs_sha256=upstream_lfs,
        git_blob_oid=upstream_git,
    )
    _validate_evidence_set(
        prefix=f"{prefix}.current_remote",
        revision=current_revision,
        required_files=required_files,
        file_sha256=current_remote_file,
        lfs_sha256=current_remote_lfs,
        git_blob_oid=current_remote_git,
    )
    if current_revision and not current_remote_file:
        raise CacheError(
            f"{prefix}.current_remote byte evidence must cover every required file"
        )

    archive_size = _integer(
        raw.get("archive_size_bytes"), f"{prefix}.archive_size_bytes"
    )
    archive_sha = _string(raw.get("sha256"), f"{prefix}.sha256", allow_empty=True)
    _validate_sha256(archive_sha, f"{prefix}.sha256", allow_empty=True)

    if status_value in ARCHIVE_READY_STATUSES:
        if not revision:
            raise CacheError(
                f"{prefix}.upstream_revision is required for status {status_value}"
            )
        if not archive_sha or archive_size == 0:
            raise CacheError(
                f"{prefix} requires an archive size and SHA-256 for status {status_value}"
            )
        if set(file_sha) != set(required_files):
            raise CacheError(f"{prefix}.file_sha256 must cover every required file")
        if not upstream_file or file_sha != upstream_file:
            raise CacheError(
                f"{prefix} archive bytes must equal complete upstream byte evidence"
            )
        try:
            _require_resolved_license(cache_license, "cache repository license")
        except CacheError as error:
            raise CacheError(
                f"{prefix} cache repository license is unresolved; archive-ready is forbidden"
            ) from error
        original_license = _string(
            raw.get("original_model_license"), f"{prefix}.original_model_license"
        )
        try:
            _require_resolved_license(original_license, "original model license")
        except CacheError as error:
            raise CacheError(
                f"{prefix} original model license is unresolved; archive-ready is forbidden"
            ) from error
        if current_revision and (
            current_revision != revision
            or current_remote_lfs != upstream_lfs
            or current_remote_file != upstream_file
            or current_remote_git != upstream_git
        ):
            raise CacheError(
                f"{prefix} candidate provenance diverges from archive baseline"
            )
    elif status_value in {"download-required", "refresh-required"}:
        if archive_sha or archive_size:
            raise CacheError(f"{prefix} must not claim an unpublished archive")
    elif status_value == "revision-review-required":
        if not revision or not current_revision:
            raise CacheError(
                f"{prefix} requires baseline and candidate revisions for reviewed adoption"
            )
        if (
            revision == current_revision
            and upstream_lfs == current_remote_lfs
            and upstream_file == current_remote_file
            and upstream_git == current_remote_git
        ):
            raise CacheError(f"{prefix} has no changed upstream provenance to review")
        if archive_sha or archive_size or file_sha:
            raise CacheError(
                f"{prefix} must invalidate archive claims while revision review is required"
            )
    elif status_value == "provenance-required":
        if not source_tag or not archive_sha or archive_size == 0:
            raise CacheError(
                f"{prefix} must retain its historical release archive evidence"
            )
        if revision:
            raise CacheError(
                f"{prefix} has provenance but remains marked provenance-required"
            )

    return ModelRecord(
        key=key,
        name=_string(raw.get("name"), f"{prefix}.name"),
        family=_string(raw.get("family"), f"{prefix}.family"),
        types=types,
        huggingface_repo=repo,
        huggingface_url=repo_url,
        cache_repo_license=cache_license,
        cache_attribution=cache_attribution,
        original_model_repo=original_repo,
        original_model_url=original_url,
        original_model_license=_string(
            raw.get("original_model_license"), f"{prefix}.original_model_license"
        ),
        original_attribution=original_attribution,
        fastembed_cache_dir=cache_dir,
        fastembed_variants=variants,
        variant_dims=variant_dims,
        model_files=model_files,
        additional_files=additional_files,
        required_files=required_files,
        default_for=defaults,
        status=status_value,
        source_release_tag=source_tag,
        legacy_archive_release_tag=legacy_archive_tag,
        legacy_archive_recorded_version=legacy_archive_version,
        legacy_archive_declared_size_mb=legacy_archive_size_mb,
        legacy_archive_sha256=legacy_archive_sha,
        legacy_archive_evidence_commit=legacy_evidence_commit,
        upstream_revision=revision,
        upstream_last_modified=modified,
        current_remote_revision=current_revision,
        current_remote_last_modified=current_modified,
        upstream_lfs_sha256=upstream_lfs,
        current_remote_lfs_sha256=current_remote_lfs,
        upstream_file_sha256=upstream_file,
        current_remote_file_sha256=current_remote_file,
        upstream_git_blob_oid=upstream_git,
        current_remote_git_blob_oid=current_remote_git,
        file_sha256=file_sha,
        archive_size_bytes=archive_size,
        sha256=archive_sha,
    )


def load_manifest(
    path: Path, root: Path | None = None, raw_bytes: bytes | None = None
) -> Manifest:
    manifest_root = (root or path.resolve().parent).resolve()
    if raw_bytes is not None:
        if len(raw_bytes) > MAX_RELEASE_MANIFEST_BYTES:
            raise CacheError("models manifest exceeds the release preflight size limit")
        content = raw_bytes
    else:
        content = _release_manifest_bytes(path, "models manifest")
    try:
        parsed = cast(TomlTable, tomllib.loads(content.decode("utf-8")))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise CacheError(f"invalid TOML manifest: {error}") from error
    meta = _table(parsed.get("meta"), "meta")
    if meta.get("schema_version") != SCHEMA_VERSION:
        raise CacheError(f"meta.schema_version must be {SCHEMA_VERSION}")
    release_tag = _string(meta.get("release_tag"), "meta.release_tag")
    if not CANONICAL_RELEASE_RE.fullmatch(release_tag):
        raise CacheError(
            "meta.release_tag must be a canonical v<major>.<minor>.<patch> tag"
        )
    legacy_tag = _string(meta.get("legacy_release_tag"), "meta.legacy_release_tag")
    if legacy_tag != LEGACY_SOURCE_RELEASE_TAG:
        raise CacheError(
            "meta.legacy_release_tag must preserve the immutable "
            + f"{LEGACY_SOURCE_RELEASE_TAG} tag"
        )
    repository = _string(meta.get("repo"), "meta.repo")
    _validate_repo_id(repository, "repository")
    fastembed_version = _string(
        meta.get("fastembed_crate_version"), "meta.fastembed_crate_version"
    )
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", fastembed_version):
        raise CacheError("meta.fastembed_crate_version is invalid")
    _validate_nonfuture_date(
        meta.get("source_audited"), "meta.source_audited", allow_empty=False
    )
    estimate_state = _string(
        meta.get("pending_raw_size_estimate_status"),
        "meta.pending_raw_size_estimate_status",
    )
    if estimate_state != "rough-unverified":
        raise CacheError(
            "meta.pending_raw_size_estimate_status must be rough-unverified"
        )
    estimate_date = _string(
        meta.get("pending_raw_size_estimate_date"),
        "meta.pending_raw_size_estimate_date",
    )
    if not DATE_RE.fullmatch(estimate_date):
        raise CacheError("meta.pending_raw_size_estimate_date is invalid")
    try:
        datetime.strptime(estimate_date, "%Y-%m-%d")
    except ValueError as error:
        raise CacheError("meta.pending_raw_size_estimate_date is invalid") from error
    last_upstream_check = _string(
        meta.get("last_upstream_check", ""),
        "meta.last_upstream_check",
        allow_empty=True,
    )
    if last_upstream_check and not DATE_RE.fullmatch(last_upstream_check):
        raise CacheError("meta.last_upstream_check is invalid")
    if last_upstream_check:
        try:
            checked_date = datetime.strptime(last_upstream_check, "%Y-%m-%d").date()
        except ValueError as error:
            raise CacheError("meta.last_upstream_check is invalid") from error
        if checked_date > datetime.now(timezone.utc).date():
            raise CacheError("meta.last_upstream_check must not be in the future")
    legacy_manifest_check = _string(
        meta.get("legacy_manifest_last_checked"),
        "meta.legacy_manifest_last_checked",
    )
    if not DATE_RE.fullmatch(legacy_manifest_check):
        raise CacheError("meta.legacy_manifest_last_checked is invalid")
    try:
        legacy_checked_date = datetime.strptime(
            legacy_manifest_check, "%Y-%m-%d"
        ).date()
    except ValueError as error:
        raise CacheError("meta.legacy_manifest_last_checked is invalid") from error
    if legacy_checked_date > datetime.now(timezone.utc).date():
        raise CacheError("meta.legacy_manifest_last_checked must not be in the future")

    raw_models = _table(parsed.get("models"), "models")
    models: dict[str, ModelRecord] = {}
    variants: set[str] = set()
    cache_dirs: set[str] = set()
    defaults: dict[str, list[str]] = {model_type: [] for model_type in VALID_TYPES}
    for key, value in raw_models.items():
        model = _parse_model(str(key), _table(value, f"models.{key}"), manifest_root)
        if model.status == "carry-forward" and not _is_historical_source_release(
            model.source_release_tag, release_tag
        ):
            raise CacheError(
                f"models.{model.key} carry-forward requires a historical "
                + "source_release_tag strictly older than the candidate release "
                + f"({LEGACY_SOURCE_RELEASE_TAG} is the documented legacy exception)"
            )
        if (
            model.status == "provenance-required"
            and model.source_release_tag == release_tag
        ):
            raise CacheError(
                f"models.{model.key} historical source_release_tag must differ from the candidate release"
            )
        duplicate_variants = variants & set(model.fastembed_variants)
        if duplicate_variants:
            raise CacheError(
                f"FastEmbed variants are duplicated: {sorted(duplicate_variants)}"
            )
        if model.fastembed_cache_dir in cache_dirs:
            raise CacheError(
                f"FastEmbed cache directory is duplicated: {model.fastembed_cache_dir}"
            )
        variants.update(model.fastembed_variants)
        cache_dirs.add(model.fastembed_cache_dir)
        for model_type in model.default_for:
            defaults[model_type].append(model.key)
        models[model.key] = model

    declared_groups = _integer(
        meta.get("artifact_groups"), "meta.artifact_groups", minimum=1
    )
    if declared_groups != len(models):
        raise CacheError("meta.artifact_groups does not match the models table")
    for model_type in VALID_TYPES:
        represented = any(model_type in model.types for model in models.values())
        if represented and len(defaults[model_type]) != 1:
            raise CacheError(f"expected exactly one default_for={model_type}")
    return Manifest(
        path=path,
        root=manifest_root,
        raw_bytes=content,
        meta=meta,
        release_tag=release_tag,
        legacy_release_tag=legacy_tag,
        repository=repository,
        fastembed_version=fastembed_version,
        models=models,
    )


def _bounded_runtime_text(value: object, field: str, *, limit: int) -> str:
    text = _string(value, field)
    if (
        text != text.strip()
        or len(text.encode("utf-8")) > limit
        or any(ord(character) < 32 or ord(character) == 127 for character in text)
    ):
        raise CacheError(f"runtime manifest field '{field}' is not safe bounded text")
    return text


def _runtime_rows(runtime_raw: TomlTable, section: str) -> list[object]:
    rows = runtime_raw.get(section)
    if not isinstance(rows, list):
        raise CacheError(f"runtime.{section} must be an array of tables")
    return cast(list[object], rows)


def _validate_runtime_archive_row(
    raw_archive: object,
    *,
    section: str,
    index: int,
    runtime_version: str,
    asset_field: str,
    require_reason: bool,
    seen_target_features: set[tuple[str, str]],
    seen_sources: set[str],
    seen_assets: set[str],
) -> tuple[str, str, str]:
    field = f"runtime.{section}[{index}]"
    archive = _table(raw_archive, field)
    required_fields = {
        "target",
        "platform",
        "feature_set",
        "execution_provider",
        "source_url",
        "source_archive",
        asset_field,
        "sha256",
        "expected_library",
        "cache_path",
    }
    if require_reason:
        required_fields.add("reason")
    if set(archive) != required_fields:
        raise CacheError(f"{field} schema is incomplete or unsupported")

    target = _string(archive.get("target"), f"{field}.target")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", target):
        raise CacheError(f"{field}.target is invalid")
    _bounded_runtime_text(
        archive.get("platform"), f"{field}.platform", limit=MAX_RUNTIME_LABEL_BYTES
    )
    feature_set = _string(archive.get("feature_set"), f"{field}.feature_set")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,63}", feature_set):
        raise CacheError(f"{field}.feature_set is invalid")
    _bounded_runtime_text(
        archive.get("execution_provider"),
        f"{field}.execution_provider",
        limit=MAX_RUNTIME_LABEL_BYTES,
    )
    target_feature = (target, feature_set)
    if target_feature in seen_target_features:
        raise CacheError(f"duplicate runtime target and feature set: {target}")
    seen_target_features.add(target_feature)

    source_archive = _string(archive.get("source_archive"), f"{field}.source_archive")
    if not RELEASE_ASSET_RE.fullmatch(source_archive) or not source_archive.endswith(
        ".tar.lzma2"
    ):
        raise CacheError(f"invalid runtime source archive name: {source_archive!r}")
    if source_archive in seen_sources:
        raise CacheError(f"duplicate runtime source archive: {source_archive}")
    seen_sources.add(source_archive)
    source_url = _string(archive.get("source_url"), f"{field}.source_url")
    expected_source_url = (
        f"https://{RUNTIME_SOURCE_HOST}/0/pyke:ort-rs/ms@{runtime_version}/"
        + source_archive
    )
    if source_url != expected_source_url:
        raise CacheError(
            "runtime source URL is not the canonical version-bound Pyke URL"
        )

    asset_name = _string(archive.get(asset_field), f"{field}.{asset_field}")
    if not RELEASE_ASSET_RE.fullmatch(asset_name) or not asset_name.endswith(
        ".tar.lzma2"
    ):
        raise CacheError(f"invalid runtime release asset name: {asset_name!r}")
    if asset_name in seen_assets:
        raise CacheError(f"duplicate release asset name: {asset_name}")
    seen_assets.add(asset_name)

    digest = _string(archive.get("sha256"), f"{field}.sha256")
    _validate_sha256(digest, f"{field}.sha256", allow_empty=False)
    expected_library = _string(
        archive.get("expected_library"), f"{field}.expected_library"
    )
    if expected_library not in {"libonnxruntime.a", "onnxruntime.lib"}:
        raise CacheError(f"unsupported runtime expected library: {expected_library}")
    cache_path = _string(archive.get("cache_path"), f"{field}.cache_path")
    if cache_path != f"${{ORT_CACHE_DIR}}/dfbin/{target}/{digest}/":
        raise CacheError("runtime cache path is not bound to target and digest")
    if require_reason:
        _bounded_runtime_text(
            archive.get("reason"),
            f"{field}.reason",
            limit=MAX_RUNTIME_REASON_BYTES,
        )
    return target, asset_name, digest


def authoritative_release_inventory(
    manifest: Manifest,
    *,
    runtime_raw_bytes: bytes | None = None,
) -> Mapping[str, ReleaseAssetRecord]:
    """Return the exact model + required runtime asset set for one release tag."""
    inventory: dict[str, ReleaseAssetRecord] = {
        f"{model.key}.tar.gz": ReleaseAssetRecord(
            name=f"{model.key}.tar.gz",
            sha256=model.sha256,
            expected_size=model.archive_size_bytes,
            component="fastembed-model",
        )
        for model in manifest.models.values()
    }
    runtime_path = manifest.root / RUNTIME_MANIFEST_RELATIVE
    try:
        runtime_stat = runtime_path.lstat()
    except FileNotFoundError as error:
        raise CacheError(
            f"required runtime manifest is missing: {runtime_path}"
        ) from error
    if not stat.S_ISREG(runtime_stat.st_mode):
        raise CacheError(
            f"required runtime manifest is not a regular file: {runtime_path}"
        )
    try:
        if runtime_raw_bytes is not None:
            if len(runtime_raw_bytes) > MAX_RELEASE_MANIFEST_BYTES:
                raise CacheError(
                    "runtime manifest exceeds the release preflight size limit"
                )
            runtime_content = runtime_raw_bytes
        else:
            runtime_content = _release_manifest_bytes(runtime_path, "runtime manifest")
        runtime_raw = cast(TomlTable, tomllib.loads(runtime_content.decode("utf-8")))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise CacheError(f"invalid runtime manifest: {error}") from error
    required_top_level_fields = {
        "meta",
        "archives",
        "future_archives",
        "optional_archives",
        "unavailable_targets",
    }
    if set(runtime_raw) != required_top_level_fields:
        raise CacheError(
            "runtime manifest top-level schema is incomplete or unsupported"
        )
    runtime_meta = _table(runtime_raw.get("meta"), "runtime.meta")
    required_meta_fields = {
        "schema_version",
        "component",
        "release_repo",
        "release_tag",
        "ort_sys_version",
        "ort_sys_source_commit",
        "ort_sys_dist_table_url",
        "ort_sys_dist_table_sha256",
        "onnxruntime_version",
        "onnxruntime_release_url",
        "onnxruntime_license",
        "onnxruntime_license_url",
        "archive_format",
        "lzma2_dictionary_bytes",
        "cache_path_template",
    }
    if set(runtime_meta) != required_meta_fields:
        raise CacheError("runtime manifest meta schema is incomplete or unsupported")
    if runtime_meta.get("schema_version") != RUNTIME_SCHEMA_VERSION:
        raise CacheError(
            f"runtime.meta.schema_version must be {RUNTIME_SCHEMA_VERSION}"
        )
    if (
        _string(runtime_meta.get("component"), "runtime.meta.component")
        != RUNTIME_COMPONENT
    ):
        raise CacheError(f"runtime component must be exactly {RUNTIME_COMPONENT}")
    if (
        _string(runtime_meta.get("release_repo"), "runtime.meta.release_repo")
        != manifest.repository
    ):
        raise CacheError("runtime release repository does not match the model manifest")
    if (
        _string(runtime_meta.get("release_tag"), "runtime.meta.release_tag")
        != manifest.release_tag
    ):
        raise CacheError("runtime release tag does not match the model manifest")
    ort_sys_version = _string(
        runtime_meta.get("ort_sys_version"), "runtime.meta.ort_sys_version"
    )
    if ort_sys_version != RUNTIME_ORT_SYS_VERSION:
        raise CacheError("runtime.meta.ort_sys_version is unsupported")
    source_commit = _string(
        runtime_meta.get("ort_sys_source_commit"),
        "runtime.meta.ort_sys_source_commit",
    )
    _validate_revision(
        source_commit, "runtime.meta.ort_sys_source_commit", allow_empty=False
    )
    if source_commit != RUNTIME_ORT_SYS_SOURCE_COMMIT:
        raise CacheError(
            "runtime manifest does not use the reviewed ort-sys source commit"
        )
    dist_url = _string(
        runtime_meta.get("ort_sys_dist_table_url"),
        "runtime.meta.ort_sys_dist_table_url",
    )
    expected_dist_url = (
        f"https://github.com/pykeio/ort/blob/{source_commit}/"
        + "ort-sys/build/download/dist.tsv"
    )
    if dist_url != expected_dist_url:
        raise CacheError(
            "runtime ort-sys dist table URL is not bound to its source commit"
        )
    dist_digest = _string(
        runtime_meta.get("ort_sys_dist_table_sha256"),
        "runtime.meta.ort_sys_dist_table_sha256",
    )
    _validate_sha256(
        dist_digest, "runtime.meta.ort_sys_dist_table_sha256", allow_empty=False
    )
    if dist_digest != RUNTIME_ORT_SYS_DIST_TABLE_SHA256:
        raise CacheError(
            "runtime manifest does not use the reviewed ort-sys dist table"
        )
    runtime_version = _string(
        runtime_meta.get("onnxruntime_version"),
        "runtime.meta.onnxruntime_version",
    )
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", runtime_version):
        raise CacheError("runtime.meta.onnxruntime_version is invalid")
    if runtime_version != RUNTIME_ONNXRUNTIME_VERSION:
        raise CacheError(
            "runtime manifest does not use the reviewed ONNX Runtime version"
        )
    release_url = _string(
        runtime_meta.get("onnxruntime_release_url"),
        "runtime.meta.onnxruntime_release_url",
    )
    if release_url != (
        f"https://github.com/microsoft/onnxruntime/releases/tag/v{runtime_version}"
    ):
        raise CacheError("runtime ONNX Runtime release URL is not version-bound")
    runtime_license = _string(
        runtime_meta.get("onnxruntime_license"), "runtime.meta.onnxruntime_license"
    )
    _require_resolved_license(runtime_license, "runtime ONNX Runtime license")
    if runtime_license != RUNTIME_LICENSE:
        raise CacheError("runtime ONNX Runtime license is unsupported")
    license_url = _string(
        runtime_meta.get("onnxruntime_license_url"),
        "runtime.meta.onnxruntime_license_url",
    )
    if license_url != (
        f"https://github.com/microsoft/onnxruntime/blob/v{runtime_version}/LICENSE"
    ):
        raise CacheError("runtime ONNX Runtime license URL is not version-bound")
    if (
        _string(runtime_meta.get("archive_format"), "runtime.meta.archive_format")
        != RUNTIME_ARCHIVE_FORMAT
    ):
        raise CacheError(f"runtime archive format must be {RUNTIME_ARCHIVE_FORMAT}")
    dictionary_bytes = _integer(
        runtime_meta.get("lzma2_dictionary_bytes"),
        "runtime.meta.lzma2_dictionary_bytes",
        minimum=1,
    )
    if dictionary_bytes != RUNTIME_LZMA2_DICTIONARY_BYTES:
        raise CacheError("runtime LZMA2 dictionary size is unsupported")
    if (
        _string(
            runtime_meta.get("cache_path_template"),
            "runtime.meta.cache_path_template",
        )
        != "${ORT_CACHE_DIR}/dfbin/{target}/{sha256}/"
    ):
        raise CacheError("runtime cache path template is unsupported")
    raw_archives = _runtime_rows(runtime_raw, "archives")
    if len(raw_archives) != REQUIRED_RUNTIME_ASSET_COUNT:
        raise CacheError(
            f"runtime manifest must contain exactly {REQUIRED_RUNTIME_ASSET_COUNT} required archives"
        )
    required_archive_fields = {
        "target",
        "platform",
        "feature_set",
        "execution_provider",
        "source_url",
        "source_archive",
        "release_asset",
        "sha256",
        "expected_library",
        "cache_path",
    }
    seen_targets: set[tuple[str, str]] = set()
    seen_sources: set[str] = set()
    seen_assets = set(inventory)
    archive_targets: set[str] = set()
    reviewed_rows: dict[tuple[str, str], tuple[str, ...]] = {}
    for index, raw_archive in enumerate(raw_archives):
        archive = _table(raw_archive, f"runtime.archives[{index}]")
        if set(archive) != required_archive_fields:
            raise CacheError(
                f"runtime.archives[{index}] schema is incomplete or unsupported"
            )
        target = _string(archive.get("target"), f"runtime.archives[{index}].target")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", target):
            raise CacheError(f"runtime.archives[{index}].target is invalid")
        _bounded_runtime_text(
            archive.get("platform"),
            f"runtime.archives[{index}].platform",
            limit=MAX_RUNTIME_LABEL_BYTES,
        )
        feature_set = _string(
            archive.get("feature_set"), f"runtime.archives[{index}].feature_set"
        )
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,63}", feature_set):
            raise CacheError(f"runtime.archives[{index}].feature_set is invalid")
        execution_provider = _bounded_runtime_text(
            archive.get("execution_provider"),
            f"runtime.archives[{index}].execution_provider",
            limit=MAX_RUNTIME_LABEL_BYTES,
        )
        target_key = (target, feature_set)
        if target_key in seen_targets:
            raise CacheError(f"duplicate runtime target and feature set: {target}")
        seen_targets.add(target_key)
        archive_targets.add(target)
        source_archive = _string(
            archive.get("source_archive"),
            f"runtime.archives[{index}].source_archive",
        )
        if not RELEASE_ASSET_RE.fullmatch(
            source_archive
        ) or not source_archive.endswith(".tar.lzma2"):
            raise CacheError(f"invalid runtime source archive name: {source_archive!r}")
        if source_archive in seen_sources:
            raise CacheError(f"duplicate runtime source archive: {source_archive}")
        seen_sources.add(source_archive)
        source_url = _string(
            archive.get("source_url"), f"runtime.archives[{index}].source_url"
        )
        expected_source_url = (
            f"https://{RUNTIME_SOURCE_HOST}/0/pyke:ort-rs/ms@{runtime_version}/"
            + source_archive
        )
        if source_url != expected_source_url:
            raise CacheError(
                "runtime source URL is not the canonical version-bound Pyke URL"
            )
        name = _string(
            archive.get("release_asset"), f"runtime.archives[{index}].release_asset"
        )
        if not RELEASE_ASSET_RE.fullmatch(name) or not name.endswith(".tar.lzma2"):
            raise CacheError(f"invalid runtime release asset name: {name!r}")
        digest = _string(archive.get("sha256"), f"runtime.archives[{index}].sha256")
        _validate_sha256(digest, f"runtime.archives[{index}].sha256", allow_empty=False)
        expected_library = _string(
            archive.get("expected_library"),
            f"runtime.archives[{index}].expected_library",
        )
        if expected_library not in {"libonnxruntime.a", "onnxruntime.lib"}:
            raise CacheError(
                f"unsupported runtime expected library: {expected_library}"
            )
        cache_path = _string(
            archive.get("cache_path"), f"runtime.archives[{index}].cache_path"
        )
        if cache_path != f"${{ORT_CACHE_DIR}}/dfbin/{target}/{digest}/":
            raise CacheError("runtime cache path is not bound to target and digest")
        if name in seen_assets:
            raise CacheError(f"duplicate release asset name: {name}")
        seen_assets.add(name)
        reviewed_rows[target_key] = (
            target,
            feature_set,
            execution_provider,
            source_archive,
            source_url,
            name,
            expected_library,
            digest,
        )
        inventory[name] = ReleaseAssetRecord(
            name=name,
            sha256=digest,
            expected_size=None,
            component="onnxruntime",
        )
    expected_reviewed_rows = {
        (row[0], row[1]): row for row in REVIEWED_RUNTIME_ARCHIVES
    }
    if reviewed_rows != expected_reviewed_rows:
        raise CacheError(
            "required runtime archives must match the exact reviewed rc13 runtime map"
        )

    for section in ("future_archives", "optional_archives"):
        for index, raw_archive in enumerate(_runtime_rows(runtime_raw, section)):
            target, _, _ = _validate_runtime_archive_row(
                raw_archive,
                section=section,
                index=index,
                runtime_version=runtime_version,
                asset_field="proposed_release_asset",
                require_reason=True,
                seen_target_features=seen_targets,
                seen_sources=seen_sources,
                seen_assets=seen_assets,
            )
            archive_targets.add(target)

    unavailable_targets: set[str] = set()
    for index, raw_target in enumerate(
        _runtime_rows(runtime_raw, "unavailable_targets")
    ):
        field = f"runtime.unavailable_targets[{index}]"
        unavailable = _table(raw_target, field)
        if set(unavailable) != {"target", "platform", "reason"}:
            raise CacheError(f"{field} schema is incomplete or unsupported")
        target = _string(unavailable.get("target"), f"{field}.target")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", target):
            raise CacheError(f"{field}.target is invalid")
        if target in archive_targets or target in unavailable_targets:
            raise CacheError(f"duplicate runtime target: {target}")
        unavailable_targets.add(target)
        _bounded_runtime_text(
            unavailable.get("platform"),
            f"{field}.platform",
            limit=MAX_RUNTIME_LABEL_BYTES,
        )
        _bounded_runtime_text(
            unavailable.get("reason"),
            f"{field}.reason",
            limit=MAX_RUNTIME_REASON_BYTES,
        )
    return inventory


def _toml_scalar(value: object) -> str:
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, Mapping):
        entries: list[str] = []
        for key, item in sorted(
            cast(Mapping[object, object], value).items(), key=lambda pair: str(pair[0])
        ):
            if not isinstance(key, str) or not isinstance(item, str):
                raise CacheError("only string-to-string manifest maps may be updated")
            entries.append(f"{json.dumps(key)} = {json.dumps(item)}")
        return "{ " + ", ".join(entries) + " }" if entries else "{}"
    raise CacheError(f"unsupported manifest update value: {type(value).__name__}")


def _replace_manifest_fields(content: str, updates: Sequence[FieldUpdate]) -> str:
    lines = content.splitlines(keepends=True)
    for model_key, field, value in updates:
        if not (
            model_key == "meta" or MODEL_KEY_RE.fullmatch(model_key)
        ) or not re.fullmatch(r"[A-Za-z0-9_]+", field):
            raise CacheError("unsafe manifest update selector")
        headers = (
            {"[meta]"}
            if model_key == "meta"
            else {f"[models.{model_key}]", f'[models."{model_key}"]'}
        )
        in_section = False
        found = False
        for index, line in enumerate(lines):
            stripped = line.strip()
            if stripped in headers:
                in_section = True
                continue
            if in_section and stripped.startswith("["):
                break
            if in_section and re.match(rf"^{re.escape(field)}\s*=", stripped):
                newline = "\n" if line.endswith("\n") else ""
                lines[index] = f"{field} = {_toml_scalar(value)}{newline}"
                found = True
                break
        if not found:
            prefix = "meta" if model_key == "meta" else f"models.{model_key}"
            raise CacheError(f"manifest field {prefix}.{field} was not found")
    return "".join(lines)


def atomic_manifest_update(
    manifest: Manifest, updates: Sequence[FieldUpdate]
) -> Manifest:
    """Apply every field update under one lock and one validated atomic replace."""
    baseline_digest = hashlib.sha256(manifest.raw_bytes).digest()
    prospective: bytes | None = None
    replacement_returned = False
    replacement_durability_unknown = False
    try:
        with advisory_lock(manifest.path):
            current = _release_manifest_bytes(manifest.path, "models manifest")
            if hashlib.sha256(current).digest() != baseline_digest:
                raise CacheError(
                    "manifest changed during operation; refusing a lost update"
                )
            prospective_text = _replace_manifest_fields(
                current.decode("utf-8"), updates
            )
            prospective = prospective_text.encode("utf-8")
            validated = load_manifest(manifest.path, manifest.root, prospective)
            try:
                atomic_replace_bytes(manifest.path, prospective)
            except PlatformFileDurabilityUnknown:
                replacement_durability_unknown = True
                raise
            replacement_returned = True
            return validated
    except BaseException as error:
        committed = (
            replacement_returned
            or replacement_durability_unknown
            or isinstance(error, PlatformFileDurabilityUnknown)
        )
        if not committed:
            if isinstance(error, (PlatformFileError, OSError)):
                raise CacheError(f"atomic manifest update failed: {error}") from error
            raise
        visible_matches = False
        if prospective is not None:
            try:
                visible_matches = (
                    _release_manifest_bytes(manifest.path, "models manifest")
                    == prospective
                )
            except (CacheError, OSError):
                pass
        state = (
            "matches the validated update" if visible_matches else "must be inspected"
        )
        raise ManifestDurabilityUnknown(
            "manifest replacement is installed but durability is unknown; "
            + f"visible state {state}; retain matching archives and run validation before retry"
        ) from error


def _path_signature(
    root_fd: int, expected_entries: set[str], model_key: str
) -> dict[str, tuple[str, int, int, int, int, str]]:
    """Incrementally inventory one held artifact tree under strict admission caps."""
    if len(expected_entries) > MAX_CACHE_INVENTORY_ENTRIES:
        raise CacheError("cache inventory entry count exceeds the safe limit")
    entries: dict[str, tuple[str, int, int, int, int, str]] = {}

    def scan(directory_fd: int, prefix: PurePosixPath, depth: int) -> None:
        try:
            iterator = os.scandir(directory_fd)
        except OSError as error:
            raise CacheError(
                f"could not inspect cache inventory for {model_key}"
            ) from error
        with iterator:
            for entry in iterator:
                relative_path = prefix / entry.name
                relative = relative_path.as_posix()
                entry_depth = depth + 1
                if entry_depth > MAX_CACHE_INVENTORY_DEPTH:
                    raise CacheError(
                        "cache inventory path depth exceeds the safe limit"
                    )
                if len(entries) >= MAX_CACHE_INVENTORY_ENTRIES:
                    raise CacheError(
                        "cache inventory entry count exceeds the safe limit"
                    )
                if relative not in expected_entries:
                    raise CacheError(
                        f"unexpected cache content for {model_key}: {relative}"
                    )
                try:
                    item_stat = os.stat(
                        entry.name, dir_fd=directory_fd, follow_symlinks=False
                    )
                except OSError as error:
                    raise CacheError(
                        f"cache inventory entry changed while inspected: {relative}"
                    ) from error
                link_target = ""
                if stat.S_ISDIR(item_stat.st_mode):
                    item_type = "directory"
                elif stat.S_ISREG(item_stat.st_mode):
                    item_type = "file"
                elif stat.S_ISLNK(item_stat.st_mode):
                    item_type = "symlink"
                    try:
                        link_target = os.readlink(entry.name, dir_fd=directory_fd)
                    except OSError as error:
                        raise CacheError(
                            f"cache inventory link changed while inspected: {relative}"
                        ) from error
                else:
                    item_type = "special"
                entries[relative] = (
                    item_type,
                    item_stat.st_ino,
                    item_stat.st_size,
                    item_stat.st_mtime_ns,
                    item_stat.st_ctime_ns,
                    link_target,
                )
                if item_type == "directory":
                    try:
                        child_fd = os.open(
                            entry.name, _model_directory_flags(), dir_fd=directory_fd
                        )
                    except OSError as error:
                        raise CacheError(
                            f"cache directory changed while inspected: {relative}"
                        ) from error
                    try:
                        opened = os.fstat(child_fd)
                        if not os.path.samestat(item_stat, opened):
                            raise CacheError(
                                f"cache directory changed while inspected: {relative}"
                            )
                        scan(child_fd, relative_path, entry_depth)
                    finally:
                        os.close(child_fd)

    scan(root_fd, PurePosixPath(), 0)
    return entries


def _copy_regular_file_descriptor(
    descriptor: int,
    destination: BinaryIO,
    *,
    max_bytes: int | None = None,
    size_purpose: str = "file",
    rewind: bool = True,
) -> tuple[int, str]:
    """Copy one already-open regular file while proving its mutable state is stable."""
    before = os.fstat(descriptor)
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        raise CacheError(f"{size_purpose} is not a single-linked regular file")
    if max_bytes is not None and before.st_size > max_bytes:
        raise CacheError(f"{size_purpose} bytes exceed the safe size limit")
    if rewind:
        os.lseek(descriptor, 0, os.SEEK_SET)
    digest = hashlib.sha256()
    size = 0
    while chunk := os.read(descriptor, HASH_CHUNK_BYTES):
        size += len(chunk)
        if max_bytes is not None and size > max_bytes:
            raise CacheError(f"{size_purpose} bytes exceed the safe size limit")
        destination.write(chunk)
        digest.update(chunk)
    after = os.fstat(descriptor)
    if (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
    ) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    ):
        raise CacheError(f"{size_purpose} changed while it was snapshotted")
    return size, digest.hexdigest()


def _copy_regular_file(
    path: Path,
    destination: BinaryIO,
    *,
    max_bytes: int | None = None,
    size_purpose: str = "file",
) -> tuple[int, str]:
    """Copy and hash one immutable regular-file view without buffering it in memory."""
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    descriptor = os.open(path, flags)
    try:
        return _copy_regular_file_descriptor(
            descriptor,
            destination,
            max_bytes=max_bytes,
            size_purpose=size_purpose,
            rewind=False,
        )
    finally:
        os.close(descriptor)


def _read_small_regular_file(path: Path, *, limit: int = 1024) -> bytes:
    with tempfile.TemporaryFile() as temporary:
        _copy_regular_file(
            path,
            temporary,
            max_bytes=limit,
            size_purpose="cache metadata file",
        )
        temporary.seek(0)
        return temporary.read()


def _open_verified_model_directory_path(path: Path, context: str) -> int:
    """Open one existing path as a stable no-follow directory authority."""
    try:
        before = path.lstat()
        descriptor = os.open(path, _model_directory_flags())
    except OSError as error:
        raise CacheError(
            f"{context} is missing, a symlink, or not a directory"
        ) from error
    opened = os.fstat(descriptor)
    if (
        not stat.S_ISDIR(before.st_mode)
        or not stat.S_ISDIR(opened.st_mode)
        or not os.path.samestat(before, opened)
    ):
        os.close(descriptor)
        raise CacheError(f"{context} changed while it was opened")
    return descriptor


def _open_existing_model_directory_at(parent_fd: int, name: str, context: str) -> int:
    name = _model_entry_name(name, context)
    try:
        descriptor = os.open(name, _model_directory_flags(), dir_fd=parent_fd)
    except OSError as error:
        raise CacheError(
            f"{context} is missing, a symlink, or not a directory"
        ) from error
    if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
        os.close(descriptor)
        raise CacheError(f"{context} is not a directory")
    return descriptor


def _open_existing_model_parent_at(root_fd: int, path: PurePosixPath) -> int:
    current_fd = os.dup(root_fd)
    try:
        for part in path.parts[:-1]:
            next_fd = _open_existing_model_directory_at(
                current_fd, part, "cache source directory"
            )
            os.close(current_fd)
            current_fd = next_fd
        return current_fd
    except BaseException:
        os.close(current_fd)
        raise


def _open_regular_model_file_at(parent_fd: int, name: str, context: str) -> int:
    name = _model_entry_name(name, context)
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    try:
        before = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        descriptor = os.open(name, flags, dir_fd=parent_fd)
    except OSError as error:
        raise CacheError(f"{context} is missing or unsafe") from error
    opened = os.fstat(descriptor)
    if (
        not stat.S_ISREG(opened.st_mode)
        or opened.st_nlink != 1
        or not os.path.samestat(before, opened)
    ):
        os.close(descriptor)
        raise CacheError(f"{context} is not a stable single-linked regular file")
    return descriptor


def _read_small_regular_file_descriptor(descriptor: int, *, limit: int = 1024) -> bytes:
    with tempfile.TemporaryFile() as temporary:
        _copy_regular_file_descriptor(
            descriptor,
            temporary,
            max_bytes=limit,
            size_purpose="cache metadata file",
        )
        temporary.seek(0)
        return temporary.read()


def _create_model_directory_at(parent_fd: int, name: str, context: str) -> int:
    name = _model_entry_name(name, context)
    try:
        os.mkdir(name, mode=0o700, dir_fd=parent_fd)
    except OSError as error:
        raise CacheError(f"could not create private {context}: {name}") from error
    try:
        descriptor = os.open(name, _model_directory_flags(), dir_fd=parent_fd)
    except OSError as error:
        raise CacheError(f"private {context} changed while it was opened") from error
    try:
        if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
            raise CacheError(f"private {context} is not a directory")
        os.fchmod(descriptor, 0o755)
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _write_new_model_bytes_at(parent_fd: int, name: str, content: bytes) -> int:
    name = _model_entry_name(name, "staged model file")
    flags = (
        os.O_RDWR
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor = os.open(name, flags, 0o600, dir_fd=parent_fd)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as output:
            output.write(content)
            output.flush()
            os.fchmod(descriptor, 0o644)
            os.fsync(descriptor)
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _copy_model_descriptor_to_new_file_at(
    source_fd: int,
    root_fd: int,
    path: PurePosixPath,
    *,
    max_bytes: int,
    size_purpose: str,
) -> tuple[int, int, str]:
    parent_fd = _open_model_parent_at(root_fd, path)
    descriptor = -1
    try:
        name = _model_entry_name(path.name, "staged model file")
        flags = (
            os.O_RDWR
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        descriptor = os.open(name, flags, 0o600, dir_fd=parent_fd)
        with os.fdopen(descriptor, "wb", closefd=False) as output:
            copied, digest = _copy_regular_file_descriptor(
                source_fd,
                output,
                max_bytes=max_bytes,
                size_purpose=size_purpose,
            )
            output.flush()
            os.fchmod(descriptor, 0o644)
            os.fsync(descriptor)
        return descriptor, copied, digest
    except BaseException:
        if descriptor >= 0:
            os.close(descriptor)
        raise
    finally:
        os.close(parent_fd)


def _required_directories(model: ModelRecord) -> set[str]:
    directories = {"refs", "snapshots", f"snapshots/{model.upstream_revision}"}
    for relative in model.required_files:
        parent = PurePosixPath(relative).parent
        while parent != PurePosixPath("."):
            directories.add(f"snapshots/{model.upstream_revision}/{parent.as_posix()}")
            parent = parent.parent
    return directories


@contextmanager
def snapshot_cache_artifact(
    cache_source: Path,
    model: ModelRecord,
    staging_parent: Path,
    *,
    staging_parent_fd: int | None = None,
) -> Iterator[CuratedSnapshot]:
    """Copy one exact live cache snapshot into regular-file-only private staging."""
    if not cache_source.is_absolute() or cache_source == Path(cache_source.anchor):
        raise CacheError("prepare requires one explicit absolute non-root cache source")
    if cache_source.is_symlink() or not cache_source.is_dir():
        raise CacheError(
            f"cache source must be a regular directory, not a symlink: {cache_source}"
        )
    if not model.upstream_revision:
        raise CacheError(f"{model.key} has unresolved upstream_revision provenance")

    _require_secure_model_install_primitives()
    source_root_fd = -1
    artifact_fd = -1
    owned_staging_parent_fd = -1
    stage_artifact_fd = -1
    source_fds: list[int] = []
    staged_fds: list[int] = []
    try:
        source_root_fd = _open_verified_model_directory_path(
            cache_source, "cache source"
        )
        artifact_fd = _open_existing_model_directory_at(
            source_root_fd, model.fastembed_cache_dir, "cache artifact"
        )
        expected_entries = _required_directories(model)
        expected_entries.add("refs/main")

        refs_parent_fd = _open_existing_model_parent_at(
            artifact_fd, PurePosixPath("refs/main")
        )
        try:
            refs_fd = _open_regular_model_file_at(
                refs_parent_fd, "main", "cache refs/main"
            )
        finally:
            os.close(refs_parent_fd)
        source_fds.append(refs_fd)
        refs_bytes = _read_small_regular_file_descriptor(refs_fd)
        try:
            refs_revision = refs_bytes.decode("utf-8").strip()
        except UnicodeDecodeError as error:
            raise CacheError(f"{model.key} refs/main is not UTF-8") from error
        if refs_revision != model.upstream_revision:
            raise CacheError(
                f"{model.key} revision mismatch: manifest {model.upstream_revision}, "
                + f"cache refs/main {refs_revision}"
            )

        source_by_relative: dict[str, int] = {}
        for relative in model.required_files:
            cache_path = (
                PurePosixPath("snapshots")
                / model.upstream_revision
                / PurePosixPath(relative)
            )
            cache_relative = cache_path.as_posix()
            expected_entries.add(cache_relative)
            parent_fd = _open_existing_model_parent_at(artifact_fd, cache_path)
            try:
                source_stat = os.stat(
                    cache_path.name, dir_fd=parent_fd, follow_symlinks=False
                )
                if stat.S_ISREG(source_stat.st_mode):
                    source_fd = _open_regular_model_file_at(
                        parent_fd,
                        cache_path.name,
                        f"cache source for {model.key}:{relative}",
                    )
                elif stat.S_ISLNK(source_stat.st_mode):
                    target = os.readlink(cache_path.name, dir_fd=parent_fd)
                    if (
                        "\\" in target
                        or "\0" in target
                        or PurePosixPath(target).is_absolute()
                    ):
                        raise CacheError(f"unsafe cache blob link: {cache_relative}")
                    normalized = PurePosixPath(
                        posixpath.normpath(str(cache_path.parent / target))
                    )
                    if len(normalized.parts) != 2 or normalized.parts[0] != "blobs":
                        raise CacheError(
                            f"cache blob link escapes artifact: {cache_relative}"
                        )
                    blob_name = normalized.parts[1]
                    if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", blob_name):
                        raise CacheError(
                            f"cache blob link has an invalid digest name: {cache_relative}"
                        )
                    expected_entries.update({"blobs", f"blobs/{blob_name}"})
                    blobs_fd = _open_existing_model_directory_at(
                        artifact_fd, "blobs", "cache blobs directory"
                    )
                    try:
                        source_fd = _open_regular_model_file_at(
                            blobs_fd,
                            blob_name,
                            f"cache blob for {model.key}:{relative}",
                        )
                    finally:
                        os.close(blobs_fd)
                else:
                    raise CacheError(
                        f"unexpected special cache entry: {cache_relative}"
                    )
            finally:
                os.close(parent_fd)
            source_fds.append(source_fd)
            source_by_relative[relative] = source_fd

        before_inventory = _path_signature(artifact_fd, expected_entries, model.key)
        missing = sorted(expected_entries - set(before_inventory))
        special = sorted(
            relative
            for relative, signature in before_inventory.items()
            if signature[0] == "special"
        )
        if missing:
            raise CacheError(f"incomplete cache for {model.key}: {', '.join(missing)}")
        if special:
            raise CacheError(
                f"unexpected special cache entries for {model.key}: {', '.join(special)}"
            )

        initial_total_bytes = 0
        for relative in model.required_files:
            source_state = os.fstat(source_by_relative[relative])
            if source_state.st_size > MAX_MODEL_MEMBER_BYTES:
                raise CacheError(
                    "model snapshot member bytes exceed the safe size limit: "
                    + f"{model.key}:{relative}"
                )
            initial_total_bytes += source_state.st_size
            if initial_total_bytes > MAX_MODEL_TOTAL_BYTES:
                raise CacheError(
                    "model snapshot total bytes exceed the safe size limit"
                )

        if staging_parent_fd is None:
            staging_parent.mkdir(parents=True, exist_ok=False, mode=0o700)
            owned_staging_parent_fd = _open_verified_model_directory_path(
                staging_parent, "private snapshot parent"
            )
            effective_staging_parent_fd = owned_staging_parent_fd
        else:
            effective_staging_parent_fd = staging_parent_fd
        stage_artifact_fd = _create_model_directory_at(
            effective_staging_parent_fd,
            model.fastembed_cache_dir,
            "staged model artifact",
        )
        stage_artifact = staging_parent / model.fastembed_cache_dir
        refs_stage_fd = _create_model_directory_at(
            stage_artifact_fd, "refs", "staged refs directory"
        )
        try:
            staged_fds.append(
                _write_new_model_bytes_at(
                    refs_stage_fd,
                    "main",
                    (model.upstream_revision + "\n").encode(),
                )
            )
        finally:
            os.close(refs_stage_fd)

        captured: list[SnapshotFile] = []
        captured_bytes = 0
        for relative in model.required_files:
            remaining_total_bytes = MAX_MODEL_TOTAL_BYTES - captured_bytes
            copy_limit = min(MAX_MODEL_MEMBER_BYTES, remaining_total_bytes)
            size_purpose = f"model snapshot member for {model.key}:{relative}"
            if remaining_total_bytes < MAX_MODEL_MEMBER_BYTES:
                size_purpose = "model snapshot total"
            staged_path = (
                PurePosixPath("snapshots")
                / model.upstream_revision
                / PurePosixPath(relative)
            )
            staged_fd, copied, digest = _copy_model_descriptor_to_new_file_at(
                source_by_relative[relative],
                stage_artifact_fd,
                staged_path,
                max_bytes=copy_limit,
                size_purpose=size_purpose,
            )
            staged_fds.append(staged_fd)
            captured_bytes += copied
            expected_file_digest = model.upstream_file_sha256.get(relative)
            if not expected_file_digest:
                raise CacheError(
                    f"{model.key} lacks upstream byte evidence for {relative}"
                )
            if digest != expected_file_digest:
                raise CacheError(
                    f"{model.key} upstream byte SHA-256 mismatch for {relative}"
                )
            archive_digest = model.file_sha256.get(relative)
            if archive_digest and digest != archive_digest:
                raise CacheError(
                    f"{model.key} archive file SHA-256 mismatch for {relative}"
                )
            upstream_digest = model.upstream_lfs_sha256.get(relative)
            if upstream_digest and digest != upstream_digest:
                raise CacheError(
                    f"{model.key} upstream LFS SHA-256 mismatch for {relative}"
                )
            destination = stage_artifact.joinpath(*staged_path.parts)
            captured.append(SnapshotFile(relative, destination, digest, staged_fd))

        after_inventory = _path_signature(artifact_fd, expected_entries, model.key)
        if after_inventory != before_inventory:
            raise CacheError(f"live cache changed while {model.key} was snapshotted")
        current_artifact = os.stat(
            model.fastembed_cache_dir,
            dir_fd=source_root_fd,
            follow_symlinks=False,
        )
        if not os.path.samestat(current_artifact, os.fstat(artifact_fd)):
            raise CacheError(f"live cache changed while {model.key} was snapshotted")
        yield CuratedSnapshot(
            model=model,
            staged_artifact=stage_artifact,
            files=tuple(captured),
            artifact_descriptor=stage_artifact_fd,
        )
    finally:
        for descriptor in reversed(staged_fds):
            os.close(descriptor)
        for descriptor in reversed(source_fds):
            os.close(descriptor)
        if stage_artifact_fd >= 0:
            os.close(stage_artifact_fd)
        if owned_staging_parent_fd >= 0:
            os.close(owned_staging_parent_fd)
        if artifact_fd >= 0:
            os.close(artifact_fd)
        if source_root_fd >= 0:
            os.close(source_root_fd)


def _archive_directories(model: ModelRecord) -> tuple[str, ...]:
    prefix = model.fastembed_cache_dir
    relative = _required_directories(model)
    return tuple([prefix] + [f"{prefix}/{item}" for item in sorted(relative)])


def build_deterministic_archive(
    snapshot: CuratedSnapshot,
    destination: Path,
    *,
    destination_dir_fd: int | None = None,
) -> tuple[int, str]:
    """Create a portable deterministic gzip/ustar from the curated private snapshot."""
    model = snapshot.model
    accepted_files: dict[str, SnapshotFile] = {}
    for item in snapshot.files:
        if item.relative_path in accepted_files:
            raise CacheError(
                f"accepted snapshot contains duplicate file: {item.relative_path}"
            )
        accepted_files[item.relative_path] = item
    if set(accepted_files) != set(model.required_files):
        raise CacheError("accepted snapshot does not cover the required model files")
    if destination_dir_fd is None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination_name: str | Path = destination
    else:
        destination_name = _model_entry_name(
            destination.name, "prepared archive destination"
        )
    flags = os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    descriptor = os.open(destination_name, flags, 0o600, dir_fd=destination_dir_fd)
    try:
        with os.fdopen(descriptor, "w+b", closefd=True) as raw_output:
            descriptor = -1
            with gzip.GzipFile(
                fileobj=raw_output, mode="wb", filename="", mtime=0
            ) as compressed:
                with tarfile.open(
                    fileobj=compressed, mode="w|", format=tarfile.USTAR_FORMAT
                ) as archive:
                    for directory in _archive_directories(model):
                        info = tarfile.TarInfo(directory)
                        info.type = tarfile.DIRTYPE
                        info.mode = 0o755
                        info.uid = info.gid = 0
                        info.uname = info.gname = ""
                        info.mtime = 0
                        archive.addfile(info)
                    reference_name = f"{model.fastembed_cache_dir}/refs/main"
                    reference_bytes = (model.upstream_revision + "\n").encode()
                    info = tarfile.TarInfo(reference_name)
                    info.size = len(reference_bytes)
                    info.mode = 0o644
                    info.uid = info.gid = 0
                    info.uname = info.gname = ""
                    info.mtime = 0
                    archive.addfile(info, io.BytesIO(reference_bytes))

                    total_model_bytes = 0
                    for relative, item in sorted(accepted_files.items()):
                        expected_digest = model.upstream_file_sha256.get(relative)
                        if not expected_digest or item.sha256 != expected_digest:
                            raise CacheError(
                                f"{model.key} accepted snapshot SHA-256 does not match "
                                + f"upstream byte evidence for {relative}"
                            )
                        archive_digest = model.file_sha256.get(relative)
                        if archive_digest and item.sha256 != archive_digest:
                            raise CacheError(
                                f"{model.key} accepted snapshot SHA-256 does not match "
                                + f"archive byte evidence for {relative}"
                            )
                        lfs_digest = model.upstream_lfs_sha256.get(relative)
                        if lfs_digest and item.sha256 != lfs_digest:
                            raise CacheError(
                                f"{model.key} accepted snapshot SHA-256 does not match "
                                + f"upstream LFS evidence for {relative}"
                            )
                        archive_name = (
                            f"{model.fastembed_cache_dir}/snapshots/{model.upstream_revision}/"
                            + relative
                        )
                        source_context = (
                            immutable_file_descriptor_snapshot(
                                item.staged_descriptor,
                                max_bytes=MAX_MODEL_MEMBER_BYTES,
                                size_purpose=(
                                    f"staged model source for {model.key}:{relative}"
                                ),
                            )
                            if item.staged_descriptor is not None
                            else immutable_file_snapshot(
                                item.staged_path,
                                max_bytes=MAX_MODEL_MEMBER_BYTES,
                                size_purpose=(
                                    f"staged model source for {model.key}:{relative}"
                                ),
                            )
                        )
                        with (
                            source_context as (
                                input_file,
                                source_size,
                                source_digest,
                            )
                        ):
                            if source_digest != item.sha256:
                                raise CacheError(
                                    f"{model.key} consumed bytes do not match the accepted "
                                    + f"snapshot SHA-256 for {relative}"
                                )
                            total_model_bytes += source_size
                            if total_model_bytes > MAX_MODEL_TOTAL_BYTES:
                                raise CacheError(
                                    "model archive logical output exceeds the safe size limit"
                                )
                            info = tarfile.TarInfo(archive_name)
                            info.size = source_size
                            info.mode = 0o644
                            info.uid = info.gid = 0
                            info.uname = info.gname = ""
                            info.mtime = 0
                            archive.addfile(info, input_file)
            raw_output.flush()
            os.fchmod(raw_output.fileno(), 0o644)
            if destination_dir_fd is None:
                _assert_archive_path_identity(raw_output.fileno(), destination)
            else:
                _assert_archive_entry_identity(
                    raw_output.fileno(), destination_dir_fd, str(destination_name)
                )
            os.fsync(raw_output.fileno())
            expected_state = os.fstat(raw_output.fileno())
            raw_output.seek(0)
            digest = hashlib.sha256()
            size = 0
            while chunk := raw_output.read(HASH_CHUNK_BYTES):
                digest.update(chunk)
                size += len(chunk)
            final_state = os.fstat(raw_output.fileno())
            if (
                expected_state.st_dev,
                expected_state.st_ino,
                expected_state.st_size,
                expected_state.st_mtime_ns,
                expected_state.st_ctime_ns,
            ) != (
                final_state.st_dev,
                final_state.st_ino,
                final_state.st_size,
                final_state.st_mtime_ns,
                final_state.st_ctime_ns,
            ):
                raise CacheError("temporary archive changed while it was hashed")
            if destination_dir_fd is None:
                _assert_archive_path_identity(raw_output.fileno(), destination)
            else:
                _assert_archive_entry_identity(
                    raw_output.fileno(), destination_dir_fd, str(destination_name)
                )
    except BaseException:
        if descriptor >= 0:
            os.close(descriptor)
            descriptor = -1
        _report_preserved_archive_entry(destination)
        raise
    return size, digest.hexdigest()


def _sync_archive_publication(
    destination: Path, *, parent_descriptor: int | None = None
) -> None:
    """Persist one published archive using the strongest portable platform primitive."""
    if parent_descriptor is not None:
        directory_state = os.fstat(parent_descriptor)
        if not stat.S_ISDIR(directory_state.st_mode):
            raise CacheError(f"archive parent is not a directory: {destination.parent}")
        os.fsync(parent_descriptor)
        return
    if _WINDOWS:
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_CLOEXEC", 0)
        descriptor = os.open(destination, flags)
        try:
            installed_state = os.fstat(descriptor)
            if not stat.S_ISREG(installed_state.st_mode):
                raise CacheError(
                    f"published archive is not a regular file: {destination}"
                )
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return

    parent = destination.parent
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor = os.open(parent, flags)
    try:
        directory_state = os.fstat(descriptor)
        if not stat.S_ISDIR(directory_state.st_mode):
            raise CacheError(f"archive parent is not a directory: {parent}")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _assert_archive_path_identity(descriptor: int, path: Path) -> None:
    """Require a pathname to still identify the descriptor-backed regular file."""
    descriptor_state = os.fstat(descriptor)
    try:
        path_state = path.lstat()
    except FileNotFoundError as error:
        raise CacheError("temporary archive changed before publication") from error
    if (
        not stat.S_ISREG(descriptor_state.st_mode)
        or not stat.S_ISREG(path_state.st_mode)
        or not os.path.samestat(descriptor_state, path_state)
    ):
        raise CacheError("temporary archive changed before publication")


def _assert_archive_entry_identity(descriptor: int, parent_fd: int, name: str) -> None:
    descriptor_state = os.fstat(descriptor)
    try:
        entry_state = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except OSError as error:
        raise CacheError("temporary archive changed before validation") from error
    if (
        not stat.S_ISREG(descriptor_state.st_mode)
        or not stat.S_ISREG(entry_state.st_mode)
        or not os.path.samestat(descriptor_state, entry_state)
    ):
        raise CacheError("temporary archive changed before validation")


def _report_preserved_archive_entry(path: Path) -> None:
    """Report a retained archive entry without reopening it for deletion."""
    try:
        path.lstat()
    except FileNotFoundError:
        return
    except OSError:
        pass
    print(
        f"warning: preserved archive recovery entry {path}; "
        + "safe identity-bound deletion is unavailable",
        file=sys.stderr,
    )


def _link_descriptor_noreplace(
    descriptor: int,
    destination: Path,
    *,
    destination_dir_fd: int = AT_FDCWD,
    publication_state: RenamePublicationState | None = None,
) -> None:
    """Atomically link the descriptor's inode at a new Linux pathname."""
    libc = ctypes.CDLL(None, use_errno=True)
    raw_function = getattr(libc, "linkat", None)
    if raw_function is None:
        raise CacheError("this platform lacks descriptor-anchored archive publication")
    linkat = cast(Callable[[int, bytes, int, bytes, int], int], raw_function)
    result = linkat(
        descriptor,
        b"",
        destination_dir_fd,
        os.fsencode(destination),
        AT_EMPTY_PATH,
    )
    if result == 0:
        if publication_state is not None:
            publication_state.renamed = True
        return
    error_number = ctypes.get_errno()
    if error_number in {errno.EEXIST, errno.ENOTEMPTY}:
        raise FileExistsError(error_number, os.strerror(error_number), destination)
    raise OSError(error_number, os.strerror(error_number), destination)


def _assert_reviewed_archive_descriptor(
    archive_file: BinaryIO,
    *,
    expected_size: int,
    expected_sha256: str,
) -> None:
    """Verify exact held output bytes and stable state before publication."""
    before = os.fstat(archive_file.fileno())
    if not stat.S_ISREG(before.st_mode) or before.st_size != expected_size:
        raise CacheError("published archive bytes do not match the reviewed size")
    archive_file.seek(0)
    digest = hashlib.sha256()
    size = 0
    while chunk := archive_file.read(HASH_CHUNK_BYTES):
        size += len(chunk)
        if size > expected_size:
            raise CacheError("published archive bytes exceed the reviewed size")
        digest.update(chunk)
    after = os.fstat(archive_file.fileno())
    if (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
    ) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    ):
        raise CacheError("published archive changed during reviewed verification")
    if size != expected_size or digest.hexdigest() != expected_sha256:
        raise CacheError("published archive bytes do not match the reviewed digest")


def _publish_archive_noreplace(
    source: Path,
    destination: Path,
    *,
    expected_size: int,
    expected_sha256: str,
) -> None:
    """Snapshot, verify, and durably publish an archive without clobbering."""
    if expected_size < 0 or expected_size > MAX_MODEL_ARCHIVE_BYTES:
        raise CacheError("reviewed archive size exceeds the safe size limit")
    if not SHA256_RE.fullmatch(expected_sha256):
        raise CacheError("reviewed archive SHA-256 is invalid")

    descriptor = -1
    parent_descriptor = -1
    temporary: Path | None = None
    publication_state = RenamePublicationState()
    try:
        try:
            with immutable_file_snapshot(
                source,
                max_bytes=MAX_MODEL_ARCHIVE_BYTES,
                size_purpose="reviewed archive",
            ) as (reviewed_source, source_size, source_sha256):
                if source_size != expected_size or source_sha256 != expected_sha256:
                    raise CacheError(
                        "archive source does not match the reviewed size and SHA-256"
                    )

                descriptor_anchored = not _WINDOWS and sys.platform.startswith("linux")
                if descriptor_anchored:
                    expected_parent = destination.parent.lstat()
                    if not stat.S_ISDIR(expected_parent.st_mode):
                        raise CacheError(
                            f"archive parent is not a directory: {destination.parent}"
                        )
                    parent_descriptor = os.open(
                        destination.parent,
                        os.O_RDONLY
                        | getattr(os, "O_CLOEXEC", 0)
                        | getattr(os, "O_DIRECTORY", 0)
                        | getattr(os, "O_NOFOLLOW", 0),
                    )
                    opened_parent = os.fstat(parent_descriptor)
                    if not os.path.samestat(expected_parent, opened_parent):
                        raise CacheError("archive parent changed while it was opened")
                    anonymous_flag = getattr(os, "O_TMPFILE", 0)
                    if anonymous_flag == 0:
                        raise CacheError(
                            "this platform lacks anonymous archive staging"
                        )
                    try:
                        descriptor = os.open(
                            ".",
                            os.O_RDWR | anonymous_flag | getattr(os, "O_CLOEXEC", 0),
                            0o600,
                            dir_fd=parent_descriptor,
                        )
                    except OSError as error:
                        raise CacheError(
                            "archive filesystem lacks secure anonymous staging"
                        ) from error
                else:
                    descriptor, temporary_name = tempfile.mkstemp(
                        prefix=f".{destination.name}.",
                        suffix=".tmp",
                        dir=destination.parent,
                    )
                    temporary = Path(temporary_name)
                with os.fdopen(descriptor, "w+b", closefd=True) as output:
                    descriptor = -1
                    reviewed_source.seek(0)
                    shutil.copyfileobj(reviewed_source, output, HASH_CHUNK_BYTES)
                    output.flush()
                    # Apply final metadata before fsync so the one flush covers data and mode.
                    os.fchmod(output.fileno(), 0o644)
                    if temporary is not None:
                        _assert_archive_path_identity(output.fileno(), temporary)
                    os.fsync(output.fileno())
                    _assert_reviewed_archive_descriptor(
                        output,
                        expected_size=expected_size,
                        expected_sha256=expected_sha256,
                    )
                    if descriptor_anchored:
                        _link_descriptor_noreplace(
                            output.fileno(),
                            Path(destination.name),
                            destination_dir_fd=parent_descriptor,
                            publication_state=publication_state,
                        )
                        installed_state = os.stat(
                            destination.name,
                            dir_fd=parent_descriptor,
                            follow_symlinks=False,
                        )
                        if not stat.S_ISREG(
                            installed_state.st_mode
                        ) or not os.path.samestat(
                            os.fstat(output.fileno()), installed_state
                        ):
                            raise CacheError(
                                "published archive changed during publication"
                            )
                    else:
                        if temporary is None:
                            raise CacheError("archive temporary path was not allocated")
                        _assert_archive_path_identity(output.fileno(), temporary)
                        atomic_rename_noreplace(
                            temporary,
                            destination,
                            publication_state=publication_state,
                        )
                        temporary = None
                        _assert_archive_path_identity(output.fileno(), destination)
            _sync_archive_publication(
                destination,
                parent_descriptor=(
                    parent_descriptor if parent_descriptor >= 0 else None
                ),
            )
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            if parent_descriptor >= 0:
                os.close(parent_descriptor)
            if temporary is not None:
                _report_preserved_archive_entry(temporary)
    except PlatformFileDurabilityUnknown:
        if publication_state.renamed:
            _report_preserved_archive_entry(destination)
        raise
    except BaseException as error:
        if publication_state.renamed:
            _report_preserved_archive_entry(destination)
            raise PlatformFileDurabilityUnknown(destination) from error
        raise


@contextmanager
def immutable_file_snapshot(
    path: Path,
    *,
    max_bytes: int | None = None,
    size_purpose: str = "file",
) -> Iterator[tuple[BinaryIO, int, str]]:
    """Yield one anonymous immutable copy used for both verification and consumption."""
    if path.is_symlink():
        raise CacheError(f"file must be a regular non-symlink: {path}")
    with tempfile.TemporaryFile() as private:
        size, digest = _copy_regular_file(
            path,
            private,
            max_bytes=max_bytes,
            size_purpose=size_purpose,
        )
        private.flush()
        private.seek(0)
        yield private, size, digest


@contextmanager
def immutable_file_descriptor_snapshot(
    descriptor: int,
    *,
    max_bytes: int,
    size_purpose: str,
) -> Iterator[tuple[BinaryIO, int, str]]:
    """Copy one held regular descriptor into an anonymous immutable view."""
    with tempfile.TemporaryFile() as private:
        size, digest = _copy_regular_file_descriptor(
            descriptor,
            private,
            max_bytes=max_bytes,
            size_purpose=size_purpose,
        )
        private.flush()
        private.seek(0)
        yield private, size, digest


@contextmanager
def immutable_file_snapshot_at(
    parent_fd: int,
    name: str,
    *,
    max_bytes: int,
    size_purpose: str,
) -> Iterator[tuple[BinaryIO, int, str]]:
    """Snapshot one regular child through a held no-follow parent descriptor."""
    name = _model_entry_name(name, size_purpose)
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    try:
        descriptor = os.open(name, flags, dir_fd=parent_fd)
    except OSError as error:
        raise CacheError(f"{size_purpose} is missing or unsafe: {name}") from error
    with os.fdopen(descriptor, "rb") as source, tempfile.TemporaryFile() as private:
        before = os.fstat(source.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise CacheError(f"{size_purpose} is not a single-linked regular file")
        if before.st_size > max_bytes:
            raise CacheError(f"{size_purpose} bytes exceed the safe size limit")
        digest = hashlib.sha256()
        size = 0
        while chunk := source.read(HASH_CHUNK_BYTES):
            size += len(chunk)
            if size > max_bytes:
                raise CacheError(f"{size_purpose} bytes exceed the safe size limit")
            private.write(chunk)
            digest.update(chunk)
        after = os.fstat(source.fileno())
        if (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ):
            raise CacheError(f"{size_purpose} changed while it was snapshotted")
        private.flush()
        private.seek(0)
        yield private, size, digest.hexdigest()


def _safe_archive_member(name: str, expected_prefix: str) -> PurePosixPath:
    path = _validate_relative_path(name.rstrip("/"), "archive member")
    if not path.parts or path.parts[0] != expected_prefix:
        raise CacheError(f"archive member escapes {expected_prefix}: {name!r}")
    return path


def _expected_archive_files(model: ModelRecord) -> set[str]:
    prefix = model.fastembed_cache_dir
    result = {f"{prefix}/refs/main"}
    result.update(
        f"{prefix}/snapshots/{model.upstream_revision}/{relative}"
        for relative in model.required_files
    )
    return result


def _expected_archive_directories(model: ModelRecord) -> set[str]:
    return set(_archive_directories(model))


def _validate_single_gzip_stream(archive_file: BinaryIO) -> None:
    archive_file.seek(0)
    decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)
    decompressed_bytes = 0
    decompressed_limit = MAX_MODEL_TOTAL_BYTES + 64 * 1024 * 1024
    try:
        while chunk := archive_file.read(HASH_CHUNK_BYTES):
            pending = chunk
            while pending:
                output = decompressor.decompress(pending, HASH_CHUNK_BYTES)
                decompressed_bytes += len(output)
                if decompressed_bytes > decompressed_limit:
                    raise CacheError(
                        "model archive decompressed stream exceeds the safe size limit"
                    )
                pending = decompressor.unconsumed_tail
                if decompressor.eof:
                    if decompressor.unused_data or archive_file.read(1):
                        raise CacheError(
                            "model archive must contain exactly one single gzip stream"
                        )
                    archive_file.seek(0)
                    return
    except zlib.error as error:
        raise CacheError("model archive is not a valid single gzip stream") from error
    raise CacheError("model archive gzip stream is missing an exact end-of-stream")


def _read_exact_bounded(source: gzip.GzipFile, size: int) -> bytes:
    content = bytearray()
    while len(content) < size:
        chunk = source.read(min(HASH_CHUNK_BYTES, size - len(content)))
        if not chunk:
            break
        content.extend(chunk)
    return bytes(content)


def _discard_exact_bounded(source: gzip.GzipFile, size: int) -> None:
    remaining = size
    while remaining:
        chunk = source.read(min(HASH_CHUNK_BYTES, remaining))
        if not chunk:
            raise CacheError("model archive tar stream is truncated")
        remaining -= len(chunk)


def _validate_raw_tar_zero_tail(source: gzip.GzipFile) -> None:
    """Consume bounded, block-aligned zero padding through decompressed EOF."""
    padding_bytes = tarfile.BLOCKSIZE
    while True:
        remaining = tarfile.RECORDSIZE - padding_bytes + 1
        chunk = source.read(min(HASH_CHUNK_BYTES, remaining))
        if not chunk:
            break
        padding_bytes += len(chunk)
        if padding_bytes > tarfile.RECORDSIZE:
            raise CacheError("model archive tar padding exceeds the safe limit")
        if chunk.strip(b"\0"):
            raise CacheError("model archive tar contains nonzero trailing data")
    if padding_bytes < 2 * tarfile.BLOCKSIZE or padding_bytes % tarfile.BLOCKSIZE:
        raise CacheError("model archive tar padding is incomplete or unaligned")


def _prevalidate_raw_tar_stream(archive_file: BinaryIO) -> None:
    """Apply bounds to raw headers before tarfile can consume extension bodies."""
    extension_types = {
        tarfile.XHDTYPE,
        tarfile.XGLTYPE,
        tarfile.GNUTYPE_LONGNAME,
        tarfile.GNUTYPE_LONGLINK,
        tarfile.SOLARIS_XHDTYPE,
    }
    archive_file.seek(0)
    expanded = gzip.GzipFile(fileobj=archive_file, mode="rb")
    member_count = 0
    total_logical_bytes = 0
    try:
        while True:
            header = _read_exact_bounded(expanded, tarfile.BLOCKSIZE)
            if not header:
                raise CacheError("model archive tar stream has no end marker")
            if len(header) != tarfile.BLOCKSIZE:
                raise CacheError("model archive tar header is truncated")
            if header == b"\0" * tarfile.BLOCKSIZE:
                _validate_raw_tar_zero_tail(expanded)
                return
            try:
                member = tarfile.TarInfo.frombuf(
                    header, encoding="utf-8", errors="surrogateescape"
                )
            except tarfile.HeaderError as error:
                raise CacheError("model archive tar header is invalid") from error
            member_count += 1
            if member_count > MAX_MODEL_ARCHIVE_MEMBERS:
                raise CacheError("model archive member count exceeds the safe limit")
            if member.size < 0:
                raise CacheError(
                    f"model archive member size exceeds the safe limit: {member.name!r}"
                )
            if member.type in extension_types and member.size > HASH_CHUNK_BYTES:
                raise CacheError(
                    "PAX/GNU extension body exceeds the safe metadata size limit"
                )
            if member.isreg():
                if member.size > MAX_MODEL_MEMBER_BYTES:
                    raise CacheError(
                        f"model archive member size exceeds the safe limit: {member.name!r}"
                    )
                total_logical_bytes += member.size
                if total_logical_bytes > MAX_MODEL_TOTAL_BYTES:
                    raise CacheError(
                        "model archive logical output exceeds the safe size limit"
                    )
            padded_size = (member.size + tarfile.BLOCKSIZE - 1) // tarfile.BLOCKSIZE
            _discard_exact_bounded(expanded, padded_size * tarfile.BLOCKSIZE)
    finally:
        expanded.close()
        archive_file.seek(0)


def _ensure_model_directory_at(root_fd: int, path: PurePosixPath) -> None:
    current_fd = os.dup(root_fd)
    try:
        for part in path.parts:
            next_fd = _open_or_create_model_directory_at(
                current_fd, part, mode=0o755, context="model archive directory"
            )
            os.fchmod(next_fd, 0o755)
            os.close(current_fd)
            current_fd = next_fd
    finally:
        os.close(current_fd)


def _open_model_parent_at(root_fd: int, path: PurePosixPath) -> int:
    current_fd = os.dup(root_fd)
    try:
        for part in path.parts[:-1]:
            next_fd = _open_or_create_model_directory_at(
                current_fd, part, mode=0o755, context="model archive directory"
            )
            os.close(current_fd)
            current_fd = next_fd
        return current_fd
    except BaseException:
        os.close(current_fd)
        raise


def _model_output_file_state(
    file_state: os.stat_result,
) -> tuple[int, int, int, int, int]:
    """Capture output fields that expose type, link, size, or in-place changes."""
    return (
        file_state.st_mode,
        file_state.st_nlink,
        file_state.st_size,
        file_state.st_mtime_ns,
        file_state.st_ctime_ns,
    )


def _capture_model_output_evidence(
    descriptor: int,
    *,
    expected_size: int,
    expected_sha256: str,
    path: PurePosixPath,
) -> ExtractedModelFileEvidence:
    """Reread a freshly written output descriptor and retain exact evidence."""
    before = os.fstat(descriptor)
    if (
        not stat.S_ISREG(before.st_mode)
        or before.st_nlink != 1
        or before.st_size != expected_size
    ):
        raise CacheError(f"extracted model output is invalid: {path.as_posix()!r}")
    os.lseek(descriptor, 0, os.SEEK_SET)
    digest = hashlib.sha256()
    size = 0
    while chunk := os.read(descriptor, HASH_CHUNK_BYTES):
        size += len(chunk)
        if size > expected_size:
            raise CacheError(
                f"extracted model output exceeds declared size: {path.as_posix()!r}"
            )
        digest.update(chunk)
    after = os.fstat(descriptor)
    actual_sha256 = digest.hexdigest()
    if (
        (after.st_dev, after.st_ino) != (before.st_dev, before.st_ino)
        or _model_output_file_state(after) != _model_output_file_state(before)
        or size != expected_size
        or actual_sha256 != expected_sha256
    ):
        raise CacheError(
            f"extracted model output bytes changed while captured: {path.as_posix()!r}"
        )
    return ExtractedModelFileEvidence(
        identity=(after.st_dev, after.st_ino),
        file_state=_model_output_file_state(after),
        sha256=actual_sha256,
    )


def _write_model_member_at(
    source: IO[bytes], root_fd: int, path: PurePosixPath, expected_size: int
) -> ExtractedModelFileEvidence:
    parent_fd = _open_model_parent_at(root_fd, path)
    try:
        flags = (
            os.O_RDWR
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        descriptor = os.open(path.name, flags, 0o600, dir_fd=parent_fd)
        with os.fdopen(descriptor, "w+b") as output:
            digest = hashlib.sha256()
            extracted_size = 0
            while chunk := source.read(HASH_CHUNK_BYTES):
                extracted_size += len(chunk)
                if extracted_size > expected_size:
                    raise CacheError(
                        f"model archive member exceeded declared size: {path.as_posix()!r}"
                    )
                written = output.write(chunk)
                if written != len(chunk):
                    raise CacheError(
                        f"short write while extracting model member: {path.as_posix()!r}"
                    )
                digest.update(chunk)
            if extracted_size != expected_size:
                raise CacheError(
                    f"model archive member ended before declared size: {path.as_posix()!r}"
                )
            output.flush()
            os.fchmod(output.fileno(), 0o644)
            os.fsync(output.fileno())
            return _capture_model_output_evidence(
                output.fileno(),
                expected_size=expected_size,
                expected_sha256=digest.hexdigest(),
                path=path,
            )
    finally:
        os.close(parent_fd)


def _read_model_member_at(root_fd: int, path: PurePosixPath, limit: int) -> bytes:
    parent_fd = _open_model_parent_at(root_fd, path)
    try:
        flags = (
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0)
        )
        descriptor = os.open(path.name, flags, dir_fd=parent_fd)
        with os.fdopen(descriptor, "rb") as source:
            state = os.fstat(source.fileno())
            if not stat.S_ISREG(state.st_mode) or state.st_size > limit:
                raise CacheError("model archive metadata file is missing or oversized")
            content = source.read(limit + 1)
            if len(content) > limit:
                raise CacheError("model archive metadata file is oversized")
            return content
    finally:
        os.close(parent_fd)


def _validate_model_output_tree(
    root_fd: int,
    model: ModelRecord,
    evidence: Mapping[str, ExtractedModelFileEvidence],
    *,
    sync: bool,
) -> None:
    """Validate the exact artifact inventory and every extracted leaf's bytes."""
    expected_files = _expected_archive_files(model)
    expected_directories = _expected_archive_directories(model)
    root_name = model.fastembed_cache_dir
    expected_entries = (expected_files | expected_directories) - {root_name}
    if set(evidence) != expected_files:
        raise CacheError(
            "model output evidence does not cover the exact file inventory"
        )
    if len(expected_entries) > MAX_CACHE_INVENTORY_ENTRIES:
        raise CacheError("model output inventory entry count exceeds the safe limit")
    seen: set[str] = set()

    def scan(directory_fd: int, prefix: PurePosixPath, depth: int) -> None:
        try:
            iterator = os.scandir(directory_fd)
        except OSError as error:
            raise CacheError("could not inspect model output inventory") from error
        with iterator:
            for entry in iterator:
                relative_path = prefix / entry.name
                relative = relative_path.as_posix()
                entry_depth = depth + 1
                if entry_depth > MAX_CACHE_INVENTORY_DEPTH:
                    raise CacheError("model output path depth exceeds the safe limit")
                if len(seen) >= MAX_CACHE_INVENTORY_ENTRIES:
                    raise CacheError(
                        "model output inventory entry count exceeds the safe limit"
                    )
                if relative not in expected_entries:
                    raise CacheError(f"unexpected model output inventory: {relative}")
                try:
                    before = os.stat(
                        entry.name,
                        dir_fd=directory_fd,
                        follow_symlinks=False,
                    )
                except OSError as error:
                    raise CacheError(
                        f"model output changed while inspected: {relative}"
                    ) from error
                seen.add(relative)
                if stat.S_ISDIR(before.st_mode):
                    if relative not in expected_directories:
                        raise CacheError(
                            f"model output file became a directory: {relative}"
                        )
                    try:
                        child_fd = os.open(
                            entry.name,
                            _model_directory_flags(),
                            dir_fd=directory_fd,
                        )
                    except OSError as error:
                        raise CacheError(
                            f"model output directory changed while opened: {relative}"
                        ) from error
                    try:
                        opened = os.fstat(child_fd)
                        if not os.path.samestat(before, opened):
                            raise CacheError(
                                f"model output directory identity changed: {relative}"
                            )
                        scan(child_fd, relative_path, entry_depth)
                        if sync:
                            os.fsync(child_fd)
                    finally:
                        os.close(child_fd)
                    continue
                if not stat.S_ISREG(before.st_mode) or relative not in expected_files:
                    raise CacheError(
                        f"model output entry is not an expected regular file: {relative}"
                    )
                expected = evidence[relative]
                flags = (
                    os.O_RDONLY
                    | getattr(os, "O_CLOEXEC", 0)
                    | getattr(os, "O_NOFOLLOW", 0)
                    | getattr(os, "O_NONBLOCK", 0)
                )
                try:
                    file_fd = os.open(entry.name, flags, dir_fd=directory_fd)
                except OSError as error:
                    raise CacheError(
                        f"model output file changed while opened: {relative}"
                    ) from error
                try:
                    opened = os.fstat(file_fd)
                    if (
                        not os.path.samestat(before, opened)
                        or (opened.st_dev, opened.st_ino) != expected.identity
                        or _model_output_file_state(opened) != expected.file_state
                    ):
                        raise CacheError(
                            f"model output file identity changed after extraction: {relative}"
                        )
                    digest = hashlib.sha256()
                    size = 0
                    while chunk := os.read(file_fd, HASH_CHUNK_BYTES):
                        size += len(chunk)
                        if size > expected.file_state[2]:
                            raise CacheError(
                                f"model output file exceeds extracted size: {relative}"
                            )
                        digest.update(chunk)
                    after = os.fstat(file_fd)
                    if (
                        (after.st_dev, after.st_ino) != expected.identity
                        or _model_output_file_state(after) != expected.file_state
                        or size != expected.file_state[2]
                        or digest.hexdigest() != expected.sha256
                    ):
                        raise CacheError(
                            f"model output file bytes changed after extraction: {relative}"
                        )
                    if sync:
                        os.fsync(file_fd)
                        synced = os.fstat(file_fd)
                        if (
                            synced.st_dev,
                            synced.st_ino,
                        ) != expected.identity or _model_output_file_state(
                            synced
                        ) != expected.file_state:
                            raise CacheError(
                                f"model output file changed during sync: {relative}"
                            )
                finally:
                    os.close(file_fd)

    scan(root_fd, PurePosixPath(root_name), 0)
    if seen != expected_entries:
        missing = sorted(expected_entries - seen)
        raise CacheError("model output inventory is incomplete: " + ", ".join(missing))
    if sync:
        os.fsync(root_fd)


def extract_verified_model_archive(
    archive_file: BinaryIO,
    model: ModelRecord,
    staging: Path,
    *,
    staging_dir_fd: int | None = None,
    artifact_dir_fd: int | None = None,
) -> Mapping[str, ExtractedModelFileEvidence]:
    """Extract only the exact declared regular-file inventory into private staging."""
    if artifact_dir_fd is not None and staging_dir_fd is None:
        raise CacheError("model artifact descriptor requires a staging descriptor")
    expected_files = _expected_archive_files(model)
    expected_directories = _expected_archive_directories(model)
    seen_files: set[str] = set()
    seen_directories: set[str] = set()
    seen_names: set[str] = set()
    extracted_evidence: dict[str, ExtractedModelFileEvidence] = {}
    archive_file.seek(0, os.SEEK_END)
    archive_size = archive_file.tell()
    if archive_size > MAX_MODEL_ARCHIVE_BYTES:
        raise CacheError("model archive bytes exceed the safe size limit")
    archive_file.seek(0)
    _validate_single_gzip_stream(archive_file)
    _prevalidate_raw_tar_stream(archive_file)
    member_count = 0
    total_logical_bytes = 0
    with tarfile.open(fileobj=archive_file, mode="r:gz") as archive:
        for member in archive:
            member_count += 1
            if member_count > MAX_MODEL_ARCHIVE_MEMBERS:
                raise CacheError("model archive member count exceeds the safe limit")
            member_path = _safe_archive_member(member.name, model.fastembed_cache_dir)
            normalized_name = member_path.as_posix()
            if normalized_name in seen_names:
                raise CacheError(f"duplicate archive member: {member.name!r}")
            seen_names.add(normalized_name)
            if member.name.rstrip("/") != normalized_name:
                raise CacheError(f"non-canonical archive member: {member.name!r}")
            destination = staging.joinpath(*member_path.parts)
            descriptor_path = member_path
            if artifact_dir_fd is not None:
                if member_path.parts[0] != model.fastembed_cache_dir:
                    raise CacheError(f"unexpected archive content: {member.name!r}")
                descriptor_path = PurePosixPath(*member_path.parts[1:])
            if member.isdir():
                if member.size != 0 or normalized_name not in expected_directories:
                    raise CacheError(
                        f"unexpected archive directory inventory: {member.name!r}"
                    )
                if staging_dir_fd is None:
                    destination.mkdir(parents=True, exist_ok=True, mode=0o755)
                    os.chmod(destination, 0o755)
                elif artifact_dir_fd is None:
                    _ensure_model_directory_at(staging_dir_fd, member_path)
                elif descriptor_path == PurePosixPath("."):
                    os.fchmod(artifact_dir_fd, 0o755)
                else:
                    _ensure_model_directory_at(artifact_dir_fd, descriptor_path)
                seen_directories.add(normalized_name)
                continue
            if member.sparse is not None or any(
                key.startswith("GNU.sparse") or key == "SCHILY.realsize"
                for key in member.pax_headers
            ):
                raise CacheError(f"sparse archive member is forbidden: {member.name!r}")
            if not member.isreg():
                raise CacheError(f"unsupported archive member type: {member.name!r}")
            if normalized_name not in expected_files:
                raise CacheError(f"unexpected archive content: {member.name!r}")
            if member.size < 0 or member.size > MAX_MODEL_MEMBER_BYTES:
                raise CacheError(
                    f"model archive member size exceeds the safe limit: {member.name!r}"
                )
            total_logical_bytes += member.size
            if total_logical_bytes > MAX_MODEL_TOTAL_BYTES:
                raise CacheError(
                    "model archive logical output exceeds the safe size limit"
                )
            extracted = archive.extractfile(member)
            if extracted is None:
                raise CacheError(f"could not read archive member: {member.name!r}")
            try:
                if staging_dir_fd is None:
                    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
                    with destination.open("x+b") as output:
                        digest = hashlib.sha256()
                        extracted_size = 0
                        while chunk := extracted.read(HASH_CHUNK_BYTES):
                            extracted_size += len(chunk)
                            if extracted_size > member.size:
                                raise CacheError(
                                    "model archive member exceeded declared size: "
                                    + repr(member.name)
                                )
                            written = output.write(chunk)
                            if written != len(chunk):
                                raise CacheError(
                                    "short write while extracting model member: "
                                    + repr(member.name)
                                )
                            digest.update(chunk)
                        if extracted_size != member.size:
                            raise CacheError(
                                "model archive member ended before declared size: "
                                + repr(member.name)
                            )
                        output.flush()
                        os.fchmod(output.fileno(), 0o644)
                        os.fsync(output.fileno())
                        file_evidence = _capture_model_output_evidence(
                            output.fileno(),
                            expected_size=member.size,
                            expected_sha256=digest.hexdigest(),
                            path=member_path,
                        )
                elif artifact_dir_fd is None:
                    file_evidence = _write_model_member_at(
                        extracted, staging_dir_fd, member_path, member.size
                    )
                else:
                    file_evidence = _write_model_member_at(
                        extracted, artifact_dir_fd, descriptor_path, member.size
                    )
            finally:
                extracted.close()
            digest_value = file_evidence.sha256
            extracted_evidence[normalized_name] = file_evidence
            relative_snapshot = (
                f"{model.fastembed_cache_dir}/snapshots/{model.upstream_revision}/"
            )
            if normalized_name.startswith(relative_snapshot):
                relative = normalized_name.removeprefix(relative_snapshot)
                expected_digest = model.file_sha256.get(relative)
                if not expected_digest or digest_value != expected_digest:
                    raise CacheError(
                        f"file SHA-256 mismatch for {model.key}:{relative}"
                    )
                upstream_file_digest = model.upstream_file_sha256.get(relative)
                if not upstream_file_digest or digest_value != upstream_file_digest:
                    raise CacheError(
                        f"upstream byte SHA-256 mismatch for {model.key}:{relative}"
                    )
                upstream_digest = model.upstream_lfs_sha256.get(relative)
                if upstream_digest and digest_value != upstream_digest:
                    raise CacheError(
                        f"upstream LFS SHA-256 mismatch for {model.key}:{relative}"
                    )
            seen_files.add(normalized_name)
    missing = expected_files - seen_files
    if missing:
        raise CacheError(
            f"incomplete archive for {model.key}: {', '.join(sorted(missing))}"
        )
    missing_directories = expected_directories - seen_directories
    if missing_directories:
        raise CacheError(
            "incomplete archive directory inventory for "
            + f"{model.key}: {', '.join(sorted(missing_directories))}"
        )
    try:
        if staging_dir_fd is None:
            reference = staging / model.fastembed_cache_dir / "refs" / "main"
            reference_bytes = _read_small_regular_file(reference)
        elif artifact_dir_fd is None:
            reference_bytes = _read_model_member_at(
                staging_dir_fd,
                PurePosixPath(model.fastembed_cache_dir) / "refs" / "main",
                1024,
            )
        else:
            reference_bytes = _read_model_member_at(
                artifact_dir_fd,
                PurePosixPath("refs/main"),
                1024,
            )
        revision = reference_bytes.decode("utf-8").strip()
    except UnicodeDecodeError as error:
        raise CacheError(f"{model.key} refs/main is not UTF-8") from error
    if revision != model.upstream_revision:
        raise CacheError(
            f"{model.key} revision mismatch: expected {model.upstream_revision}, got {revision}"
        )
    if artifact_dir_fd is not None:
        _validate_model_output_tree(
            artifact_dir_fd,
            model,
            extracted_evidence,
            sync=False,
        )
    return extracted_evidence


def _select_models(
    manifest: Manifest, selector: str | None, model_type: str | None
) -> list[ModelRecord]:
    if selector:
        try:
            return [manifest.models[selector]]
        except KeyError as error:
            raise CacheError(f"unknown model artifact: {selector}") from error
    if model_type:
        return [
            model for model in manifest.models.values() if model_type in model.types
        ]
    defaults = [
        model for model in manifest.models.values() if "embedding" in model.default_for
    ]
    if len(defaults) != 1:
        raise CacheError("expected exactly one default embedding model")
    return defaults


def _explicit_nonroot_directory(
    value: str | os.PathLike[str], purpose: str, *, must_exist: bool
) -> Path:
    raw_value = os.fspath(value)
    if not raw_value or "\0" in raw_value:
        raise CacheError(f"{purpose} requires one explicit absolute non-root directory")
    if "\\" in raw_value and os.sep != "\\":
        raise CacheError(f"{purpose} directory contains a Windows path separator")
    if re.search(r"[/\\]{2,}", raw_value) or os.path.normpath(raw_value) != raw_value:
        raise CacheError(
            f"{purpose} directory must use one canonical absolute spelling"
        )
    candidate = Path(raw_value)
    if not candidate.is_absolute():
        raise CacheError(f"{purpose} requires one explicit absolute non-root directory")
    resolved = candidate.resolve(strict=False)
    if resolved == Path(resolved.anchor):
        raise CacheError(f"{purpose} requires one explicit absolute non-root directory")

    current = Path(candidate.anchor)
    for part in candidate.parts[1:]:
        current /= part
        try:
            entry_stat = current.lstat()
        except FileNotFoundError:
            break
        if stat.S_ISLNK(entry_stat.st_mode):
            raise CacheError(f"{purpose} directory traverses a symlink: {current}")
    if resolved.exists() and not resolved.is_dir():
        raise CacheError(f"{purpose} path is not a directory: {resolved}")
    if must_exist:
        try:
            target_stat = resolved.lstat()
        except FileNotFoundError as error:
            raise CacheError(
                f"{purpose} directory does not exist: {resolved}"
            ) from error
        if not stat.S_ISDIR(target_stat.st_mode):
            raise CacheError(f"{purpose} path is not a directory: {resolved}")
    return resolved


def command_validate(args: argparse.Namespace) -> None:
    manifest = load_manifest(args.manifest)
    inventory = authoritative_release_inventory(manifest)
    message = (
        f"Manifest valid: {len(manifest.models)} artifact groups for FastEmbed "
        + f"{manifest.fastembed_version}; {len(inventory)} combined release assets."
    )
    print(message)


@contextmanager
def _private_command_workspace(
    *, prefix: str, root: Path | None = None
) -> Iterator[Path]:
    """Create task-private command state and retain it at cleanup boundaries."""
    workspace = Path(tempfile.mkdtemp(prefix=prefix, dir=root))
    try:
        yield workspace
    finally:
        # Recursive pathname cleanup can delete a foreign replacement after a
        # top-level swap. There is no portable conditional tree deletion, so
        # retain the entry for explicit operator reconciliation.
        retained = True
        try:
            workspace.lstat()
        except FileNotFoundError:
            retained = False
        except OSError:
            pass
        if retained:
            print(
                f"warning: preserved model-cache command workspace {workspace}; "
                + "safe identity-bound recursive deletion is unavailable",
                file=sys.stderr,
            )


def command_sync(args: argparse.Namespace) -> None:
    manifest = load_manifest(args.manifest)
    if args.upload:
        raise CacheError(
            "upload is a separate reviewed-asset command; sync never publishes"
        )
    if not args.prepare:
        selected = (
            _select_models(manifest, args.model, None)
            if args.model
            else list(manifest.models.values())
        )
        if not args.discover_cache:
            raise CacheError(
                "audit requires at least one explicit absolute --discover-cache root"
            )
        roots = [
            _explicit_nonroot_directory(item, "audit", must_exist=True)
            for item in args.discover_cache
        ]
        if len(roots) != len(set(roots)):
            raise CacheError("audit cache roots must be unique after canonicalization")
        print("FastEmbed cache audit (read-only)")
        with _private_command_workspace(prefix="model-cache-audit-") as staging_root:
            for model in selected:
                if not model.upstream_revision or set(
                    model.upstream_file_sha256
                ) != set(model.required_files):
                    raise CacheError(
                        f"{model.key} lacks exact revision/upstream byte evidence for cache audit"
                    )
                candidates = [
                    root
                    for root in roots
                    if (root / model.fastembed_cache_dir).exists()
                    or (root / model.fastembed_cache_dir).is_symlink()
                ]
                if not candidates:
                    raise CacheError(f"{model.key} is not cached in any requested root")
                if len(candidates) != 1:
                    raise CacheError(
                        f"{model.key} is cached in multiple requested roots; audit is ambiguous"
                    )
                with snapshot_cache_artifact(
                    candidates[0], model, staging_root / model.key
                ):
                    pass
                print(f"  {model.key}: verified at {candidates[0]}")
        return
    selected = _select_models(manifest, args.model, None)
    for model in selected:
        if model.status not in PREPARABLE_STATUSES:
            raise CacheError(
                f"{model.key} status {model.status} is not preparable; adopt reviewed provenance first"
            )
        if not model.upstream_revision or set(model.upstream_file_sha256) != set(
            model.required_files
        ):
            raise CacheError(
                f"{model.key} lacks complete upstream byte evidence and is not preparable"
            )
        _require_adopted_current_provenance(model, "preparation")
        _require_model_licenses(model, "preparation")
    if args.cache_source is None:
        raise CacheError("prepare requires one explicit absolute non-root cache source")
    cache_source = _explicit_nonroot_directory(
        args.cache_source, "prepare", must_exist=True
    )
    dist = manifest.root / "dist"
    if dist.exists() and (dist.is_symlink() or not dist.is_dir()):
        raise CacheError(f"dist is not a regular directory: {dist}")

    prepared: list[tuple[ModelRecord, Path, int, str, Mapping[str, str]]] = []
    with _private_command_workspace(
        prefix=".model-cache-prepare-", root=manifest.root
    ) as workspace:
        _require_secure_model_install_primitives()
        workspace_fd = _open_verified_model_directory_path(
            workspace, "private preparation workspace"
        )
        snapshots_fd = archives_fd = validated_fd = -1
        try:
            snapshots_fd = _create_model_directory_at(
                workspace_fd, "snapshots", "snapshot collection"
            )
            archives_fd = _create_model_directory_at(
                workspace_fd, "archives", "archive collection"
            )
            validated_fd = _create_model_directory_at(
                workspace_fd, "validated", "validation collection"
            )
            for model in selected:
                snapshot_root = workspace / "snapshots" / model.key
                snapshot_model_fd = _create_model_directory_at(
                    snapshots_fd, model.key, "model snapshot parent"
                )
                try:
                    with snapshot_cache_artifact(
                        cache_source,
                        model,
                        snapshot_root,
                        staging_parent_fd=snapshot_model_fd,
                    ) as snapshot:
                        archive_name = f"{model.key}.tar.gz"
                        archive = workspace / "archives" / archive_name
                        size, digest = build_deterministic_archive(
                            snapshot,
                            archive,
                            destination_dir_fd=archives_fd,
                        )
                        file_digests = {
                            item.relative_path: item.sha256 for item in snapshot.files
                        }
                        validated_model = replace(
                            model,
                            status="prepared",
                            file_sha256=file_digests,
                            archive_size_bytes=size,
                            sha256=digest,
                        )
                        validation_root = workspace / "validated" / model.key
                        validation_model_fd = _create_model_directory_at(
                            validated_fd, model.key, "model validation parent"
                        )
                        try:
                            validation_artifact_fd = _create_model_directory_at(
                                validation_model_fd,
                                model.fastembed_cache_dir,
                                "validated model artifact",
                            )
                            try:
                                with immutable_file_snapshot_at(
                                    archives_fd,
                                    archive_name,
                                    max_bytes=MAX_MODEL_ARCHIVE_BYTES,
                                    size_purpose="prepared model archive",
                                ) as (
                                    archive_snapshot,
                                    validated_size,
                                    validated_digest,
                                ):
                                    if (
                                        validated_size != size
                                        or validated_digest != digest
                                    ):
                                        raise CacheError(
                                            "prepared archive changed before validation for "
                                            + model.key
                                        )
                                    extract_verified_model_archive(
                                        archive_snapshot,
                                        validated_model,
                                        validation_root,
                                        staging_dir_fd=validation_model_fd,
                                        artifact_dir_fd=validation_artifact_fd,
                                    )
                            finally:
                                os.close(validation_artifact_fd)
                        finally:
                            os.close(validation_model_fd)
                        prepared.append((model, archive, size, digest, file_digests))
                finally:
                    os.close(snapshot_model_fd)
        finally:
            for descriptor in (validated_fd, archives_fd, snapshots_fd, workspace_fd):
                if descriptor >= 0:
                    os.close(descriptor)

        collisions = [
            dist / item[1].name for item in prepared if (dist / item[1].name).exists()
        ]
        if collisions:
            raise CacheError(
                f"refusing to clobber existing reviewed archive: {collisions[0]}"
            )
        dist.mkdir(mode=0o755, exist_ok=True)
        installed: list[Path] = []
        try:
            for _, archive, size, digest, _ in prepared:
                destination = dist / archive.name
                _publish_archive_noreplace(
                    archive,
                    destination,
                    expected_size=size,
                    expected_sha256=digest,
                )
                installed.append(destination)
            updates: list[FieldUpdate] = []
            for model, _, size, digest, file_digests in prepared:
                updates.extend(
                    (
                        (model.key, "archive_size_bytes", size),
                        (model.key, "sha256", digest),
                        (model.key, "file_sha256", file_digests),
                        (model.key, "status", "prepared"),
                    )
                )
            atomic_manifest_update(manifest, updates)
        except (ManifestDurabilityUnknown, PlatformFileDurabilityUnknown):
            raise
        except BaseException:
            for destination in installed:
                print(
                    f"warning: preserved prepared archive {destination}; "
                    + "safe identity-bound rollback is unavailable",
                    file=sys.stderr,
                )
            raise
    for model, _, size, digest, _ in prepared:
        print(f"prepared {model.key}.tar.gz ({size} bytes, sha256:{digest})")


def _model_directory_flags() -> int:
    return (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )


def _require_secure_model_install_primitives() -> None:
    if _WINDOWS or not (sys.platform.startswith("linux") or sys.platform == "darwin"):
        raise CacheError(
            "this platform lacks secure descriptor-anchored model installation"
        )
    if (
        getattr(os, "O_DIRECTORY", 0) == 0
        or getattr(os, "O_NOFOLLOW", 0) == 0
        or any(
            function not in os.supports_dir_fd
            for function in (os.open, os.mkdir, os.stat)
        )
    ):
        raise CacheError("this platform lacks descriptor-anchored no-follow operations")


def _model_entry_name(value: str, field: str) -> str:
    if (
        not value
        or value in {".", ".."}
        or os.path.isabs(value)
        or "/" in value
        or "\\" in value
    ):
        raise CacheError(f"{field} must be one relative path component")
    return value


def _open_or_create_model_directory_at(
    parent_fd: int, name: str, *, mode: int, context: str
) -> int:
    name = _model_entry_name(name, context)
    created = False
    try:
        os.mkdir(name, mode=mode, dir_fd=parent_fd)
        created = True
    except FileExistsError:
        pass
    try:
        descriptor = os.open(name, _model_directory_flags(), dir_fd=parent_fd)
    except OSError as error:
        raise CacheError(
            f"{context} is a symlink or is not a directory: {name}"
        ) from error
    if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
        os.close(descriptor)
        raise CacheError(f"{context} is not a directory: {name}")
    if created:
        try:
            os.fsync(descriptor)
            os.fsync(parent_fd)
        except BaseException:
            os.close(descriptor)
            raise
    return descriptor


@contextmanager
def _secure_model_cache_root(cache_root: Path) -> Iterator[int]:
    try:
        current_fd = os.open(cache_root.anchor, _model_directory_flags())
    except OSError as error:
        raise CacheError("could not open model cache filesystem anchor") from error
    try:
        for part in cache_root.parts[1:]:
            next_fd = _open_or_create_model_directory_at(
                current_fd, part, mode=0o755, context="model cache directory"
            )
            os.close(current_fd)
            current_fd = next_fd
        yield current_fd
    finally:
        os.close(current_fd)


@contextmanager
def _download_cache_root(
    cache_root: Path, publication: DownloadPublicationState
) -> Iterator[int]:
    """Translate cache-root exit failures after a model publication commit."""
    try:
        with _secure_model_cache_root(cache_root) as cache_fd:
            yield cache_fd
    except PlatformFileDurabilityUnknown:
        raise
    except Exception as error:
        if (
            publication.rename is not None
            and publication.rename.renamed
            and publication.destination is not None
        ):
            raise PlatformFileDurabilityUnknown(publication.destination) from error
        raise


def _path_matches_directory_fd(path: Path, descriptor: int) -> bool:
    try:
        path_state = path.lstat()
    except FileNotFoundError:
        return False
    descriptor_state = os.fstat(descriptor)
    return (
        stat.S_ISDIR(path_state.st_mode)
        and stat.S_ISDIR(descriptor_state.st_mode)
        and os.path.samestat(path_state, descriptor_state)
    )


def _remove_owned_model_directory_at(
    parent_fd: int, name: str, identity: tuple[int, int]
) -> bool:
    """Inspect one held tree but preserve it when conditional deletion is unavailable."""
    try:
        descriptor = os.open(name, _model_directory_flags(), dir_fd=parent_fd)
    except FileNotFoundError:
        return True
    except OSError:
        return False
    try:
        state = os.fstat(descriptor)
        if not stat.S_ISDIR(state.st_mode) or (state.st_dev, state.st_ino) != identity:
            return False
        # No portable removal can be conditioned on the held identity. Since
        # every reachable leaf and directory must therefore be retained, do not
        # recursively inventory an attacker-controlled recovery tree.
        return False
    finally:
        os.close(descriptor)


def _clear_owned_model_directory_fd(directory_fd: int) -> bool:
    """Preserve a held recovery tree without traversing attacker-controlled entries."""
    _ = directory_fd
    return False


@contextmanager
def _private_model_staging(parent_fd: int, prefix: str) -> Iterator[tuple[str, int]]:
    name = ""
    for _ in range(128):
        candidate = prefix + secrets.token_hex(16)
        try:
            os.mkdir(candidate, mode=0o700, dir_fd=parent_fd)
        except FileExistsError:
            continue
        name = candidate
        break
    if not name:
        raise CacheError("could not allocate private model staging")
    try:
        descriptor = os.open(name, _model_directory_flags(), dir_fd=parent_fd)
    except BaseException:
        print(
            f"warning: preserved ambiguous private model staging entry {name}",
            file=sys.stderr,
        )
        raise
    identity = (os.fstat(descriptor).st_dev, os.fstat(descriptor).st_ino)
    try:
        yield name, descriptor
    finally:
        os.close(descriptor)
        if not _remove_owned_model_directory_at(parent_fd, name, identity):
            print(
                f"warning: preserved private model staging entry {name}; "
                + "safe identity-bound deletion is unavailable",
                file=sys.stderr,
            )


def _download_with_gh(
    manifest: Manifest,
    model: ModelRecord,
    directory: Path,
    *,
    directory_fd: int | None = None,
) -> Path:
    if model.status == "carry-forward":
        if not model.source_release_tag:
            raise CacheError(
                f"{model.key} carry-forward lacks a historical source_release_tag"
            )
        tag = model.source_release_tag
    else:
        tag = manifest.release_tag
    if model.archive_size_bytes <= 0:
        raise CacheError(f"{model.key} lacks a positive expected archive size")
    if model.archive_size_bytes > MAX_MODEL_ARCHIVE_BYTES:
        raise CacheError("model archive bytes exceed the safe size limit")
    archive_name = _model_entry_name(f"{model.key}.tar.gz", "model download archive")
    command = [
        "gh",
        "release",
        "download",
        tag,
        "-R",
        manifest.repository,
        "-p",
        archive_name,
        "--output",
        "-",
    ]
    owned_directory_fd = directory_fd is None
    active_directory_fd = directory_fd
    if active_directory_fd is None:
        active_directory_fd = _open_verified_model_directory_path(
            directory, "model download staging"
        )
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    try:
        try:
            archive_fd = os.open(archive_name, flags, 0o600, dir_fd=active_directory_fd)
        except FileExistsError as error:
            raise CacheError(
                f"download archive already exists; refusing overwrite: {archive_name}"
            ) from error
        except OSError as error:
            raise CacheError(
                f"could not create exclusive download archive: {archive_name}"
            ) from error
        process: subprocess.Popen[bytes] | None = None
        try:
            try:
                process = subprocess.Popen(command, stdout=subprocess.PIPE)
            except FileNotFoundError as error:
                raise CacheError(
                    "gh is required to download verified release assets"
                ) from error
            if process.stdout is None:
                raise CacheError(
                    "release download did not provide an asset byte stream"
                )
            size = 0
            while True:
                remaining = model.archive_size_bytes - size
                chunk = process.stdout.read(min(HASH_CHUNK_BYTES, remaining + 1))
                if not chunk:
                    break
                if len(chunk) > remaining:
                    raise CacheError(
                        f"release download exceeds the declared size for {model.key}"
                    )
                offset = 0
                while offset < len(chunk):
                    written = os.write(archive_fd, chunk[offset:])
                    if written <= 0:
                        raise OSError("short write while acquiring release archive")
                    offset += written
                size += len(chunk)
            return_code = process.wait()
            if return_code != 0:
                raise CacheError(f"release download failed for {model.key}")
            if size != model.archive_size_bytes:
                raise CacheError(
                    f"release download size mismatch for {model.key}: "
                    + f"expected {model.archive_size_bytes}, received {size}"
                )
            held_state = os.fstat(archive_fd)
            try:
                named_state = os.stat(
                    archive_name,
                    dir_fd=active_directory_fd,
                    follow_symlinks=False,
                )
            except OSError as error:
                raise CacheError(
                    f"release download changed while acquired: {archive_name}"
                ) from error
            if (
                not stat.S_ISREG(held_state.st_mode)
                or held_state.st_nlink != 1
                or not stat.S_ISREG(named_state.st_mode)
                or not os.path.samestat(held_state, named_state)
            ):
                raise CacheError(
                    f"release download changed while acquired: {archive_name}"
                )
        except BaseException:
            if process is not None and process.returncode is None:
                try:
                    process.kill()
                except OSError:
                    pass
                process.wait()
            raise
        finally:
            if process is not None and process.stdout is not None:
                process.stdout.close()
            os.close(archive_fd)
    finally:
        if owned_directory_fd:
            os.close(active_directory_fd)
    return directory / archive_name


def atomic_rename_noreplace(
    source: Path,
    destination: Path,
    *,
    source_dir_fd: int | None = None,
    destination_dir_fd: int | None = None,
    source_identity: tuple[int, int] | None = None,
    publication_state: RenamePublicationState | None = None,
) -> None:
    """Atomically install a staged filesystem entry without replacing a destination."""
    if _WINDOWS:
        if source_dir_fd is not None or destination_dir_fd is not None:
            raise CacheError(
                "native Windows lacks descriptor-relative model installation"
            )
        source.rename(destination)
        if publication_state is not None:
            publication_state.renamed = True
        return
    if (source_dir_fd is None) != (destination_dir_fd is None):
        raise CacheError("model publication requires both verified parent descriptors")
    source_parent = AT_FDCWD if source_dir_fd is None else source_dir_fd
    destination_parent = AT_FDCWD if destination_dir_fd is None else destination_dir_fd
    source_value = os.fspath(source)
    destination_value = os.fspath(destination)
    if source_dir_fd is not None:
        source_value = _model_entry_name(source_value, "model publication source")
        destination_value = _model_entry_name(
            destination_value, "model publication destination"
        )
        if source_identity is not None:
            source_state = os.stat(
                source_value, dir_fd=source_dir_fd, follow_symlinks=False
            )
            if (
                not stat.S_ISDIR(source_state.st_mode)
                or (source_state.st_dev, source_state.st_ino) != source_identity
            ):
                raise CacheError("model payload changed before publication")
    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform.startswith("linux"):
        raw_function = getattr(libc, "renameat2", None)
        if raw_function is None:
            raise CacheError(
                "this platform lacks atomic no-clobber directory installation"
            )
        renameat2 = cast(Callable[[int, bytes, int, bytes, int], int], raw_function)
        result = renameat2(
            source_parent,
            os.fsencode(source_value),
            destination_parent,
            os.fsencode(destination_value),
            RENAME_NOREPLACE,
        )
    elif sys.platform == "darwin":
        raw_function = getattr(libc, "renameatx_np", None)
        if raw_function is None:
            raise CacheError(
                "this platform lacks atomic no-clobber directory installation"
            )
        renameatx_np = cast(Callable[[int, bytes, int, bytes, int], int], raw_function)
        result = renameatx_np(
            source_parent,
            os.fsencode(source_value),
            destination_parent,
            os.fsencode(destination_value),
            RENAME_EXCL,
        )
    else:
        raise CacheError("this platform lacks atomic no-clobber directory installation")
    if result == 0:
        if publication_state is not None:
            publication_state.renamed = True
        if source_identity is not None and destination_dir_fd is not None:
            installed_state = os.stat(
                destination_value,
                dir_fd=destination_dir_fd,
                follow_symlinks=False,
            )
            if (
                not stat.S_ISDIR(installed_state.st_mode)
                or (installed_state.st_dev, installed_state.st_ino) != source_identity
            ):
                raise CacheError("model payload changed during publication")
        return
    error_number = ctypes.get_errno()
    if error_number in {errno.EEXIST, errno.ENOTEMPTY}:
        raise FileExistsError(error_number, os.strerror(error_number), destination)
    raise OSError(error_number, os.strerror(error_number), destination)


def _sync_published_model_tree(
    directory_fd: int,
    model: ModelRecord,
    evidence: Mapping[str, ExtractedModelFileEvidence],
) -> None:
    """Revalidate exact published bytes while flushing every tree commit point."""
    _validate_model_output_tree(directory_fd, model, evidence, sync=True)


def command_download(args: argparse.Namespace) -> None:
    manifest = load_manifest(args.manifest)
    if args.list:
        for model in manifest.models.values():
            print(f"{model.key}\t{','.join(model.types)}\t{model.status}")
        return
    selected = (
        list(manifest.models.values())
        if args.selection == "all"
        else _select_models(manifest, args.model, args.model_type)
    )
    cache_value = os.environ.get("FASTEMBED_CACHE_DIR") or os.environ.get(
        "FASTEMBED_CACHE_PATH"
    )
    if not cache_value:
        raise CacheError(
            "FASTEMBED_CACHE_DIR must be one explicit absolute cache destination"
        )
    cache_root = _explicit_nonroot_directory(cache_value, "download", must_exist=False)
    destinations: list[tuple[ModelRecord, Path]] = []
    for model in selected:
        if model.status not in INSTALLABLE_STATUSES or not model.sha256:
            raise CacheError(
                f"{model.key} has no verified SHA-256 and is not installable"
            )
        if (
            not model.upstream_revision
            or set(model.file_sha256) != set(model.required_files)
            or model.file_sha256 != model.upstream_file_sha256
        ):
            raise CacheError(f"{model.key} has incomplete exact provenance metadata")
        destination = cache_root / model.fastembed_cache_dir
        if destination.exists() or destination.is_symlink():
            raise CacheError(
                f"cache destination already exists; refusing overwrite: {destination}"
            )
        destinations.append((model, destination))

    _require_secure_model_install_primitives()
    command_publication = DownloadPublicationState()
    with _download_cache_root(cache_root, command_publication) as cache_fd:
        if not _path_matches_directory_fd(cache_root, cache_fd):
            raise CacheError("model cache root changed while it was opened")
        for model, destination in destinations:
            destination_name = _model_entry_name(
                model.fastembed_cache_dir, "model cache destination"
            )
            try:
                os.stat(destination_name, dir_fd=cache_fd, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                raise CacheError(
                    "cache destination already exists; refusing overwrite: "
                    + str(destination)
                )

        for model, destination in destinations:
            archive_name = f"{model.key}.tar.gz"
            publication_state = RenamePublicationState()
            command_publication.rename = publication_state
            command_publication.destination = destination
            try:
                with _private_model_staging(cache_fd, f".download-{model.key}-") as (
                    staging_name,
                    staging_fd,
                ):
                    staging_path = cache_root / staging_name
                    _download_with_gh(
                        manifest,
                        model,
                        staging_path,
                        directory_fd=staging_fd,
                    )
                    if not _path_matches_directory_fd(cache_root, cache_fd):
                        raise CacheError("model cache root changed during download")
                    with immutable_file_snapshot_at(
                        staging_fd,
                        archive_name,
                        max_bytes=MAX_MODEL_ARCHIVE_BYTES,
                        size_purpose="model archive",
                    ) as (archive_file, size, digest):
                        if size != model.archive_size_bytes or digest != model.sha256:
                            raise CacheError(
                                f"archive checksum mismatch for {model.key}; "
                                + "cache was not modified"
                            )
                        payload_fd = _open_or_create_model_directory_at(
                            staging_fd,
                            "payload",
                            mode=0o700,
                            context="model extraction staging",
                        )
                        try:
                            artifact_fd = _open_or_create_model_directory_at(
                                payload_fd,
                                model.fastembed_cache_dir,
                                mode=0o700,
                                context="model artifact",
                            )
                            try:
                                extracted_evidence = extract_verified_model_archive(
                                    archive_file,
                                    model,
                                    Path("payload"),
                                    staging_dir_fd=payload_fd,
                                    artifact_dir_fd=artifact_fd,
                                )
                                artifact_state = os.fstat(artifact_fd)
                                artifact_identity = (
                                    artifact_state.st_dev,
                                    artifact_state.st_ino,
                                )
                                if not _path_matches_directory_fd(cache_root, cache_fd):
                                    raise CacheError(
                                        "model cache root changed before publication"
                                    )
                                _validate_model_output_tree(
                                    artifact_fd,
                                    model,
                                    extracted_evidence,
                                    sync=False,
                                )
                                try:
                                    atomic_rename_noreplace(
                                        Path(model.fastembed_cache_dir),
                                        Path(model.fastembed_cache_dir),
                                        source_dir_fd=payload_fd,
                                        destination_dir_fd=cache_fd,
                                        source_identity=artifact_identity,
                                        publication_state=publication_state,
                                    )
                                except FileExistsError as error:
                                    raise CacheError(
                                        "cache destination appeared during installation; "
                                        + f"already exists: {destination}"
                                    ) from error
                                installed_state = os.stat(
                                    model.fastembed_cache_dir,
                                    dir_fd=cache_fd,
                                    follow_symlinks=False,
                                )
                                if (
                                    not stat.S_ISDIR(installed_state.st_mode)
                                    or (
                                        installed_state.st_dev,
                                        installed_state.st_ino,
                                    )
                                    != artifact_identity
                                ):
                                    raise CacheError(
                                        "installed model cache identity changed "
                                        + "during publication"
                                    )
                                if not _path_matches_directory_fd(cache_root, cache_fd):
                                    raise CacheError(
                                        "model cache root changed after publication"
                                    )
                                _sync_published_model_tree(
                                    artifact_fd,
                                    model,
                                    extracted_evidence,
                                )
                                os.fsync(payload_fd)
                                os.fsync(cache_fd)
                            finally:
                                os.close(artifact_fd)
                        finally:
                            os.close(payload_fd)
            except PlatformFileDurabilityUnknown:
                raise
            except Exception as error:
                if publication_state.renamed:
                    raise PlatformFileDurabilityUnknown(destination) from error
                raise
            print(f"installed {model.key} in {destination}")


def _parse_remote_model(payload: bytes, model: ModelRecord) -> RemoteModel:
    try:
        data = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CacheError(f"invalid upstream response for {model.key}") from error
    if not isinstance(data, dict):
        raise CacheError(f"invalid upstream response for {model.key}")
    revision = _string(data.get("sha"), "upstream.sha")
    modified = _string(data.get("lastModified"), "upstream.lastModified")
    _validate_revision(revision, f"{model.key}.upstream.sha", allow_empty=False)
    _validate_timestamp(
        modified, f"{model.key}.upstream.lastModified", allow_empty=False
    )
    siblings = data.get("siblings", [])
    if not isinstance(siblings, list):
        raise CacheError(f"invalid upstream siblings for {model.key}")
    lfs: dict[str, str] = {}
    file_sha256: dict[str, str] = {}
    git_blob_oid: dict[str, str] = {}
    seen: set[str] = set()
    for sibling in cast(list[object], siblings):
        if not isinstance(sibling, dict):
            raise CacheError(f"invalid upstream sibling for {model.key}")
        name = sibling.get("rfilename")
        if not isinstance(name, str) or name not in model.required_files:
            continue
        if name in seen:
            raise CacheError(f"duplicate upstream sibling for {model.key}: {name}")
        seen.add(name)
        lfs_data = sibling.get("lfs")
        if isinstance(lfs_data, dict) and "sha256" in lfs_data:
            digest = _string(
                lfs_data.get("sha256"), f"upstream.siblings.{name}.lfs.sha256"
            )
            _validate_sha256(
                digest, f"upstream.siblings.{name}.lfs.sha256", allow_empty=False
            )
            lfs[name] = digest
            file_sha256[name] = digest
            continue
        object_id = _string(sibling.get("blobId"), f"upstream.siblings.{name}.blobId")
        _validate_git_blob_oid(object_id, f"upstream.siblings.{name}.blobId")
        git_blob_oid[name] = object_id
    missing = sorted(set(model.required_files) - seen)
    if missing:
        raise CacheError(
            f"upstream response omits required file evidence for {model.key}: {missing[0]}"
        )
    return RemoteModel(revision, modified, lfs, file_sha256, git_blob_oid)


def _validate_hf_https_url(url: str) -> urllib.parse.SplitResult:
    try:
        parsed = urllib.parse.urlsplit(url)
    except ValueError as error:
        raise CacheError("invalid Hugging Face HTTPS URL") from error
    if (
        parsed.scheme != "https"
        or parsed.netloc != HF_HOST
        or not parsed.path.startswith("/")
        or parsed.fragment
    ):
        raise CacheError("Hugging Face byte fetch must remain on exact HTTPS host")
    return parsed


def _read_strict_hf_https(url: str, *, limit: int) -> bytes:
    current = url
    for redirect_count in range(MAX_HF_REDIRECTS + 1):
        parsed = _validate_hf_https_url(current)
        target = urllib.parse.urlunsplit(("", "", parsed.path, parsed.query, ""))
        connection = http.client.HTTPSConnection(HF_HOST, timeout=30)
        try:
            connection.request(
                "GET", target, headers={"Accept": "application/octet-stream"}
            )
            response = connection.getresponse()
            if response.status in {301, 302, 303, 307, 308}:
                location = response.getheader("Location")
                if not location or redirect_count == MAX_HF_REDIRECTS:
                    raise CacheError("Hugging Face byte fetch exceeded safe redirects")
                current = urllib.parse.urljoin(current, location)
                _validate_hf_https_url(current)
                continue
            if response.status != 200:
                raise CacheError(
                    f"Hugging Face byte fetch returned HTTP {response.status}"
                )
            length_header = response.getheader("Content-Length")
            if length_header is not None:
                try:
                    declared_length = int(length_header)
                except ValueError as error:
                    raise CacheError("invalid Hugging Face Content-Length") from error
                if declared_length < 0 or declared_length > limit:
                    raise CacheError(
                        "Hugging Face response exceeds the safe size limit"
                    )
            content = bytearray()
            while chunk := response.read(
                min(HASH_CHUNK_BYTES, limit + 1 - len(content))
            ):
                content.extend(chunk)
                if len(content) > limit:
                    raise CacheError(
                        "Hugging Face response exceeds the safe size limit"
                    )
            return bytes(content)
        except (OSError, http.client.HTTPException) as error:
            raise CacheError("Hugging Face byte fetch failed") from error
        finally:
            connection.close()
    raise CacheError("Hugging Face byte fetch exceeded safe redirects")


def _fetch_hf_git_blob(
    model: ModelRecord, revision: str, relative: str, expected_oid: str
) -> bytes:
    encoded_repo = urllib.parse.quote(model.huggingface_repo, safe="/")
    encoded_relative = urllib.parse.quote(relative, safe="/")
    url = f"https://{HF_HOST}/{encoded_repo}/raw/{revision}/{encoded_relative}"
    content = _read_strict_hf_https(url, limit=MAX_HF_GIT_BLOB_BYTES)
    git_digest = hashlib.sha1(
        f"blob {len(content)}\0".encode("ascii") + content,
        usedforsecurity=False,
    ).hexdigest()
    if git_digest != expected_oid:
        raise CacheError(f"Git blob OID mismatch for {model.key}:{relative}")
    return content


def _query_remote(model: ModelRecord) -> RemoteModel:
    encoded = urllib.parse.quote(model.huggingface_repo, safe="/")
    url = f"https://{HF_HOST}/api/models/{encoded}?blobs=true"
    payload = _read_strict_hf_https(url, limit=MAX_HF_API_BYTES)
    parsed = _parse_remote_model(payload, model)
    file_sha256 = dict(parsed.file_sha256)
    for relative, object_id in parsed.git_blob_oid.items():
        content = _fetch_hf_git_blob(model, parsed.revision, relative, object_id)
        file_sha256[relative] = hashlib.sha256(content).hexdigest()
    if set(file_sha256) != set(model.required_files):
        raise CacheError(f"incomplete upstream byte evidence for {model.key}")
    return RemoteModel(
        parsed.revision,
        parsed.last_modified,
        parsed.lfs_sha256,
        file_sha256,
        parsed.git_blob_oid,
    )


def command_check_updates(args: argparse.Namespace) -> None:
    manifest = load_manifest(args.manifest)
    selected = (
        _select_models(manifest, args.model, None)
        if args.model
        else list(manifest.models.values())
    )
    if args.adopt_current:
        if len(selected) != 1:
            raise CacheError("adopt-current requires exactly one explicit --model")
        model = selected[0]
        if model.status == "provenance-required":
            raise CacheError(
                f"{model.key} historical provenance cannot be replaced by current HEAD"
            )
        if not model.current_remote_revision:
            raise CacheError(
                f"{model.key} has no validated current remote candidate to adopt"
            )
        if set(model.current_remote_file_sha256) != set(model.required_files):
            raise CacheError(
                f"{model.key} candidate has incomplete upstream byte evidence"
            )
        if model.status in ARCHIVE_READY_STATUSES:
            raise CacheError(
                f"{model.key} is still archive-ready; run --apply to invalidate a changed candidate first"
            )
        adopted_status = (
            "refresh-required"
            if model.status == "revision-review-required"
            else model.status
        )
        adopt_updates: list[FieldUpdate] = [
            (model.key, "upstream_revision", model.current_remote_revision),
            (
                model.key,
                "upstream_last_modified",
                model.current_remote_last_modified,
            ),
            (
                model.key,
                "upstream_lfs_sha256",
                model.current_remote_lfs_sha256,
            ),
            (
                model.key,
                "upstream_file_sha256",
                model.current_remote_file_sha256,
            ),
            (
                model.key,
                "upstream_git_blob_oid",
                model.current_remote_git_blob_oid,
            ),
            (model.key, "status", adopted_status),
        ]
        if model.source_release_tag:
            adopt_updates.append((model.key, "source_release_tag", ""))
        atomic_manifest_update(manifest, adopt_updates)
        print(
            f"adopted reviewed upstream candidate for {model.key}; status={adopted_status}"
        )
        return

    remotes: dict[str, RemoteModel] = {}
    for model in selected:
        remotes[model.key] = _query_remote(model)
    if not args.apply:
        for model in selected:
            remote = remotes[model.key]
            baseline = model.upstream_revision or "unresolved historical baseline"
            print(f"{model.key}: baseline={baseline} current={remote.revision}")
        return
    updates: list[FieldUpdate] = []
    for model in selected:
        remote = remotes[model.key]
        updates.extend(
            (
                (model.key, "current_remote_revision", remote.revision),
                (model.key, "current_remote_last_modified", remote.last_modified),
                (model.key, "current_remote_lfs_sha256", remote.lfs_sha256),
                (model.key, "current_remote_file_sha256", remote.file_sha256),
                (model.key, "current_remote_git_blob_oid", remote.git_blob_oid),
            )
        )
        if model.status == "provenance-required":
            continue
        provenance_changed = bool(model.upstream_revision) and (
            model.upstream_revision != remote.revision
            or model.upstream_lfs_sha256 != remote.lfs_sha256
            or model.upstream_file_sha256 != remote.file_sha256
            or model.upstream_git_blob_oid != remote.git_blob_oid
        )
        if provenance_changed and model.status in ARCHIVE_READY_STATUSES:
            updates.extend(
                (
                    (model.key, "status", "revision-review-required"),
                    (model.key, "archive_size_bytes", 0),
                    (model.key, "sha256", ""),
                    (model.key, "file_sha256", {}),
                )
            )
    if args.model is None:
        updates.append(
            (
                "meta",
                "last_upstream_check",
                datetime.now(timezone.utc).date().isoformat(),
            )
        )
    atomic_manifest_update(manifest, updates)
    print("validated upstream metadata recorded in one atomic manifest transaction")


def _canonical_remote(value: str) -> str:
    match = re.fullmatch(r"git@github\.com:([^/]+/[^/]+?)(?:\.git)?", value.strip())
    if not match:
        match = re.fullmatch(
            r"https://github\.com/([^/]+/[^/]+?)(?:\.git)?/?", value.strip()
        )
    if not match:
        raise CacheError(
            f"git origin is not a canonical GitHub repository URL: {value!r}"
        )
    repository = match.group(1)
    _validate_repo_id(repository, "git origin repository")
    return repository


def _git_capture(
    manifest: Manifest,
    arguments: Sequence[str],
    *,
    failure_message: str | None = None,
) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(manifest.root), *arguments],
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as error:
        message = failure_message or f"git preflight failed: {' '.join(arguments)}"
        raise CacheError(message) from error
    return result.stdout


def _git_capture_bytes(
    manifest: Manifest,
    arguments: Sequence[str],
    *,
    failure_message: str | None = None,
) -> bytes:
    try:
        result = subprocess.run(
            ["git", "-C", str(manifest.root), *arguments],
            check=True,
            capture_output=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as error:
        message = failure_message or f"git preflight failed: {' '.join(arguments)}"
        raise CacheError(message) from error
    return result.stdout


def _canonical_upload_manifest_path() -> Path:
    return Path(__file__).resolve().parent.parent / "models-manifest.toml"


def _release_manifest_bytes(path: Path, label: str) -> bytes:
    with tempfile.TemporaryFile() as temporary:
        _copy_regular_file(
            path,
            temporary,
            max_bytes=MAX_RELEASE_MANIFEST_BYTES,
            size_purpose=label,
        )
        temporary.seek(0)
        return temporary.read()


def _repository_state_preflight(manifest: Manifest) -> ReleaseTrustSnapshot:
    canonical_manifest = _canonical_upload_manifest_path()
    if (
        manifest.path != canonical_manifest
        or manifest.root != canonical_manifest.parent
    ):
        raise CacheError("upload requires the canonical models manifest")

    origin = _git_capture(manifest, ("remote", "get-url", "origin"))
    if _canonical_remote(origin) != manifest.repository:
        raise CacheError("configured repository does not exactly match git origin")

    version_path = manifest.root / "VERSION"
    try:
        version = _read_small_regular_file(version_path).decode("utf-8").strip()
    except UnicodeDecodeError as error:
        raise CacheError("VERSION is not valid UTF-8") from error
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        raise CacheError("VERSION must contain one semantic version")
    if manifest.release_tag != f"v{version}":
        raise CacheError("VERSION does not match the configured release tag")

    critical_files = {
        "VERSION",
        "LICENSE",
        "models-manifest.toml",
        "scripts/check-updates.sh",
        "scripts/download-model.sh",
        "scripts/install-ort-runtime.py",
        "scripts/manifest.sh",
        "scripts/model_cache.py",
        "scripts/platform_file.py",
        "scripts/sync-release.sh",
        "scripts/upload-release.sh",
        "scripts/validate-manifest.sh",
        RUNTIME_MANIFEST_RELATIVE.as_posix(),
        "runtime/ort-sys-2.0.0-rc.13/ATTRIBUTION.md",
        "runtime/ort-sys-2.0.0-rc.13/LICENSE",
    }
    for model in manifest.models.values():
        critical_files.add(model.cache_attribution)
        critical_files.add(model.original_attribution)
        for attribution in (model.cache_attribution, model.original_attribution):
            sibling_license = PurePosixPath(attribution).parent / "LICENSE"
            if (manifest.root / sibling_license).is_file():
                critical_files.add(sibling_license.as_posix())
    _git_capture(
        manifest, ("ls-files", "--error-unmatch", "--", *sorted(critical_files))
    )
    status = _git_capture(
        manifest, ("status", "--porcelain=v1", "--untracked-files=all")
    )
    if status:
        raise CacheError("release requires the entire worktree and index to be clean")

    branch_error = "checked-out symbolic branch must be exactly main"
    branch = _git_capture(
        manifest,
        ("symbolic-ref", "--quiet", "--short", "HEAD"),
        failure_message=branch_error,
    ).strip()
    if branch != "main":
        raise CacheError(branch_error)

    head = _git_capture(manifest, ("rev-parse", "HEAD")).strip()
    _validate_revision(head, "git.HEAD", allow_empty=False)
    upstream = _git_capture(
        manifest, ("rev-parse", "--symbolic-full-name", "@{upstream}")
    ).strip()
    if upstream != "refs/remotes/origin/main":
        raise CacheError("git upstream must be exactly refs/remotes/origin/main")

    runtime_path = manifest.root / RUNTIME_MANIFEST_RELATIVE
    model_bytes = _release_manifest_bytes(canonical_manifest, "models manifest")
    runtime_bytes = _release_manifest_bytes(runtime_path, "runtime manifest")
    committed_model_bytes = _git_capture_bytes(
        manifest,
        ("show", f"{head}:models-manifest.toml"),
        failure_message="could not read the exact HEAD models manifest blob",
    )
    committed_runtime_bytes = _git_capture_bytes(
        manifest,
        ("show", f"{head}:{RUNTIME_MANIFEST_RELATIVE.as_posix()}"),
        failure_message="could not read the exact HEAD runtime manifest blob",
    )
    if manifest.raw_bytes != model_bytes:
        raise CacheError(
            "loaded models manifest diverges from the canonical checkout file"
        )
    if model_bytes != committed_model_bytes:
        raise CacheError("canonical models manifest diverges from the exact HEAD blob")
    if runtime_bytes != committed_runtime_bytes:
        raise CacheError("canonical runtime manifest diverges from the exact HEAD blob")
    return ReleaseTrustSnapshot(head, model_bytes, runtime_bytes)


def _assert_release_trust_unchanged(
    manifest: Manifest, expected: ReleaseTrustSnapshot
) -> None:
    current = _repository_state_preflight(manifest)
    if current != expected:
        raise CacheError("release trust state changed during preflight")


def _repository_remote_head_preflight(manifest: Manifest, expected_head: str) -> None:
    remote_ref = "refs/heads/main"
    remote_output = _git_capture(
        manifest, ("ls-remote", "--exit-code", "origin", remote_ref)
    ).strip()
    remote_parts = remote_output.split()
    if len(remote_parts) != 2 or remote_parts[1] != remote_ref:
        raise CacheError("could not resolve the exact pushed upstream commit")
    remote_head = remote_parts[0]
    _validate_revision(remote_head, "git.remote_HEAD", allow_empty=False)
    if remote_head != expected_head:
        raise CacheError("release requires the exact pushed HEAD")


def _reviewed_artifacts(
    manifest: Manifest,
    directory: Path,
    trust: ReleaseTrustSnapshot | None = None,
) -> dict[str, tuple[int, str]]:
    if trust is not None:
        _assert_release_trust_unchanged(manifest, trust)
    canonical = load_manifest(manifest.path, manifest.root, manifest.raw_bytes)
    if canonical != manifest:
        raise CacheError("review manifest diverges from its canonical raw manifest")
    manifest = canonical
    inventory = authoritative_release_inventory(
        manifest,
        runtime_raw_bytes=trust.runtime_manifest_bytes if trust is not None else None,
    )
    expected = {f"{model.key}.tar.gz": model for model in manifest.models.values()}
    for model in expected.values():
        if model.status not in ARCHIVE_READY_STATUSES:
            raise CacheError(
                "complete reviewed artifact set is unavailable: models remain non-release-ready"
            )
        _require_model_licenses(model, "release admission")
        _require_adopted_current_provenance(model, "release admission")
        _validate_evidence_set(
            prefix=f"models.{model.key}.upstream",
            revision=model.upstream_revision,
            required_files=model.required_files,
            file_sha256=model.upstream_file_sha256,
            lfs_sha256=model.upstream_lfs_sha256,
            git_blob_oid=model.upstream_git_blob_oid,
        )
        _validate_evidence_set(
            prefix=f"models.{model.key}.current_remote",
            revision=model.current_remote_revision,
            required_files=model.required_files,
            file_sha256=model.current_remote_file_sha256,
            lfs_sha256=model.current_remote_lfs_sha256,
            git_blob_oid=model.current_remote_git_blob_oid,
        )
        if (
            not model.upstream_revision
            or set(model.upstream_file_sha256) != set(model.required_files)
            or model.file_sha256 != model.upstream_file_sha256
        ):
            raise CacheError(f"{model.key} has incomplete archive byte provenance")
        if model.status == "carry-forward" and not _is_historical_source_release(
            model.source_release_tag, manifest.release_tag
        ):
            raise CacheError(
                f"{model.key} carry-forward lacks a historical source_release_tag "
                + "strictly older than the candidate release"
            )
    expected_count = len(inventory)
    seen: set[str] = set()
    results: dict[str, tuple[int, str]] = {}
    with os.scandir(directory) as entries:
        for entry in entries:
            if len(seen) >= expected_count:
                raise CacheError(
                    "reviewed artifact entry count exceeds the exact release inventory"
                )
            if entry.name in seen:
                raise CacheError(f"duplicate reviewed artifact: {entry.name}")
            if entry.name not in inventory:
                raise CacheError(f"unexpected reviewed artifact: {entry.name}")
            if entry.is_symlink() or not entry.is_file():
                raise CacheError(
                    f"unexpected or special reviewed artifact entry: {entry.name}"
                )
            seen.add(entry.name)
    if len(seen) != expected_count:
        raise CacheError(
            "complete reviewed artifact set is required before GitHub access"
        )
    for name, asset in inventory.items():
        is_model_archive = asset.component == "fastembed-model"
        with immutable_file_snapshot(
            directory / name,
            max_bytes=(
                MAX_MODEL_ARCHIVE_BYTES
                if is_model_archive
                else MAX_RUNTIME_ARCHIVE_BYTES
            ),
            size_purpose="model archive" if is_model_archive else "runtime archive",
        ) as (_, size, digest):
            if (
                asset.expected_size is not None and size != asset.expected_size
            ) or digest != asset.sha256:
                raise CacheError(f"reviewed artifact digest mismatch: {name}")
            results[name] = (size, digest)
    return results


def _gh_release_json(manifest: Manifest) -> dict[str, object]:
    try:
        result = subprocess.run(
            [
                "gh",
                "release",
                "view",
                manifest.release_tag,
                "-R",
                manifest.repository,
                "--json",
                "isDraft,tagName,assets",
            ],
            check=True,
            capture_output=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as error:
        raise CacheError(
            "could not inspect the configured GitHub draft release"
        ) from error
    try:
        data = json.loads(result.stdout)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CacheError("GitHub release inspection returned invalid JSON") from error
    if not isinstance(data, dict):
        raise CacheError("GitHub release inspection returned invalid JSON")
    return cast(dict[str, object], data)


def _repository_remote_tag_preflight(manifest: Manifest, expected_head: str) -> str:
    """Resolve the canonical remote tag, recursively peeling annotated tags."""
    tag_ref = f"refs/tags/{manifest.release_tag}"
    peeled_ref = f"{tag_ref}^{{}}"
    output = _git_capture(
        manifest,
        ("ls-remote", "--exit-code", "origin", tag_ref, peeled_ref),
        failure_message="could not resolve the exact canonical remote release tag",
    )
    resolved: dict[str, str] = {}
    for line in output.splitlines():
        parts = line.split()
        if len(parts) != 2 or parts[1] not in {tag_ref, peeled_ref}:
            raise CacheError("canonical remote release tag response is malformed")
        if parts[1] in resolved:
            raise CacheError("canonical remote release tag response is ambiguous")
        _validate_revision(parts[0], f"git.{parts[1]}", allow_empty=False)
        resolved[parts[1]] = parts[0]
    if tag_ref not in resolved:
        raise CacheError("canonical remote release tag is missing")
    target_sha = resolved.get(peeled_ref, resolved[tag_ref])
    if target_sha != expected_head:
        raise CacheError("canonical remote release tag commit does not match HEAD")
    return target_sha


def _release_preflight(
    manifest: Manifest, trust: ReleaseTrustSnapshot
) -> ReleasePreflight:
    _assert_release_trust_unchanged(manifest, trust)
    _repository_remote_head_preflight(manifest, trust.head_sha)
    target_sha = _repository_remote_tag_preflight(manifest, trust.head_sha)
    release = _gh_release_json(manifest)
    if (
        release.get("tagName") != manifest.release_tag
        or release.get("isDraft") is not True
    ):
        raise CacheError(
            "configured release must exist as the exact verified draft tag"
        )
    return ReleasePreflight(
        head_sha=trust.head_sha, target_sha=target_sha, release=release
    )


def _remote_asset_digests(assets: list[object]) -> dict[str, str]:
    remote: dict[str, str] = {}
    for asset in assets:
        if not isinstance(asset, dict) or not isinstance(asset.get("name"), str):
            raise CacheError("GitHub release assets response is malformed")
        name = cast(str, asset["name"])
        if name in remote:
            raise CacheError(f"duplicate remote release asset: {name}")
        digest = asset.get("digest")
        remote[name] = digest if isinstance(digest, str) else ""
    return remote


def command_upload(args: argparse.Namespace) -> None:
    manifest = load_manifest(args.manifest)
    trust = _repository_state_preflight(manifest)
    directory = _explicit_nonroot_directory(
        args.artifacts_dir, "upload", must_exist=True
    )
    reviewed = _reviewed_artifacts(manifest, directory, trust)
    preflight = _release_preflight(manifest, trust)
    release = preflight.release
    assets = release.get("assets")
    if not isinstance(assets, list):
        raise CacheError("GitHub release assets response is malformed")
    remote = _remote_asset_digests(cast(list[object], assets))
    expected = set(reviewed)
    collisions = expected & set(remote)
    if args.verify_remote:
        if set(remote) != expected:
            raise CacheError(
                "remote release does not contain the complete reviewed artifact set"
            )
        for name, (_, digest) in reviewed.items():
            if remote[name] != f"sha256:{digest}":
                raise CacheError(f"remote release digest mismatch: {name}")
        final_preflight = _release_preflight(manifest, trust)
        if (
            final_preflight.head_sha != preflight.head_sha
            or final_preflight.target_sha != preflight.target_sha
        ):
            raise CacheError("release target commit changed during remote verification")
        final_assets = final_preflight.release.get("assets")
        if not isinstance(final_assets, list):
            raise CacheError("GitHub release assets response is malformed")
        final_remote = _remote_asset_digests(cast(list[object], final_assets))
        if final_remote != remote:
            raise CacheError("release asset set changed during remote verification")
        _assert_release_trust_unchanged(manifest, trust)
        print(
            "remote draft release contains the complete digest-verified reviewed artifact set"
        )
        return
    if collisions:
        raise CacheError(
            f"release asset collision; refusing to clobber: {sorted(collisions)[0]}"
        )
    if args.preflight:
        _assert_release_trust_unchanged(manifest, trust)
        message = (
            "preflight passed; automated multi-asset upload is intentionally disabled because "
            + "GitHub cannot make it atomic. Upload the reviewed set manually, then run "
            + "--verify-remote."
        )
        print(message)
        return
    raise CacheError(
        "automated publication is disabled; use --preflight and manual upload"
    )


def _query_value(value: object) -> None:
    if isinstance(value, list):
        print(*value, sep="\n")
    elif isinstance(value, Mapping):
        print(json.dumps(value, sort_keys=True))
    elif isinstance(value, bool):
        print("true" if value else "false")
    else:
        print(value)


def command_query(args: argparse.Namespace) -> None:
    manifest = load_manifest(args.manifest)
    if args.query_command == "keys":
        print(*manifest.models, sep="\n")
    elif args.query_command == "meta":
        try:
            _query_value(manifest.meta[args.field])
        except KeyError as error:
            raise CacheError(f"unknown manifest meta field: {args.field}") from error
    elif args.query_command == "field":
        try:
            raw = tomllib.loads(manifest.raw_bytes.decode("utf-8"))["models"][
                args.model
            ]
            _query_value(raw[args.field])
        except KeyError as error:
            raise CacheError(
                f"unknown model field: {args.model}.{args.field}"
            ) from error
    elif args.query_command == "default":
        matches = [
            model.key
            for model in manifest.models.values()
            if args.model_type in model.default_for
        ]
        if len(matches) != 1:
            raise CacheError(f"expected exactly one default for {args.model_type}")
        print(matches[0])
    elif args.query_command == "type":
        print(
            *(
                model.key
                for model in manifest.models.values()
                if args.model_type in model.types
            ),
            sep="\n",
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "models-manifest.toml",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("validate").set_defaults(handler=command_validate)

    sync = subcommands.add_parser("sync")
    sync.add_argument("--model")
    sync.add_argument("--prepare", action="store_true")
    sync.add_argument("--upload", action="store_true")
    sync.add_argument("--cache-source")
    sync.add_argument("--discover-cache", action="append", default=[])
    sync.set_defaults(handler=command_sync)

    download = subcommands.add_parser("download")
    download.add_argument("model", nargs="?")
    download.add_argument("--list", action="store_true")
    type_group = download.add_mutually_exclusive_group()
    type_group.add_argument(
        "--all", action="store_const", const="all", dest="selection"
    )
    type_group.add_argument(
        "--embeddings", action="store_const", const="embedding", dest="model_type"
    )
    type_group.add_argument(
        "--rerankers", action="store_const", const="reranker", dest="model_type"
    )
    type_group.add_argument(
        "--images", action="store_const", const="image", dest="model_type"
    )
    type_group.add_argument(
        "--sparse", action="store_const", const="sparse", dest="model_type"
    )
    download.set_defaults(handler=command_download)

    check = subcommands.add_parser("check-updates")
    check.add_argument("--model")
    check_mode = check.add_mutually_exclusive_group()
    check_mode.add_argument("--apply", action="store_true")
    check_mode.add_argument("--adopt-current", action="store_true")
    check.set_defaults(handler=command_check_updates)

    upload = subcommands.add_parser("upload")
    upload.add_argument("--artifacts-dir", required=True)
    upload_modes = upload.add_mutually_exclusive_group(required=True)
    upload_modes.add_argument("--preflight", action="store_true")
    upload_modes.add_argument("--verify-remote", action="store_true")
    upload.set_defaults(handler=command_upload)

    query = subcommands.add_parser("query")
    query_subcommands = query.add_subparsers(dest="query_command", required=True)
    meta = query_subcommands.add_parser("meta")
    meta.add_argument("field")
    field = query_subcommands.add_parser("field")
    field.add_argument("model")
    field.add_argument("field")
    query_subcommands.add_parser("keys")
    default = query_subcommands.add_parser("default")
    default.add_argument("model_type", nargs="?", default="embedding")
    typed = query_subcommands.add_parser("type")
    typed.add_argument("model_type")
    query.set_defaults(handler=command_query)
    return parser


def main() -> int:
    try:
        args = build_parser().parse_args()
        args.manifest = args.manifest.resolve()
        args.handler(args)
    except (
        CacheError,
        PlatformFileDurabilityUnknown,
        OSError,
        tarfile.TarError,
        UnicodeError,
        ValueError,
    ) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
