#!/usr/bin/env python3
"""Install one verified Pyke ONNX Runtime archive into ORT_CACHE_DIR.

The script deliberately does not download anything. It accepts an archive that
was downloaded from this repository's GitHub Release, verifies the original
ort-sys distribution SHA-256, and then installs it at the exact path ort-sys
2.0.0-rc.13 probes before attempting a network request. POSIX installation is
anchored to no-follow directory descriptors; native Windows currently fails
closed until equivalent descriptor-relative primitives are implemented.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Generator
from contextlib import contextmanager
import ctypes
from dataclasses import dataclass
import errno
import hashlib
import lzma
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import stat
import sys
import tarfile
import tempfile
from typing import BinaryIO, IO, cast

import tomllib


RUNTIME_VERSION_DIR = Path("runtime/ort-sys-2.0.0-rc.13")
MANIFEST_NAME = "manifest.toml"
SUPPORTED_SCHEMA_VERSION = 1
EXPECTED_ARCHIVE_FORMAT = "tar+raw-lzma2"
EXPECTED_COMPONENT = "onnxruntime-native-static"
EXPECTED_RELEASE_REPO = "michelabboud/the-one-mcp-models-cache"
EXPECTED_RELEASE_TAG = "v6.0.2"
EXPECTED_ORT_SYS_VERSION = "2.0.0-rc.13"
EXPECTED_ORT_SYS_SOURCE_COMMIT = "002f41a8e175eac7f6695ff361d2e51a50874c48"
EXPECTED_ORT_SYS_DIST_URL = (
    "https://github.com/pykeio/ort/blob/"
    + EXPECTED_ORT_SYS_SOURCE_COMMIT
    + "/ort-sys/build/download/dist.tsv"
)
EXPECTED_ORT_SYS_DIST_SHA256 = (
    "c706a8bf67367fbec3ad7851d9b119f8830fbabe53696e20f4740131f7f59e78"
)
EXPECTED_ONNXRUNTIME_VERSION = "1.28.0"
EXPECTED_ONNXRUNTIME_RELEASE_URL = (
    "https://github.com/microsoft/onnxruntime/releases/tag/v1.28.0"
)
EXPECTED_ONNXRUNTIME_LICENSE = "MIT"
EXPECTED_ONNXRUNTIME_LICENSE_URL = (
    "https://github.com/microsoft/onnxruntime/blob/v1.28.0/LICENSE"
)
EXPECTED_DICTIONARY_BYTES = 64 * 1024 * 1024
EXPECTED_CACHE_PATH_TEMPLATE = "${ORT_CACHE_DIR}/dfbin/{target}/{sha256}/"
EXPECTED_PYKE_PREFIX = "https://cdn.pyke.io/0/pyke:ort-rs/ms@1.28.0/"
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
HASH_CHUNK_BYTES = 1024 * 1024
COPY_CHUNK_BYTES = 1024 * 1024
MAX_DECOMPRESSED_BYTES = 4 * 1024 * 1024 * 1024
MAX_COMPRESSED_BYTES = 1024 * 1024 * 1024
MAX_MANIFEST_BYTES = 1024 * 1024
MAX_TAR_MEMBERS = 128
MAX_TAR_MEMBER_BYTES = 2 * 1024 * 1024 * 1024
MAX_TAR_TOTAL_BYTES = 4 * 1024 * 1024 * 1024
MAX_TAR_EXTENSION_BYTES = 1024 * 1024
TAR_BLOCK_BYTES = 512
SAFE_TARGET = re.compile(r"^[A-Za-z0-9_]+(?:-[A-Za-z0-9_]+)+$")
SAFE_SHA256 = re.compile(r"^[0-9a-f]{64}$")
RENAME_NOREPLACE = 1
RENAME_EXCL = 0x00000004
PRIVATE_DIRECTORY_MODE = 0o700
CACHE_DIRECTORY_MODE = 0o777
PRIVATE_FILE_MODE = 0o600
TEMP_DIRECTORY_ATTEMPTS = 128
_WINDOWS = os.name == "nt"


class InstallerError(Exception):
    """A concise, operator-actionable installation failure."""


class InstallDurabilityUnknown(InstallerError):
    """The runtime is visible, but crash persistence could not be confirmed."""

    def __init__(self, path: Path) -> None:
        super().__init__(
            "runtime output is installed but durability is unknown; "
            + f"preserved for operator recovery: {path}"
        )


@dataclass(frozen=True)
class InstallArguments:
    """Validated command-line inputs used by the installer."""

    archive: Path
    target: str
    feature_set: str


@dataclass(frozen=True)
class Distribution:
    """The validated runtime manifest fields needed for installation."""

    dictionary_bytes: int
    sha256: str
    expected_library: str


@dataclass(frozen=True)
class DecompressedTarSnapshot:
    """Held tar bytes plus the state captured before the handoff boundary."""

    file: BinaryIO
    original_state: os.stat_result


@dataclass(frozen=True)
class ExtractedFileEvidence:
    """Byte and filesystem identity captured from one freshly written leaf."""

    identity: tuple[int, int]
    mutable_state: tuple[int, int, int]
    sha256: str


@dataclass
class RenamePublicationState:
    """Records the no-clobber rename commit point inside the atomic helper."""

    renamed: bool = False


def parse_args() -> InstallArguments:
    parser = argparse.ArgumentParser(
        description=(
            "Verify a mirrored Pyke ONNX Runtime archive and install it into "
            "ORT_CACHE_DIR at ort-sys's exact target/hash cache path."
        )
    )
    _ = parser.add_argument(
        "--archive", required=True, type=Path, help="downloaded .tar.lzma2 asset"
    )
    _ = parser.add_argument(
        "--target", required=True, help="Rust target triple from the runtime manifest"
    )
    _ = parser.add_argument(
        "--feature-set",
        default="none",
        help="exact ort-sys distribution feature set (default: none)",
    )
    values = cast(dict[str, object], vars(parser.parse_args()))
    archive = values.get("archive")
    if not isinstance(archive, Path):
        raise InstallerError("--archive must identify a filesystem path")
    return InstallArguments(
        archive=archive,
        target=require_string(values.get("target"), "target"),
        feature_set=require_string(values.get("feature_set"), "feature_set"),
    )


def require_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise InstallerError(f"manifest field '{field}' must be a non-empty string")
    return value


def require_table(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise InstallerError(f"manifest field '{field}' must be a table")
    return cast(dict[str, object], value)


def require_rows(value: object, field: str) -> list[object]:
    if not isinstance(value, list):
        raise InstallerError(f"manifest field '{field}' must be an array of tables")
    return cast(list[object], value)


def _validate_archive_row(
    raw: object,
    *,
    section: str,
    index: int,
    asset_field: str,
    require_reason: bool,
) -> tuple[str, str, str, str]:
    field = f"{section}[{index}]"
    row = require_table(raw, field)
    expected_fields = {
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
        expected_fields.add("reason")
    if set(row) != expected_fields:
        raise InstallerError(f"archive schema is incomplete or unsupported: {field}")

    target = require_string(row.get("target"), f"{field}.target")
    if not SAFE_TARGET.fullmatch(target):
        raise InstallerError(f"archive target is invalid: {target!r}")
    _ = require_string(row.get("platform"), f"{field}.platform")
    feature_set = require_string(row.get("feature_set"), f"{field}.feature_set")
    _ = require_string(row.get("execution_provider"), f"{field}.execution_provider")
    source_archive = require_string(
        row.get("source_archive"), f"{field}.source_archive"
    )
    if PurePosixPath(
        source_archive
    ).name != source_archive or not source_archive.endswith(".tar.lzma2"):
        raise InstallerError(f"archive source name is invalid: {source_archive!r}")
    source_url = require_string(row.get("source_url"), f"{field}.source_url")
    if source_url != EXPECTED_PYKE_PREFIX + source_archive:
        raise InstallerError("Pyke source is not the exact version-bound archive URL")
    asset = require_string(row.get(asset_field), f"{field}.{asset_field}")
    if PurePosixPath(asset).name != asset or not asset.endswith(".tar.lzma2"):
        raise InstallerError(f"archive release asset is invalid: {asset!r}")
    digest = require_string(row.get("sha256"), f"{field}.sha256")
    if not SAFE_SHA256.fullmatch(digest):
        raise InstallerError(f"archive SHA-256 is invalid: {digest!r}")
    expected_library = require_string(
        row.get("expected_library"), f"{field}.expected_library"
    )
    if expected_library not in {"libonnxruntime.a", "onnxruntime.lib"}:
        raise InstallerError(
            f"archive expected library is unsupported: {expected_library}"
        )
    cache_path = require_string(row.get("cache_path"), f"{field}.cache_path")
    if cache_path != f"${{ORT_CACHE_DIR}}/dfbin/{target}/{digest}/":
        raise InstallerError("archive cache path is not bound to target and SHA-256")
    if require_reason:
        _ = require_string(row.get("reason"), f"{field}.reason")
    return target, feature_set, source_archive, asset


def load_distribution(script_path: Path, target: str, feature_set: str) -> Distribution:
    repo_root = script_path.resolve().parent.parent
    manifest_path = repo_root / RUNTIME_VERSION_DIR / MANIFEST_NAME
    manifest_bytes = _read_bounded_regular_file_snapshot(manifest_path)
    try:
        manifest = cast(
            dict[str, object], tomllib.loads(manifest_bytes.decode("utf-8"))
        )
    except UnicodeDecodeError as error:
        raise InstallerError("runtime manifest is not valid UTF-8") from error

    top_level_fields = {
        "meta",
        "archives",
        "future_archives",
        "optional_archives",
        "unavailable_targets",
    }
    if set(manifest) != top_level_fields:
        raise InstallerError("top-level schema is incomplete or unsupported")
    meta = require_table(manifest.get("meta"), "meta")
    meta_fields = {
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
    if set(meta) != meta_fields:
        raise InstallerError("meta schema is incomplete or unsupported")
    if meta.get("schema_version") != SUPPORTED_SCHEMA_VERSION:
        raise InstallerError(
            f"unsupported runtime manifest schema: {meta.get('schema_version')!r}"
        )
    exact_meta = (
        ("component", EXPECTED_COMPONENT, "component"),
        ("release_repo", EXPECTED_RELEASE_REPO, "release repository"),
        ("release_tag", EXPECTED_RELEASE_TAG, "release tag"),
        ("ort_sys_version", EXPECTED_ORT_SYS_VERSION, "ort-sys version"),
        (
            "ort_sys_source_commit",
            EXPECTED_ORT_SYS_SOURCE_COMMIT,
            "ort-sys source commit",
        ),
        ("ort_sys_dist_table_url", EXPECTED_ORT_SYS_DIST_URL, "ort-sys dist URL"),
        (
            "ort_sys_dist_table_sha256",
            EXPECTED_ORT_SYS_DIST_SHA256,
            "ort-sys dist digest",
        ),
        (
            "onnxruntime_version",
            EXPECTED_ONNXRUNTIME_VERSION,
            "ONNX Runtime version",
        ),
        (
            "onnxruntime_release_url",
            EXPECTED_ONNXRUNTIME_RELEASE_URL,
            "ONNX Runtime release URL",
        ),
        (
            "onnxruntime_license",
            EXPECTED_ONNXRUNTIME_LICENSE,
            "ONNX Runtime license",
        ),
        (
            "onnxruntime_license_url",
            EXPECTED_ONNXRUNTIME_LICENSE_URL,
            "ONNX Runtime license URL",
        ),
        ("archive_format", EXPECTED_ARCHIVE_FORMAT, "archive format"),
        (
            "cache_path_template",
            EXPECTED_CACHE_PATH_TEMPLATE,
            "cache path template",
        ),
    )
    for field, expected, label in exact_meta:
        if meta.get(field) != expected:
            raise InstallerError(f"{label} must match the exact supported rc13 tuple")
    if meta.get("archive_format") != EXPECTED_ARCHIVE_FORMAT:
        raise InstallerError(
            f"unsupported archive format: {meta.get('archive_format')!r}"
        )
    dictionary_bytes = meta.get("lzma2_dictionary_bytes")
    if (
        not isinstance(dictionary_bytes, int)
        or isinstance(dictionary_bytes, bool)
        or dictionary_bytes != EXPECTED_DICTIONARY_BYTES
    ):
        raise InstallerError("dictionary must match the exact supported rc13 tuple")

    seen_targets: set[tuple[str, str]] = set()
    seen_sources: set[str] = set()
    seen_assets: set[str] = set()
    selected: Distribution | None = None
    archives = require_rows(manifest.get("archives"), "archives")
    if len(archives) != len(REVIEWED_RUNTIME_ARCHIVES):
        raise InstallerError(
            "runtime manifest must contain exactly four reviewed archives"
        )
    reviewed_rows: dict[tuple[str, str], tuple[str, ...]] = {}
    for index, raw_archive in enumerate(archives):
        archive = require_table(raw_archive, f"archives[{index}]")
        row_target, row_feature, source, asset = _validate_archive_row(
            raw_archive,
            section="archives",
            index=index,
            asset_field="release_asset",
            require_reason=False,
        )
        if (row_target, row_feature) in seen_targets:
            raise InstallerError("archive target and feature set must be unique")
        if source in seen_sources or asset in seen_assets:
            raise InstallerError(
                "archive source and release asset names must be unique"
            )
        seen_targets.add((row_target, row_feature))
        seen_sources.add(source)
        seen_assets.add(asset)
        reviewed_rows[(row_target, row_feature)] = (
            row_target,
            row_feature,
            require_string(
                archive.get("execution_provider"),
                f"archives[{index}].execution_provider",
            ),
            source,
            require_string(archive.get("source_url"), f"archives[{index}].source_url"),
            asset,
            require_string(
                archive.get("expected_library"),
                f"archives[{index}].expected_library",
            ),
            require_string(archive.get("sha256"), f"archives[{index}].sha256"),
        )
        if row_target == target and row_feature == feature_set:
            selected = Distribution(
                dictionary_bytes=dictionary_bytes,
                sha256=require_string(archive.get("sha256"), "archives.sha256"),
                expected_library=require_string(
                    archive.get("expected_library"), "archives.expected_library"
                ),
            )

    expected_reviewed_rows = {
        (row[0], row[1]): row for row in REVIEWED_RUNTIME_ARCHIVES
    }
    if reviewed_rows != expected_reviewed_rows:
        raise InstallerError(
            "required runtime archives must match the exact reviewed rc13 runtime map"
        )

    for section in ("future_archives", "optional_archives"):
        for index, raw_archive in enumerate(
            require_rows(manifest.get(section), section)
        ):
            row_target, row_feature, source, asset = _validate_archive_row(
                raw_archive,
                section=section,
                index=index,
                asset_field="proposed_release_asset",
                require_reason=True,
            )
            if (row_target, row_feature) in seen_targets:
                raise InstallerError("archive target and feature set must be unique")
            if source in seen_sources or asset in seen_assets:
                raise InstallerError(
                    "archive source and release asset names must be unique"
                )
            seen_targets.add((row_target, row_feature))
            seen_sources.add(source)
            seen_assets.add(asset)

    unavailable_targets: set[str] = set()
    for index, raw_target in enumerate(
        require_rows(manifest.get("unavailable_targets"), "unavailable_targets")
    ):
        field = f"unavailable_targets[{index}]"
        unavailable = require_table(raw_target, field)
        if set(unavailable) != {"target", "platform", "reason"}:
            raise InstallerError(
                f"archive schema is incomplete or unsupported: {field}"
            )
        unavailable_target = require_string(
            unavailable.get("target"), f"{field}.target"
        )
        if not SAFE_TARGET.fullmatch(unavailable_target):
            raise InstallerError(
                f"unavailable target is invalid: {unavailable_target!r}"
            )
        _ = require_string(unavailable.get("platform"), f"{field}.platform")
        _ = require_string(unavailable.get("reason"), f"{field}.reason")
        if unavailable_target in unavailable_targets:
            raise InstallerError("unavailable targets must be unique")
        unavailable_targets.add(unavailable_target)

    if selected is not None:
        return selected

    raise InstallerError(
        f"no current runtime archive for target '{target}' and feature set '{feature_set}'"
    )


def file_identity(file_stat: os.stat_result) -> tuple[int, int]:
    """Return the stable identity fields available on supported platforms."""
    return file_stat.st_dev, file_stat.st_ino


def mutable_file_state(file_stat: os.stat_result) -> tuple[int, int, int]:
    """Return fields that detect in-place changes while a file is copied."""
    return file_stat.st_size, file_stat.st_mtime_ns, file_stat.st_ctime_ns


def _read_bounded_regular_file_snapshot(path: Path) -> bytes:
    """Read one bounded immutable regular-file view without following a symlink."""
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise InstallerError(f"runtime manifest not found or unsafe: {path}") from error
    with os.fdopen(descriptor, "rb") as source, tempfile.TemporaryFile() as snapshot:
        before = os.fstat(source.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise InstallerError(
                "runtime manifest must be a single-linked regular file"
            )
        if before.st_size > MAX_MANIFEST_BYTES:
            raise InstallerError("runtime manifest bytes exceed the safe size limit")
        copied = 0
        while chunk := source.read(HASH_CHUNK_BYTES):
            copied += len(chunk)
            if copied > MAX_MANIFEST_BYTES:
                raise InstallerError(
                    "runtime manifest bytes exceed the safe size limit"
                )
            _ = snapshot.write(chunk)
        after = os.fstat(source.fileno())
        if file_identity(after) != file_identity(before) or mutable_file_state(
            after
        ) != mutable_file_state(before):
            raise InstallerError("runtime manifest changed while it was snapshotted")
        _ = snapshot.seek(0)
        return snapshot.read()


def _directory_open_flags() -> int:
    """Return flags that open one real directory without following its final name."""
    return (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )


def _require_secure_posix_primitives() -> None:
    """Fail before cache mutation when descriptor-anchored installation is unavailable."""
    if _WINDOWS:
        raise InstallerError(
            "native Windows runtime installation is not yet securely supported"
        )
    if not (sys.platform.startswith("linux") or sys.platform == "darwin"):
        raise InstallerError(
            "this platform lacks descriptor-anchored no-clobber installation"
        )
    required_dir_fd = (os.open, os.mkdir, os.stat)
    if (
        getattr(os, "O_DIRECTORY", 0) == 0
        or getattr(os, "O_NOFOLLOW", 0) == 0
        or any(function not in os.supports_dir_fd for function in required_dir_fd)
    ):
        raise InstallerError(
            "this platform lacks descriptor-anchored no-follow filesystem operations"
        )


def _relative_entry_name(path: Path, field: str) -> str:
    """Require one relative path component for a descriptor-relative operation."""
    value = os.fspath(path)
    if (
        not value
        or value in {".", ".."}
        or os.path.isabs(value)
        or "/" in value
        or "\\" in value
    ):
        raise InstallerError(f"{field} must be one relative path component")
    return value


def _open_or_create_directory_at(
    parent_fd: int,
    name: str,
    *,
    mode: int,
    context: str,
) -> int:
    """Open one child directory beneath a verified parent descriptor."""
    created = False
    try:
        os.mkdir(name, mode=mode, dir_fd=parent_fd)
        created = True
    except FileExistsError:
        pass
    except OSError as error:
        raise InstallerError(
            f"could not create {context} directory {name!r}: {error}"
        ) from error

    try:
        descriptor = os.open(name, _directory_open_flags(), dir_fd=parent_fd)
    except OSError as error:
        if error.errno in {errno.ELOOP, errno.ENOTDIR}:
            detail = "is a symlink or is not a directory"
        else:
            detail = str(error)
        raise InstallerError(f"{context} directory {name!r} {detail}") from error
    opened_state = os.fstat(descriptor)
    if not stat.S_ISDIR(opened_state.st_mode):
        os.close(descriptor)
        raise InstallerError(f"{context} directory {name!r} is not a directory")
    if created:
        try:
            os.fsync(descriptor)
            os.fsync(parent_fd)
        except BaseException:
            os.close(descriptor)
            raise
    return descriptor


@contextmanager
def _opened_or_created_directory(
    parent_fd: int,
    name: str,
    *,
    mode: int,
    context: str,
) -> Generator[int]:
    descriptor = _open_or_create_directory_at(
        parent_fd, name, mode=mode, context=context
    )
    try:
        yield descriptor
    finally:
        os.close(descriptor)


@contextmanager
def _secure_cache_root(cache_root: Path) -> Generator[int]:
    """Create and open a POSIX cache root one no-follow component at a time."""
    try:
        current_fd = os.open(cache_root.anchor, _directory_open_flags())
    except OSError as error:
        raise InstallerError(
            f"could not securely open ORT_CACHE_DIR anchor: {cache_root.anchor}: {error}"
        ) from error
    try:
        for part in cache_root.parts[1:]:
            next_fd = _open_or_create_directory_at(
                current_fd,
                part,
                mode=CACHE_DIRECTORY_MODE,
                context="cache",
            )
            os.close(current_fd)
            current_fd = next_fd
        yield current_fd
    finally:
        os.close(current_fd)


@contextmanager
def _private_staging_directory(
    parent_fd: int, prefix: str
) -> Generator[tuple[str, int]]:
    """Yield a private temporary directory anchored beneath a verified parent."""
    name = ""
    for _ in range(TEMP_DIRECTORY_ATTEMPTS):
        candidate = prefix + secrets.token_hex(16)
        try:
            os.mkdir(candidate, mode=PRIVATE_DIRECTORY_MODE, dir_fd=parent_fd)
        except FileExistsError:
            continue
        name = candidate
        break
    if not name:
        raise InstallerError("could not allocate a private staging directory")

    try:
        descriptor = _open_or_create_directory_at(
            parent_fd,
            name,
            mode=PRIVATE_DIRECTORY_MODE,
            context="staging",
        )
    except BaseException:
        print(
            f"warning: preserved ambiguous private runtime staging entry {name}",
            file=sys.stderr,
        )
        raise
    identity = file_identity(os.fstat(descriptor))
    try:
        yield name, descriptor
    finally:
        removed = _remove_owned_directory_at(
            parent_fd,
            name,
            identity,
            directory_fd=descriptor,
        )
        os.close(descriptor)
        if not removed:
            print(
                f"warning: preserved private runtime staging entry {name}; "
                + "safe identity-bound deletion is unavailable",
                file=sys.stderr,
            )


@contextmanager
def verified_archive_snapshot(path: Path, expected_sha256: str) -> Generator[BinaryIO]:
    """Yield one private snapshot whose bytes produced the verified checksum.

    Opening and hashing a pathname before reopening it for extraction permits a
    path-swap attack. This function opens the source once, copies it in bounded
    chunks to an anonymous temporary file, hashes exactly those copied bytes,
    and yields that same private descriptor for decompression.
    """
    try:
        path_state = path.stat(follow_symlinks=False)
    except FileNotFoundError as error:
        raise InstallerError(
            f"archive must be a regular, non-symlink file: {path}"
        ) from error
    if not stat.S_ISREG(path_state.st_mode):
        raise InstallerError(f"archive must be a regular, non-symlink file: {path}")

    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise InstallerError(
            f"could not securely open archive: {path}: {error}"
        ) from error

    with (
        os.fdopen(descriptor, "rb") as source,
        tempfile.TemporaryFile(mode="w+b") as snapshot,
    ):
        opened_state = os.fstat(source.fileno())
        if not stat.S_ISREG(opened_state.st_mode) or file_identity(
            opened_state
        ) != file_identity(path_state):
            raise InstallerError(f"archive changed while it was being opened: {path}")
        if opened_state.st_size > MAX_COMPRESSED_BYTES:
            raise InstallerError(
                f"compressed archive exceeds the {MAX_COMPRESSED_BYTES}-byte safety limit"
            )

        digest = hashlib.sha256()
        copied = 0
        while chunk := source.read(HASH_CHUNK_BYTES):
            copied += len(chunk)
            if copied > MAX_COMPRESSED_BYTES:
                raise InstallerError(
                    f"compressed archive exceeds the {MAX_COMPRESSED_BYTES}-byte safety limit"
                )
            _ = snapshot.write(chunk)
            digest.update(chunk)

        final_state = os.fstat(source.fileno())
        if mutable_file_state(final_state) != mutable_file_state(opened_state):
            raise InstallerError(
                f"archive changed while it was being snapshotted: {path}"
            )

        actual_sha256 = digest.hexdigest()
        if actual_sha256 != expected_sha256:
            message = (
                f"archive checksum mismatch: expected {expected_sha256}, "
                f"got {actual_sha256}; cache was not modified"
            )
            raise InstallerError(message)

        snapshot.flush()
        _ = snapshot.seek(0)
        yield snapshot


def iter_decompressed_chunks(
    source: BinaryIO, dictionary_bytes: int
) -> Generator[bytes]:
    """Yield raw LZMA2 output in bounded chunks and reject malformed streams."""
    decompressor = lzma.LZMADecompressor(
        format=lzma.FORMAT_RAW,
        filters=[{"id": lzma.FILTER_LZMA2, "dict_size": dictionary_bytes}],
    )
    written = 0
    _ = source.seek(0)
    while compressed := source.read(COPY_CHUNK_BYTES):
        pending = compressed
        while True:
            if decompressor.eof:
                raise InstallerError(
                    "archive contains trailing data after the LZMA2 stream"
                )
            max_output = min(COPY_CHUNK_BYTES, MAX_DECOMPRESSED_BYTES - written + 1)
            decoded = decompressor.decompress(pending, max_length=max_output)
            pending = b""
            written += len(decoded)
            if written > MAX_DECOMPRESSED_BYTES:
                raise InstallerError(
                    f"archive expands beyond the {MAX_DECOMPRESSED_BYTES}-byte safety limit"
                )
            if decoded:
                yield decoded
            if decompressor.eof and (decompressor.unused_data or source.read(1)):
                raise InstallerError(
                    "archive contains trailing data after the LZMA2 stream"
                )
            if decompressor.eof:
                return
            if decompressor.needs_input:
                break
            if not decoded:
                raise InstallerError(
                    "raw LZMA2 decoder stalled before reaching end-of-stream"
                )

    raise InstallerError("archive ended before the raw LZMA2 stream completed")


def _write_decompressed_raw_lzma2(
    source: BinaryIO, destination: BinaryIO, dictionary_bytes: int
) -> None:
    for decoded in iter_decompressed_chunks(source, dictionary_bytes):
        _ = destination.write(decoded)


def _assert_decompressed_tar_stable(
    tar_input: BinaryIO, expected_state: os.stat_result
) -> None:
    """Require the held decompressed tar to retain its reviewed file state."""
    current_state = os.fstat(tar_input.fileno())
    if (
        not stat.S_ISREG(current_state.st_mode)
        or current_state.st_nlink != 1
        or file_identity(current_state) != file_identity(expected_state)
        or mutable_file_state(current_state) != mutable_file_state(expected_state)
    ):
        raise InstallerError("decompressed tar changed during extraction")


@contextmanager
def decompressed_tar_snapshot(
    source: BinaryIO,
    destination: Path,
    dictionary_bytes: int,
    *,
    destination_dir_fd: int | None = None,
) -> Generator[DecompressedTarSnapshot]:
    """Yield held tar bytes bound to the state captured before handoff."""
    flags = (
        os.O_RDWR
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    if destination_dir_fd is None:
        descriptor = os.open(destination, flags, PRIVATE_FILE_MODE)
    else:
        name = _relative_entry_name(destination, "decompression destination")
        descriptor = os.open(
            name,
            flags,
            PRIVATE_FILE_MODE,
            dir_fd=destination_dir_fd,
        )
    with os.fdopen(descriptor, "w+b") as tar_output:
        _write_decompressed_raw_lzma2(source, tar_output, dictionary_bytes)
        tar_output.flush()
        opened_state = os.fstat(tar_output.fileno())
        if not stat.S_ISREG(opened_state.st_mode) or opened_state.st_nlink != 1:
            raise InstallerError("decompressed tar is not a single-linked regular file")
        _ = tar_output.seek(0)
        yield DecompressedTarSnapshot(tar_output, opened_state)
        _assert_decompressed_tar_stable(tar_output, opened_state)


def decompress_raw_lzma2(
    source: BinaryIO,
    destination: Path,
    dictionary_bytes: int,
    *,
    destination_dir_fd: int | None = None,
) -> None:
    """Decompress to a new file, closing it only after the write is complete."""
    with decompressed_tar_snapshot(
        source,
        destination,
        dictionary_bytes,
        destination_dir_fd=destination_dir_fd,
    ):
        pass


def safe_member_path(member_name: str) -> PurePosixPath:
    member_path = PurePosixPath(member_name)
    if (
        not member_name
        or "\\" in member_name
        or "\0" in member_name
        or member_path.is_absolute()
        or member_path == PurePosixPath(".")
        or any(part in {"", ".", ".."} for part in member_path.parts)
        or member_path.as_posix() != member_name
    ):
        raise InstallerError(f"unsafe archive member path: {member_name!r}")
    return member_path


def _copy_member_at(
    source: IO[bytes],
    staging_fd: int,
    member_path: PurePosixPath,
    expected_size: int,
) -> ExtractedFileEvidence:
    """Copy one member beneath an opened staging directory without path traversal."""
    current_fd = os.dup(staging_fd)
    try:
        for parent in member_path.parts[:-1]:
            next_fd = _open_or_create_directory_at(
                current_fd,
                parent,
                mode=PRIVATE_DIRECTORY_MODE,
                context="archive",
            )
            os.close(current_fd)
            current_fd = next_fd

        name = member_path.name
        flags = (
            os.O_RDWR
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        try:
            descriptor = os.open(
                name,
                flags,
                PRIVATE_FILE_MODE,
                dir_fd=current_fd,
            )
        except FileExistsError as error:
            raise InstallerError(
                f"duplicate or conflicting archive member: {member_path.as_posix()!r}"
            ) from error
        with os.fdopen(descriptor, "w+b") as output:
            digest = hashlib.sha256()
            remaining = expected_size
            while remaining:
                chunk = source.read(min(COPY_CHUNK_BYTES, remaining))
                if not chunk:
                    raise InstallerError(
                        "archive member ended before its declared size: "
                        + repr(member_path.as_posix())
                    )
                written = output.write(chunk)
                if written != len(chunk):
                    raise InstallerError(
                        "short write while extracting archive member: "
                        + repr(member_path.as_posix())
                    )
                digest.update(chunk)
                remaining -= len(chunk)
            output.flush()
            written_state = os.fstat(output.fileno())
            if (
                not stat.S_ISREG(written_state.st_mode)
                or written_state.st_nlink != 1
                or written_state.st_size != expected_size
            ):
                raise InstallerError(
                    "extracted archive member output is invalid: "
                    + repr(member_path.as_posix())
                )
            output.seek(0)
            output_digest = hashlib.sha256()
            output_size = 0
            while chunk := output.read(COPY_CHUNK_BYTES):
                output_size += len(chunk)
                if output_size > expected_size:
                    raise InstallerError(
                        "extracted archive member output exceeded its declared size: "
                        + repr(member_path.as_posix())
                    )
                output_digest.update(chunk)
            final_state = os.fstat(output.fileno())
            if (
                file_identity(final_state) != file_identity(written_state)
                or mutable_file_state(final_state) != mutable_file_state(written_state)
                or output_size != expected_size
                or output_digest.digest() != digest.digest()
            ):
                raise InstallerError(
                    "extracted archive member output bytes changed while captured: "
                    + repr(member_path.as_posix())
                )
            return ExtractedFileEvidence(
                identity=file_identity(final_state),
                mutable_state=mutable_file_state(final_state),
                sha256=output_digest.hexdigest(),
            )
    finally:
        os.close(current_fd)


def _validate_runtime_output_tree(
    payload_fd: int,
    expected_library: str,
    evidence: ExtractedFileEvidence,
) -> int:
    """Open and validate the exact staged/published runtime output inventory."""
    found_library = False
    try:
        with os.scandir(payload_fd) as entries:
            for entry in entries:
                if found_library or entry.name != expected_library:
                    raise InstallerError(
                        "runtime output inventory must contain exactly the "
                        + "expected root library"
                    )
                found_library = True
    except OSError as error:
        raise InstallerError("could not inspect runtime output inventory") from error
    if not found_library:
        raise InstallerError(
            "runtime output inventory must contain exactly the expected root library"
        )
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    try:
        descriptor = os.open(expected_library, flags, dir_fd=payload_fd)
    except OSError as error:
        raise InstallerError(
            "runtime output leaf changed while it was opened"
        ) from error
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or file_identity(before) != evidence.identity
            or mutable_file_state(before) != evidence.mutable_state
        ):
            raise InstallerError(
                "runtime output leaf identity changed after extraction"
            )
        digest = hashlib.sha256()
        size = 0
        while chunk := os.read(descriptor, COPY_CHUNK_BYTES):
            size += len(chunk)
            if size > evidence.mutable_state[0]:
                raise InstallerError("runtime output leaf bytes exceed extracted size")
            digest.update(chunk)
        after = os.fstat(descriptor)
        if (
            file_identity(after) != evidence.identity
            or mutable_file_state(after) != evidence.mutable_state
            or size != evidence.mutable_state[0]
            or digest.hexdigest() != evidence.sha256
        ):
            raise InstallerError("runtime output leaf bytes changed after extraction")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _validate_raw_tar_zero_tail(source: BinaryIO) -> None:
    """Consume bounded, block-aligned zero padding through decompressed EOF."""
    padding_bytes = TAR_BLOCK_BYTES
    while True:
        remaining = tarfile.RECORDSIZE - padding_bytes + 1
        chunk = source.read(min(COPY_CHUNK_BYTES, remaining))
        if not chunk:
            break
        padding_bytes += len(chunk)
        if padding_bytes > tarfile.RECORDSIZE:
            raise InstallerError("tar archive padding exceeds the safe limit")
        if chunk.strip(b"\0"):
            raise InstallerError("tar archive contains nonzero trailing data")
    if padding_bytes < 2 * TAR_BLOCK_BYTES or padding_bytes % TAR_BLOCK_BYTES:
        raise InstallerError("tar archive padding is incomplete or unaligned")


def _prevalidate_raw_tar_headers(tar_input: BinaryIO) -> None:
    """Bound raw headers before ``tarfile`` can consume extension payloads.

    Python's tar iterator resolves PAX and GNU long-name records before it yields
    the corresponding member. Inspecting the raw 512-byte records first prevents
    a hostile extension size from causing one large, pre-counter read.
    """
    extension_types = {
        tarfile.XHDTYPE,
        tarfile.XGLTYPE,
        tarfile.GNUTYPE_LONGNAME,
        tarfile.GNUTYPE_LONGLINK,
    }
    solaris_extension = getattr(tarfile, "SOLARIS_XHDTYPE", None)
    if isinstance(solaris_extension, bytes):
        extension_types.add(solaris_extension)

    _ = tar_input.seek(0, os.SEEK_END)
    stream_bytes = tar_input.tell()
    _ = tar_input.seek(0)
    raw_headers = 0
    raw_total = 0
    while True:
        header = tar_input.read(TAR_BLOCK_BYTES)
        if not header:
            raise InstallerError("tar archive ended before its end marker")
        if len(header) != TAR_BLOCK_BYTES:
            raise InstallerError("tar archive contains a truncated raw header")
        if header == bytes(TAR_BLOCK_BYTES):
            _validate_raw_tar_zero_tail(tar_input)
            _ = tar_input.seek(0)
            return
        try:
            raw = tarfile.TarInfo.frombuf(header, "utf-8", "surrogateescape")
        except tarfile.HeaderError as error:
            raise InstallerError(
                f"tar archive contains an invalid raw header: {error}"
            ) from error

        raw_headers += 1
        if raw_headers > MAX_TAR_MEMBERS:
            raise InstallerError(
                f"archive member count exceeds the {MAX_TAR_MEMBERS}-member safety limit"
            )
        if raw.size < 0:
            raise InstallerError("tar archive raw member size cannot be negative")
        if raw.type in extension_types:
            if raw.size > MAX_TAR_EXTENSION_BYTES:
                raise InstallerError(
                    "archive extension size exceeds the "
                    + f"{MAX_TAR_EXTENSION_BYTES}-byte safety limit"
                )
        elif raw.type == tarfile.GNUTYPE_SPARSE:
            raise InstallerError(f"sparse archive member is not allowed: {raw.name!r}")
        else:
            if raw.size > MAX_TAR_MEMBER_BYTES:
                raise InstallerError(
                    "archive member size exceeds the "
                    + f"{MAX_TAR_MEMBER_BYTES}-byte safety limit: {raw.name!r}"
                )
            raw_total += raw.size
            if raw_total > MAX_TAR_TOTAL_BYTES:
                raise InstallerError(
                    "archive total logical size exceeds the "
                    + f"{MAX_TAR_TOTAL_BYTES}-byte safety limit"
                )

        padded_size = (
            (raw.size + TAR_BLOCK_BYTES - 1) // TAR_BLOCK_BYTES
        ) * TAR_BLOCK_BYTES
        next_header = tar_input.tell() + padded_size
        if next_header > stream_bytes:
            raise InstallerError(
                f"tar archive ended before declared member data: {raw.name!r}"
            )
        _ = tar_input.seek(next_header)


def _extract_tar_stream_safely(
    tar_input: BinaryIO,
    staging_fd: int,
    expected_library: str | None,
) -> dict[str, ExtractedFileEvidence]:
    """Validate a bounded tar inventory and extract only after it is accepted."""
    _prevalidate_raw_tar_headers(tar_input)
    with tarfile.open(fileobj=tar_input, mode="r:") as archive:
        seen: set[str] = set()
        regular_files: set[str] = set()
        members: list[tarfile.TarInfo] = []
        total_size = 0
        allowed_directories: set[str] = set()
        if expected_library is not None:
            expected_path = PurePosixPath(expected_library)
            allowed_directories = {
                parent.as_posix()
                for parent in expected_path.parents
                if parent != PurePosixPath(".")
            }

        for member in archive:
            members.append(member)
            if len(members) > MAX_TAR_MEMBERS:
                raise InstallerError(
                    f"archive member count exceeds the {MAX_TAR_MEMBERS}-member safety limit"
                )
            member_path = safe_member_path(member.name)
            normalized_name = member_path.as_posix()
            if normalized_name in seen:
                raise InstallerError(
                    f"duplicate normalized archive member: {normalized_name!r}"
                )
            seen.add(normalized_name)
            if member.isdir():
                if (
                    expected_library is not None
                    and normalized_name not in allowed_directories
                ):
                    raise InstallerError(
                        f"unexpected archive directory member: {normalized_name!r}"
                    )
                continue
            if not member.isreg():
                detail = f"unsafe archive member type for {member.name!r}"
                raise InstallerError(
                    f"{detail}; only files and directories are allowed"
                )
            if getattr(member, "sparse", None) is not None:
                raise InstallerError(
                    f"sparse archive member is not allowed: {member.name!r}"
                )
            if member.size < 0 or member.size > MAX_TAR_MEMBER_BYTES:
                message = (
                    f"archive member size exceeds the {MAX_TAR_MEMBER_BYTES}-byte safety "
                    + f"limit: {member.name!r}"
                )
                raise InstallerError(message)
            total_size += member.size
            if total_size > MAX_TAR_TOTAL_BYTES:
                message = (
                    f"archive total logical size exceeds the {MAX_TAR_TOTAL_BYTES}-byte safety "
                    + "limit"
                )
                raise InstallerError(message)
            regular_files.add(normalized_name)

        if not members:
            raise InstallerError("archive contains no files")
        if expected_library is not None and regular_files != {expected_library}:
            message = (
                "archive file inventory must contain exactly the expected root library: "
                + expected_library
            )
            raise InstallerError(message)

        evidence: dict[str, ExtractedFileEvidence] = {}
        for member in members:
            if member.isdir():
                continue
            member_path = safe_member_path(member.name)
            extracted = archive.extractfile(member)
            if extracted is None:
                raise InstallerError(f"could not read archive member: {member.name!r}")
            with extracted:
                evidence[member_path.as_posix()] = _copy_member_at(
                    extracted, staging_fd, member_path, member.size
                )
        return evidence


def extract_tar_safely(
    tar_path: Path,
    staging: Path,
    expected_library: str | None = None,
    *,
    tar_dir_fd: int | None = None,
    staging_dir_fd: int | None = None,
    tar_file: BinaryIO | None = None,
) -> dict[str, ExtractedFileEvidence]:
    """Safely extract one tar using optional verified directory descriptors."""
    tar_descriptor = -1
    if tar_file is not None:
        tar_input = tar_file
    elif tar_dir_fd is None:
        tar_descriptor = os.open(
            tar_path,
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0),
        )
        tar_input = os.fdopen(tar_descriptor, "rb")
        tar_descriptor = -1
    else:
        tar_name = _relative_entry_name(tar_path, "tar input")
        tar_descriptor = os.open(
            tar_name,
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0),
            dir_fd=tar_dir_fd,
        )
        tar_input = os.fdopen(tar_descriptor, "rb")
        tar_descriptor = -1

    try:
        if staging_dir_fd is None:
            staging_descriptor = os.open(staging, _directory_open_flags())
        else:
            staging_descriptor = os.dup(staging_dir_fd)
    except BaseException:
        if tar_file is None:
            tar_input.close()
        elif tar_descriptor >= 0:
            os.close(tar_descriptor)
        raise
    try:
        if tar_file is not None:
            opened_state = os.fstat(tar_input.fileno())
            if not stat.S_ISREG(opened_state.st_mode) or opened_state.st_nlink != 1:
                raise InstallerError(
                    "decompressed tar is not a single-linked regular file"
                )
            _ = tar_input.seek(0)
            return _extract_tar_stream_safely(
                tar_input,
                staging_descriptor,
                expected_library,
            )
        else:
            with tar_input:
                return _extract_tar_stream_safely(
                    tar_input,
                    staging_descriptor,
                    expected_library,
                )
    finally:
        if tar_descriptor >= 0:
            os.close(tar_descriptor)
        os.close(staging_descriptor)


def validate_explicit_cache_root(value: str) -> Path:
    """Reject ambiguous cache roots and every existing symlink ancestor."""
    cache_root = Path(value)
    if not cache_root.is_absolute():
        raise InstallerError("ORT_CACHE_DIR must be an absolute path")
    if (
        (os.name != "nt" and value.startswith("//"))
        or os.path.normpath(value) != value
        or str(cache_root) != value
    ):
        raise InstallerError("ORT_CACHE_DIR must be a canonical lexical path")
    if cache_root == Path(cache_root.anchor):
        raise InstallerError("ORT_CACHE_DIR cannot be a filesystem root")

    current = Path(cache_root.anchor)
    for part in cache_root.parts[1:]:
        current = current / part
        try:
            current_state = current.lstat()
        except FileNotFoundError:
            break
        if stat.S_ISLNK(current_state.st_mode):
            raise InstallerError(
                f"ORT_CACHE_DIR cannot contain a symlink ancestor: {current}"
            )
        if not stat.S_ISDIR(current_state.st_mode):
            raise InstallerError(
                f"ORT_CACHE_DIR ancestor is not a directory: {current}"
            )
    return cache_root


def verified_directory_identity(
    path: Path, expected: tuple[int, int] | None = None
) -> tuple[int, int]:
    """Return a non-symlink directory identity and reject path substitution."""
    directory_state = path.lstat()
    if stat.S_ISLNK(directory_state.st_mode) or not stat.S_ISDIR(
        directory_state.st_mode
    ):
        raise InstallerError(f"cache directory is not a stable real directory: {path}")
    identity = file_identity(directory_state)
    if expected is not None and identity != expected:
        raise InstallerError(f"cache directory changed during installation: {path}")
    return identity


def atomic_rename_noreplace(
    source: Path,
    destination: Path,
    *,
    source_dir_fd: int | None = None,
    destination_dir_fd: int | None = None,
    source_identity: tuple[int, int] | None = None,
    publication_state: RenamePublicationState | None = None,
) -> None:
    """Atomically install relative to verified parent fds without replacement."""
    if _WINDOWS:
        if source_dir_fd is not None or destination_dir_fd is not None:
            raise InstallerError(
                "native Windows does not support descriptor-relative runtime installation"
            )
        _ = source.rename(destination)
        if publication_state is not None:
            publication_state.renamed = True
        return

    if source_dir_fd is None or destination_dir_fd is None:
        raise InstallerError(
            "POSIX no-clobber installation requires verified parent descriptors"
        )
    source_name = _relative_entry_name(source, "rename source")
    destination_name = _relative_entry_name(destination, "rename destination")
    if source_identity is not None:
        try:
            source_state = os.stat(
                source_name,
                dir_fd=source_dir_fd,
                follow_symlinks=False,
            )
        except OSError as error:
            raise InstallerError("payload changed before publication") from error
        if (
            not stat.S_ISDIR(source_state.st_mode)
            or file_identity(source_state) != source_identity
        ):
            raise InstallerError("payload changed before publication")

    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform.startswith("linux"):
        raw_function = getattr(libc, "renameat2", None)
        if raw_function is None:
            raise InstallerError(
                "this platform lacks atomic no-clobber directory installation"
            )
        renameat2 = cast(Callable[[int, bytes, int, bytes, int], int], raw_function)
        result = renameat2(
            source_dir_fd,
            os.fsencode(source_name),
            destination_dir_fd,
            os.fsencode(destination_name),
            RENAME_NOREPLACE,
        )
    elif sys.platform == "darwin":
        raw_function = getattr(libc, "renameatx_np", None)
        if raw_function is None:
            raise InstallerError(
                "this platform lacks atomic no-clobber directory installation"
            )
        renameatx_np = cast(Callable[[int, bytes, int, bytes, int], int], raw_function)
        result = renameatx_np(
            source_dir_fd,
            os.fsencode(source_name),
            destination_dir_fd,
            os.fsencode(destination_name),
            RENAME_EXCL,
        )
    else:
        raise InstallerError(
            "this platform lacks atomic no-clobber directory installation"
        )

    if result == 0:
        if publication_state is not None:
            publication_state.renamed = True
        if source_identity is not None:
            try:
                installed_state = os.stat(
                    destination_name,
                    dir_fd=destination_dir_fd,
                    follow_symlinks=False,
                )
            except OSError as error:
                raise InstallerError("payload changed during publication") from error
            if (
                not stat.S_ISDIR(installed_state.st_mode)
                or file_identity(installed_state) != source_identity
            ):
                raise InstallerError("payload changed during publication")
        return
    error_number = ctypes.get_errno()
    if error_number in {errno.EEXIST, errno.ENOTEMPTY}:
        raise FileExistsError(error_number, os.strerror(error_number), destination_name)
    raise OSError(error_number, os.strerror(error_number), destination_name)


def _sync_published_runtime_output(
    payload_fd: int,
    library_fd: int,
    source_parent_fd: int,
    target_fd: int,
    dfbin_fd: int,
    cache_fd: int,
    expected_library: str,
    evidence: ExtractedFileEvidence,
) -> None:
    """Flush a published runtime file and every held directory commit boundary."""
    validated_fd = _validate_runtime_output_tree(payload_fd, expected_library, evidence)
    try:
        held_state = os.fstat(library_fd)
        validated_state = os.fstat(validated_fd)
        if (
            file_identity(held_state) != evidence.identity
            or mutable_file_state(held_state) != evidence.mutable_state
            or file_identity(validated_state) != evidence.identity
        ):
            raise InstallerError("published runtime library changed before sync")
        os.fsync(library_fd)
    finally:
        os.close(validated_fd)

    # The rename changes both parents. Flush the installed tree first, then the
    # source and destination ancestry from the commit point outward.
    for descriptor in (
        payload_fd,
        source_parent_fd,
        target_fd,
        dfbin_fd,
        cache_fd,
    ):
        os.fsync(descriptor)


def _remove_owned_directory_at(
    parent_fd: int,
    name: str,
    expected_identity: tuple[int, int],
    *,
    directory_fd: int | None = None,
) -> bool:
    """Inspect one held tree but preserve it when conditional deletion is unavailable."""
    close_descriptor = directory_fd is None
    if directory_fd is None:
        try:
            directory_fd = os.open(name, _directory_open_flags(), dir_fd=parent_fd)
        except FileNotFoundError:
            return True
        except OSError:
            return False
    try:
        opened = os.fstat(directory_fd)
        if (
            not stat.S_ISDIR(opened.st_mode)
            or file_identity(opened) != expected_identity
        ):
            return False
        # No portable removal can be conditioned on the held identity. Since
        # every reachable leaf and directory must therefore be retained, do not
        # recursively inventory an attacker-controlled recovery tree.
        return False
    finally:
        if close_descriptor:
            os.close(directory_fd)


def _clear_owned_directory_fd(directory_fd: int) -> bool:
    """Preserve a held recovery tree without traversing attacker-controlled entries."""
    _ = directory_fd
    return False


def install(args: InstallArguments) -> Path:
    target = args.target
    feature_set = args.feature_set
    if not SAFE_TARGET.fullmatch(target):
        raise InstallerError(f"invalid target triple: {target!r}")

    distribution = load_distribution(Path(__file__), target, feature_set)
    expected_sha256 = distribution.sha256
    if not SAFE_SHA256.fullmatch(expected_sha256):
        raise InstallerError(
            "manifest archive SHA-256 must be 64 lowercase hexadecimal characters"
        )
    expected_library = distribution.expected_library
    if (
        "\\" in expected_library
        or PurePosixPath(expected_library).name != expected_library
        or expected_library in {".", ".."}
    ):
        raise InstallerError("manifest expected_library must be a root-level filename")

    cache_value = os.environ.get("ORT_CACHE_DIR")
    if not cache_value:
        raise InstallerError("ORT_CACHE_DIR must be set explicitly")
    cache_root = validate_explicit_cache_root(cache_value)

    _require_secure_posix_primitives()
    archive_path = args.archive.expanduser()
    destination = cache_root / "dfbin" / target / expected_sha256
    target_root = destination.parent
    publication_state = RenamePublicationState()
    try:
        with verified_archive_snapshot(
            archive_path, expected_sha256
        ) as archive_snapshot:
            with (
                _secure_cache_root(cache_root) as cache_fd,
                _opened_or_created_directory(
                    cache_fd,
                    "dfbin",
                    mode=CACHE_DIRECTORY_MODE,
                    context="cache",
                ) as dfbin_fd,
                _opened_or_created_directory(
                    dfbin_fd,
                    target,
                    mode=CACHE_DIRECTORY_MODE,
                    context="cache target",
                ) as target_fd,
            ):
                try:
                    _ = os.stat(
                        expected_sha256,
                        dir_fd=target_fd,
                        follow_symlinks=False,
                    )
                except FileNotFoundError:
                    pass
                else:
                    raise InstallerError(
                        "cache destination already exists; refusing to overwrite: "
                        + str(destination)
                    )

                target_identity = file_identity(os.fstat(target_fd))
                dictionary_bytes = distribution.dictionary_bytes
                prefix = f".install-{expected_sha256}-"
                with _private_staging_directory(target_fd, prefix) as (
                    _,
                    temporary_fd,
                ):
                    library_fd = -1
                    installed_fd = -1
                    try:
                        with decompressed_tar_snapshot(
                            archive_snapshot,
                            Path("archive.tar"),
                            dictionary_bytes,
                            destination_dir_fd=temporary_fd,
                        ) as tar_snapshot:
                            tar_input = tar_snapshot.file
                            with _opened_or_created_directory(
                                temporary_fd,
                                "payload",
                                mode=PRIVATE_DIRECTORY_MODE,
                                context="staging payload",
                            ) as payload_fd:
                                extracted_files = extract_tar_safely(
                                    Path("archive.tar"),
                                    Path("payload"),
                                    expected_library,
                                    tar_dir_fd=temporary_fd,
                                    staging_dir_fd=payload_fd,
                                    tar_file=tar_input,
                                )
                                try:
                                    library_evidence = extracted_files[expected_library]
                                except KeyError as error:
                                    raise InstallerError(
                                        "verified archive is missing expected root library: "
                                        + expected_library
                                    ) from error

                                # The context manager also checks at descriptor close,
                                # but publication must not precede this held-file gate.
                                _assert_decompressed_tar_stable(
                                    tar_input, tar_snapshot.original_state
                                )

                                _ = validate_explicit_cache_root(cache_value)
                                _ = verified_directory_identity(
                                    target_root, target_identity
                                )
                                library_fd = _validate_runtime_output_tree(
                                    payload_fd,
                                    expected_library,
                                    library_evidence,
                                )
                                payload_identity = file_identity(os.fstat(payload_fd))
                                try:
                                    atomic_rename_noreplace(
                                        Path("payload"),
                                        Path(expected_sha256),
                                        source_dir_fd=temporary_fd,
                                        destination_dir_fd=target_fd,
                                        source_identity=payload_identity,
                                        publication_state=publication_state,
                                    )
                                except FileExistsError as error:
                                    detail = (
                                        "cache destination appeared during installation: "
                                        + str(destination)
                                    )
                                    raise InstallerError(
                                        f"{detail}; refusing to overwrite"
                                    ) from error

                                _ = verified_directory_identity(
                                    target_root, target_identity
                                )
                                try:
                                    installed_fd = os.open(
                                        expected_sha256,
                                        _directory_open_flags(),
                                        dir_fd=target_fd,
                                    )
                                except OSError as error:
                                    raise InstallerError(
                                        "published runtime output changed during installation"
                                    ) from error
                                installed_state = os.fstat(installed_fd)
                                if (
                                    not stat.S_ISDIR(installed_state.st_mode)
                                    or file_identity(installed_state)
                                    != payload_identity
                                ):
                                    raise InstallerError(
                                        "published runtime output changed during installation"
                                    )
                                _sync_published_runtime_output(
                                    installed_fd,
                                    library_fd,
                                    temporary_fd,
                                    target_fd,
                                    dfbin_fd,
                                    cache_fd,
                                    expected_library,
                                    library_evidence,
                                )
                    finally:
                        if installed_fd >= 0:
                            os.close(installed_fd)
                        if library_fd >= 0:
                            os.close(library_fd)
    except InstallDurabilityUnknown:
        raise
    except Exception as error:
        if publication_state.renamed:
            raise InstallDurabilityUnknown(destination) from error
        raise

    return destination


def main() -> int:
    try:
        destination = install(parse_args())
    except (
        InstallerError,
        OSError,
        lzma.LZMAError,
        tarfile.TarError,
        tomllib.TOMLDecodeError,
    ) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    _ = print(f"Installed verified ONNX Runtime archive at {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
