#!/usr/bin/env python3
# pyright: reportImplicitOverride=false
"""Behavior tests for the checksum-gated ort-sys runtime cache installer."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Iterator
from contextlib import contextmanager
import hashlib
import importlib.util
import io
import lzma
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
from typing import Any, BinaryIO, Protocol, cast, final
import unittest
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALLER = REPO_ROOT / "scripts" / "install-ort-runtime.py"
RUNTIME_VERSION_DIR = Path("runtime/ort-sys-2.0.0-rc.13")
TARGET = "x86_64-unknown-linux-gnu"
FEATURE_SET = "none"
EXPECTED_LIBRARY = "libonnxruntime.a"
LZMA2_FILTERS = [{"id": lzma.FILTER_LZMA2, "dict_size": 1 << 26}]
ORT_SYS_SOURCE_COMMIT = "002f41a8e175eac7f6695ff361d2e51a50874c48"
ORT_SYS_DIST_SHA256 = "c706a8bf67367fbec3ad7851d9b119f8830fbabe53696e20f4740131f7f59e78"
LINUX_REVIEWED_SHA256 = (
    "e454f710f8a49f53aa5b4ff51e3454ae1835777e431c6c35c5255ce6f205fd68"
)


def build_archive(path: Path, members: dict[str, bytes]) -> str:
    """Build the same tar + raw LZMA2 envelope used by Pyke distributions."""
    tar_buffer = io.BytesIO()
    with tarfile.open(fileobj=tar_buffer, mode="w") as archive:
        for name, content in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))

    encoded = lzma.compress(
        tar_buffer.getvalue(),
        format=lzma.FORMAT_RAW,
        filters=LZMA2_FILTERS,
    )
    _ = path.write_bytes(encoded)
    return hashlib.sha256(encoded).hexdigest()


def build_archive_entries(
    path: Path, entries: list[tuple[tarfile.TarInfo, bytes | None]]
) -> str:
    """Build an archive from explicit entries, including duplicate names."""
    tar_buffer = io.BytesIO()
    with tarfile.open(fileobj=tar_buffer, mode="w") as archive:
        for info, content in entries:
            archive.addfile(info, None if content is None else io.BytesIO(content))
    encoded = lzma.compress(
        tar_buffer.getvalue(),
        format=lzma.FORMAT_RAW,
        filters=LZMA2_FILTERS,
    )
    _ = path.write_bytes(encoded)
    return hashlib.sha256(encoded).hexdigest()


class InstallerModule(Protocol):
    """Typed surface used from the dynamically loaded installer module."""

    InstallerError: type[Exception]
    InstallDurabilityUnknown: type[Exception]
    decompress_raw_lzma2: Callable[[BinaryIO, Path, int], None]
    extract_tar_safely: Callable[[Path, Path, str | None], Any]
    install: Callable[[argparse.Namespace], Path]
    iter_decompressed_chunks: Callable[[BinaryIO, int], Iterator[bytes]]
    load_distribution: Callable[[Path, str, str], Any]
    verified_archive_snapshot: Callable[[Path, str], Any]
    tarfile: Any
    atomic_rename_noreplace: Any
    safe_member_path: Callable[[str], Any]
    tempfile: Any


@final
class InstallOrtRuntimeTests(unittest.TestCase):
    def __init__(self, methodName: str = "runTest") -> None:
        super().__init__(methodName)
        self.temp_dir: tempfile.TemporaryDirectory[str] | None = None
        self.root: Path = Path()
        self.repo: Path = Path()
        self.script: Path = Path()
        self.cache: Path = Path()
        self.archive: Path = Path()

    def setUp(self) -> None:
        self.assertTrue(INSTALLER.is_file(), f"installer missing: {INSTALLER}")
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.repo = self.root / "repo"
        (self.repo / "scripts").mkdir(parents=True)
        (self.repo / RUNTIME_VERSION_DIR).mkdir(parents=True)
        _ = shutil.copy2(INSTALLER, self.repo / "scripts/install-ort-runtime.py")
        self.script = self.repo / "scripts/install-ort-runtime.py"
        self.cache = self.root / "ort-cache"
        self.archive = self.root / "runtime.tar.lzma2"

    def tearDown(self) -> None:
        if self.temp_dir is not None:
            self.temp_dir.cleanup()

    def write_manifest(self, sha256: str) -> None:
        manifest = (REPO_ROOT / RUNTIME_VERSION_DIR / "manifest.toml").read_text(
            encoding="utf-8"
        )
        manifest = manifest.replace(LINUX_REVIEWED_SHA256, sha256)
        _ = (self.repo / RUNTIME_VERSION_DIR / "manifest.toml").write_text(
            manifest, encoding="utf-8"
        )
        installer = self.script.read_text(encoding="utf-8")
        self.script.write_text(
            installer.replace(LINUX_REVIEWED_SHA256, sha256), encoding="utf-8"
        )

    def run_installer(
        self,
        *,
        archive: Path | None = None,
        target: str = TARGET,
        feature_set: str = FEATURE_SET,
        cache: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        if cache is not None:
            env["ORT_CACHE_DIR"] = str(cache)
        else:
            _ = env.pop("ORT_CACHE_DIR", None)
        return subprocess.run(
            [
                "python3",
                str(self.script),
                "--archive",
                str(archive or self.archive),
                "--target",
                target,
                "--feature-set",
                feature_set,
            ],
            cwd=self.repo,
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )

    def load_installer_module(self) -> InstallerModule:
        module_name = f"_test_ort_installer_{id(self)}_{len(sys.modules)}"
        spec = importlib.util.spec_from_file_location(module_name, self.script)
        if spec is None or spec.loader is None:
            self.fail("could not load copied installer module")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
        except BaseException:
            _ = sys.modules.pop(module_name, None)
            raise
        self.addCleanup(sys.modules.pop, module_name, None)
        return cast(InstallerModule, cast(object, module))

    def test_verified_archive_installs_at_ort_sys_target_hash_path(self) -> None:
        # Catches extracting to a convenient path instead of ort-sys's exact dfbin path.
        content = b"verified ONNX Runtime static library"
        sha256 = build_archive(self.archive, {EXPECTED_LIBRARY: content})
        self.write_manifest(sha256)

        result = self.run_installer(cache=self.cache)

        destination = self.cache / "dfbin" / TARGET / sha256
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((destination / EXPECTED_LIBRARY).read_bytes(), content)

    @unittest.skipIf(os.name == "nt", "descriptor-relative install is POSIX-only")
    def test_postpublication_sync_failure_preserves_runtime_for_recovery(self) -> None:
        # Catches reporting success or deleting the only visible output after its
        # publication commit point when crash durability cannot be confirmed.
        content = b"verified ONNX Runtime static library"
        sha256 = build_archive(self.archive, {EXPECTED_LIBRARY: content})
        self.write_manifest(sha256)
        installer = self.load_installer_module()
        implementation = cast(Any, installer)
        original_rename = installer.atomic_rename_noreplace
        real_fsync = os.fsync
        published = False

        def publish_then_mark(*args: Any, **kwargs: Any) -> None:
            nonlocal published
            original_rename(*args, **kwargs)
            published = True

        def fail_after_publication(descriptor: int) -> None:
            if published:
                raise OSError("injected runtime postpublication sync failure")
            real_fsync(descriptor)

        args = argparse.Namespace(
            archive=self.archive,
            target=TARGET,
            feature_set=FEATURE_SET,
        )
        with (
            mock.patch.dict(os.environ, {"ORT_CACHE_DIR": str(self.cache)}),
            mock.patch.object(
                installer,
                "atomic_rename_noreplace",
                side_effect=publish_then_mark,
            ),
            mock.patch.object(
                implementation.os, "fsync", side_effect=fail_after_publication
            ),
            self.assertRaisesRegex(
                installer.InstallDurabilityUnknown,
                "installed but durability is unknown",
            ),
        ):
            _ = installer.install(args)

        destination = self.cache / "dfbin" / TARGET / sha256
        self.assertEqual((destination / EXPECTED_LIBRARY).read_bytes(), content)

    @unittest.skipIf(os.name == "nt", "descriptor-relative install is POSIX-only")
    def test_postpublication_runtime_validation_error_is_durability_unknown(
        self,
    ) -> None:
        # Catches a post-rename InstallerError bypassing the durability-unknown
        # classification and making a visible output look safe to retry.
        content = b"verified ONNX Runtime static library"
        sha256 = build_archive(self.archive, {EXPECTED_LIBRARY: content})
        self.write_manifest(sha256)
        installer = self.load_installer_module()
        implementation = cast(Any, installer)
        args = argparse.Namespace(
            archive=self.archive,
            target=TARGET,
            feature_set=FEATURE_SET,
        )
        original_rename = installer.atomic_rename_noreplace
        original_verify = implementation.verified_directory_identity
        published = False

        def publish_then_mark(*args: Any, **kwargs: Any) -> None:
            nonlocal published
            original_rename(*args, **kwargs)
            published = True

        def reject_postpublication_directory(
            path: Path, expected: tuple[int, int] | None = None
        ) -> tuple[int, int]:
            if published:
                raise installer.InstallerError(
                    "cache directory changed during installation"
                )
            return original_verify(path, expected)

        with (
            mock.patch.dict(os.environ, {"ORT_CACHE_DIR": str(self.cache)}),
            mock.patch.object(
                implementation, "atomic_rename_noreplace", side_effect=publish_then_mark
            ),
            mock.patch.object(
                implementation,
                "verified_directory_identity",
                side_effect=reject_postpublication_directory,
            ),
            self.assertRaisesRegex(
                installer.InstallDurabilityUnknown,
                "installed but durability is unknown",
            ),
        ):
            _ = installer.install(args)

        destination = self.cache / "dfbin" / TARGET / sha256
        self.assertEqual((destination / EXPECTED_LIBRARY).read_bytes(), content)

    @unittest.skipIf(os.name == "nt", "descriptor-relative install is POSIX-only")
    def test_atomic_helper_postrename_failure_is_durability_unknown(self) -> None:
        # Catches the rename helper committing output and then raising before the
        # caller can otherwise learn that publication already happened.
        content = b"verified ONNX Runtime static library"
        sha256 = build_archive(self.archive, {EXPECTED_LIBRARY: content})
        self.write_manifest(sha256)
        installer = self.load_installer_module()
        implementation = cast(Any, installer)
        real_stat = implementation.os.stat
        failed_inside_helper = False

        def fail_destination_validation(
            path: Any, *stat_args: Any, **stat_kwargs: Any
        ) -> os.stat_result:
            nonlocal failed_inside_helper
            state = real_stat(path, *stat_args, **stat_kwargs)
            if os.fspath(path) == sha256 and stat_kwargs.get("dir_fd") is not None:
                failed_inside_helper = True
                raise installer.InstallerError(
                    "injected helper post-rename validation failure"
                )
            return state

        args = argparse.Namespace(
            archive=self.archive,
            target=TARGET,
            feature_set=FEATURE_SET,
        )
        with (
            mock.patch.dict(os.environ, {"ORT_CACHE_DIR": str(self.cache)}),
            mock.patch.object(
                implementation,
                "_require_secure_posix_primitives",
                return_value=None,
            ),
            mock.patch.object(
                implementation.os,
                "stat",
                side_effect=fail_destination_validation,
            ),
        ):
            with self.assertRaises(installer.InstallerError) as caught:
                _ = installer.install(args)

        self.assertIsInstance(caught.exception, installer.InstallDurabilityUnknown)
        self.assertIn("installed but durability is unknown", str(caught.exception))
        self.assertTrue(failed_inside_helper)

        destination = self.cache / "dfbin" / TARGET / sha256
        self.assertEqual((destination / EXPECTED_LIBRARY).read_bytes(), content)

    @unittest.skipIf(os.name == "nt", "descriptor-relative install is POSIX-only")
    def test_postpublication_decompression_context_failure_is_durability_unknown(
        self,
    ) -> None:
        # Catches a post-yield context-manager check escaping after the rename
        # commit point as an ordinary retry-safe installer error.
        content = b"verified ONNX Runtime static library"
        sha256 = build_archive(self.archive, {EXPECTED_LIBRARY: content})
        self.write_manifest(sha256)
        installer = self.load_installer_module()
        implementation = cast(Any, installer)
        original_assert = implementation._assert_decompressed_tar_stable
        checks = 0

        def fail_second_stability_check(*args: Any, **kwargs: Any) -> None:
            nonlocal checks
            checks += 1
            if checks == 2:
                raise installer.InstallerError(
                    "injected decompression context-exit failure"
                )
            original_assert(*args, **kwargs)

        args = argparse.Namespace(
            archive=self.archive,
            target=TARGET,
            feature_set=FEATURE_SET,
        )
        with (
            mock.patch.dict(os.environ, {"ORT_CACHE_DIR": str(self.cache)}),
            mock.patch.object(
                implementation,
                "_assert_decompressed_tar_stable",
                side_effect=fail_second_stability_check,
            ),
        ):
            with self.assertRaises(installer.InstallerError) as caught:
                _ = installer.install(args)

        self.assertIsInstance(caught.exception, installer.InstallDurabilityUnknown)
        self.assertIn("installed but durability is unknown", str(caught.exception))

        destination = self.cache / "dfbin" / TARGET / sha256
        self.assertEqual((destination / EXPECTED_LIBRARY).read_bytes(), content)

    def test_checksum_mismatch_fails_before_creating_cache(self) -> None:
        # Catches writes occurring before the authoritative archive checksum passes.
        _ = build_archive(self.archive, {EXPECTED_LIBRARY: b"wrong archive"})
        self.write_manifest("0" * 64)

        result = self.run_installer(cache=self.cache)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("checksum mismatch", result.stderr.lower())
        self.assertFalse(self.cache.exists())

    def test_missing_ort_cache_dir_is_rejected(self) -> None:
        # Catches silently falling back to a platform cache outside explicit operator scope.
        sha256 = build_archive(self.archive, {EXPECTED_LIBRARY: b"runtime"})
        self.write_manifest(sha256)

        result = self.run_installer(cache=None)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ORT_CACHE_DIR", result.stderr)

    def test_distribution_manifest_rejects_schema_and_rc13_tuple_mutations(
        self,
    ) -> None:
        # Catches accepting plausible but unaudited metadata or fields the installer ignores.
        sha256 = build_archive(self.archive, {EXPECTED_LIBRARY: b"runtime"})
        self.write_manifest(sha256)
        canonical = (self.repo / RUNTIME_VERSION_DIR / "manifest.toml").read_text(
            encoding="utf-8"
        )
        mutations = {
            "top-level schema": canonical.replace(
                "[meta]",
                'unexpected_top_level = "value"\n\n[meta]',
                1,
            ),
            "meta schema": canonical.replace(
                'component = "onnxruntime-native-static"',
                'component = "onnxruntime-native-static"\nunexpected_meta = "value"',
            ),
            "archive schema": canonical.replace(
                'platform = "Linux x86_64"',
                'platform = "Linux x86_64"\nunexpected_row = "value"',
            ),
            "ort-sys version": canonical.replace("2.0.0-rc.13", "2.0.0-rc.14"),
            "ort-sys source commit": canonical.replace(ORT_SYS_SOURCE_COMMIT, "f" * 40),
            "ort-sys dist digest": canonical.replace(ORT_SYS_DIST_SHA256, "f" * 64),
            "ONNX Runtime version": canonical.replace("1.28.0", "1.29.0"),
            "Pyke source": canonical.replace("cdn.pyke.io", "example.invalid"),
            "dictionary": canonical.replace("67108864", "33554432"),
        }
        manifest_path = self.repo / RUNTIME_VERSION_DIR / "manifest.toml"
        installer = self.load_installer_module()
        for label, mutated in mutations.items():
            with self.subTest(label=label):
                _ = manifest_path.write_text(mutated, encoding="utf-8")
                with self.assertRaisesRegex(installer.InstallerError, label):
                    _ = installer.load_distribution(
                        self.script,
                        TARGET,
                        FEATURE_SET,
                    )

    def test_distribution_requires_exact_four_reviewed_runtime_records(self) -> None:
        # Catches installer consumption accepting a self-consistent but unreviewed
        # required runtime map, including missing/extra and ABI-library mutations.
        sha256 = build_archive(self.archive, {EXPECTED_LIBRARY: b"runtime"})
        self.write_manifest(sha256)
        canonical = (self.repo / RUNTIME_VERSION_DIR / "manifest.toml").read_text(
            encoding="utf-8"
        )
        first_source = "x86_64-unknown-linux-gnu.tar.lzma2"
        second_source = "aarch64-unknown-linux-gnu.tar.lzma2"
        marker = "\n[[archives]]\n"
        first_start = canonical.index(marker) + 1
        second_start = canonical.index(marker, first_start + len(marker)) + 1
        third_start = canonical.index(marker, second_start + len(marker)) + 1
        first_block = canonical[first_start:second_start]
        mutations = {
            "runtime version": canonical.replace("1.28.0", "1.29.0"),
            "target source swap": canonical.replace(first_source, "__SOURCE_A__")
            .replace(second_source, first_source)
            .replace("__SOURCE_A__", second_source),
            "missing row": canonical[:second_start] + canonical[third_start:],
            "extra row": canonical.replace(
                "\n[[future_archives]]\n",
                "\n" + first_block + "[[future_archives]]\n",
                1,
            ),
            "library mismatch": canonical.replace(
                'expected_library = "libonnxruntime.a"',
                'expected_library = "onnxruntime.lib"',
                1,
            ),
        }
        manifest_path = self.repo / RUNTIME_VERSION_DIR / "manifest.toml"
        installer = self.load_installer_module()
        for label, mutated in mutations.items():
            with self.subTest(label=label):
                manifest_path.write_text(mutated, encoding="utf-8")
                with self.assertRaises(installer.InstallerError):
                    installer.load_distribution(self.script, TARGET, FEATURE_SET)

    def test_distribution_manifest_read_is_bounded_regular_file_snapshot(self) -> None:
        # Catches tomllib.load/read-all consumption before size, regular-file, and
        # identity checks establish one immutable manifest view.
        sha256 = build_archive(self.archive, {EXPECTED_LIBRARY: b"runtime"})
        self.write_manifest(sha256)
        installer = self.load_installer_module()

        class RejectingSnapshot(io.BytesIO):
            def write(self, data: Any, /) -> int:
                raise AssertionError("oversized manifest reached snapshot storage")

        with (
            mock.patch.object(
                cast(Any, installer), "MAX_MANIFEST_BYTES", 1, create=True
            ),
            mock.patch.object(
                installer.tempfile,
                "TemporaryFile",
                return_value=RejectingSnapshot(),
            ),
            self.assertRaisesRegex(installer.InstallerError, "manifest.*size limit"),
        ):
            installer.load_distribution(self.script, TARGET, FEATURE_SET)

    @unittest.skipIf(os.name == "nt", "POSIX FIFOs are not available")
    def test_distribution_manifest_fifo_is_rejected_without_blocking_open(self) -> None:
        installer = self.load_installer_module()
        manifest_path = self.repo / RUNTIME_VERSION_DIR / "manifest.toml"
        os.mkfifo(manifest_path)
        real_open = os.open

        def require_nonblocking_open(
            path: Any, flags: int, *args: Any, **kwargs: Any
        ) -> int:
            if Path(path) == manifest_path and not flags & os.O_NONBLOCK:
                raise AssertionError("manifest FIFO reached a blocking open")
            return real_open(path, flags, *args, **kwargs)

        with (
            mock.patch.object(
                cast(Any, installer).os,
                "open",
                side_effect=require_nonblocking_open,
            ),
            self.assertRaisesRegex(installer.InstallerError, "regular file"),
        ):
            installer.load_distribution(self.script, TARGET, FEATURE_SET)

    def test_cache_root_rejects_lexical_alias_and_symlink_ancestor(self) -> None:
        sha256 = build_archive(self.archive, {EXPECTED_LIBRARY: b"runtime"})
        self.write_manifest(sha256)
        aliased = self.root / "missing" / ".." / "ort-cache"

        alias_result = self.run_installer(cache=aliased)

        self.assertNotEqual(alias_result.returncode, 0)
        self.assertIn("canonical", alias_result.stderr.lower())
        referent = self.root / "real-cache"
        referent.mkdir()
        symlink = self.root / "cache-link"
        symlink.symlink_to(referent, target_is_directory=True)

        symlink_result = self.run_installer(cache=symlink)

        self.assertNotEqual(symlink_result.returncode, 0)
        self.assertIn("symlink", symlink_result.stderr.lower())
        self.assertEqual(list(referent.iterdir()), [])

    @unittest.skipIf(os.name == "nt", "POSIX double-slash roots are not applicable")
    def test_cache_root_rejects_posix_double_slash_alias(self) -> None:
        sha256 = build_archive(self.archive, {EXPECTED_LIBRARY: b"runtime"})
        self.write_manifest(sha256)
        double_slash = Path("//" + str(self.cache).lstrip("/"))

        result = self.run_installer(cache=double_slash)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("canonical", result.stderr.lower())
        self.assertFalse(self.cache.exists())

    def test_cache_root_rejects_derived_dfbin_symlink(self) -> None:
        sha256 = build_archive(self.archive, {EXPECTED_LIBRARY: b"runtime"})
        self.write_manifest(sha256)
        self.cache.mkdir()
        outside = self.root / "outside"
        outside.mkdir()
        (self.cache / "dfbin").symlink_to(outside, target_is_directory=True)

        result = self.run_installer(cache=self.cache)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("symlink", result.stderr.lower())
        self.assertEqual(list(outside.iterdir()), [])

    def test_compressed_archive_size_is_bounded_before_snapshot_copy(self) -> None:
        sha256 = build_archive(self.archive, {EXPECTED_LIBRARY: b"runtime"})
        self.write_manifest(sha256)
        installer = self.load_installer_module()
        args = argparse.Namespace(
            archive=self.archive,
            target=TARGET,
            feature_set=FEATURE_SET,
        )
        with (
            mock.patch.dict(os.environ, {"ORT_CACHE_DIR": str(self.cache)}),
            mock.patch.object(
                cast(Any, installer),
                "MAX_COMPRESSED_BYTES",
                self.archive.stat().st_size - 1,
            ),
        ):
            with self.assertRaisesRegex(installer.InstallerError, "compressed.*limit"):
                _ = installer.install(args)

        self.assertFalse(self.cache.exists())

    def test_archive_path_traversal_is_rejected_without_escape(self) -> None:
        # Catches an archive member escaping the temporary extraction directory.
        sha256 = build_archive(
            self.archive,
            {EXPECTED_LIBRARY: b"runtime", "../../escape": b"escaped"},
        )
        self.write_manifest(sha256)

        result = self.run_installer(cache=self.cache)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unsafe archive member", result.stderr.lower())
        self.assertFalse((self.root / "escape").exists())
        self.assertFalse((self.cache / "dfbin" / TARGET / sha256).exists())

    def test_windows_style_path_traversal_is_rejected(self) -> None:
        # Catches a backslash path becoming traversal when the installer runs on Windows.
        sha256 = build_archive(
            self.archive,
            {EXPECTED_LIBRARY: b"runtime", "..\\escape": b"escaped"},
        )
        self.write_manifest(sha256)

        result = self.run_installer(cache=self.cache)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unsafe archive member", result.stderr.lower())
        self.assertFalse((self.cache / "dfbin" / TARGET / sha256).exists())

    def test_noncanonical_posix_archive_member_aliases_are_rejected(self) -> None:
        installer = self.load_installer_module()

        for member_name in (f"./{EXPECTED_LIBRARY}", f"dir//{EXPECTED_LIBRARY}"):
            with self.subTest(member_name=member_name):
                with self.assertRaisesRegex(
                    installer.InstallerError, "unsafe archive member"
                ):
                    _ = installer.safe_member_path(member_name)

    def test_duplicate_archive_member_is_rejected(self) -> None:
        first = tarfile.TarInfo(EXPECTED_LIBRARY)
        first.size = 3
        duplicate = tarfile.TarInfo(EXPECTED_LIBRARY)
        duplicate.size = 3
        sha256 = build_archive_entries(
            self.archive,
            [(first, b"one"), (duplicate, b"two")],
        )
        self.write_manifest(sha256)

        result = self.run_installer(cache=self.cache)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("duplicate", result.stderr.lower())

    def test_archive_inventory_rejects_every_unexpected_file(self) -> None:
        sha256 = build_archive(
            self.archive,
            {EXPECTED_LIBRARY: b"runtime", "README.txt": b"unexpected"},
        )
        self.write_manifest(sha256)

        result = self.run_installer(cache=self.cache)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("inventory", result.stderr.lower())
        self.assertFalse((self.cache / "dfbin" / TARGET / sha256).exists())

    def test_archive_member_count_and_logical_sizes_are_bounded(self) -> None:
        installer = self.load_installer_module()
        unused_tar = self.root / "unused.tar"
        _ = unused_tar.write_bytes(b"")
        safe = tarfile.TarInfo(EXPECTED_LIBRARY)
        safe.size = 1
        too_many = [tarfile.TarInfo(f"member-{index}") for index in range(129)]
        oversized = tarfile.TarInfo(EXPECTED_LIBRARY)
        oversized.size = (2 * 1024 * 1024 * 1024) + 1
        cumulative_a = tarfile.TarInfo(EXPECTED_LIBRARY)
        cumulative_a.size = 2 * 1024 * 1024 * 1024
        cumulative_b = tarfile.TarInfo("second.lib")
        cumulative_b.size = 2 * 1024 * 1024 * 1024
        cumulative_c = tarfile.TarInfo("third.lib")
        cumulative_c.size = 1

        for members, message in (
            (too_many, "member count"),
            ([oversized], "member size"),
            ([cumulative_a, cumulative_b, cumulative_c], "total"),
        ):
            fake_archive = mock.MagicMock()
            fake_archive.__enter__.return_value = fake_archive
            fake_archive.__iter__.side_effect = lambda members=members: iter(members)
            with (
                mock.patch.object(
                    cast(Any, installer.tarfile), "open", return_value=fake_archive
                ),
                mock.patch.object(
                    cast(Any, installer),
                    "_prevalidate_raw_tar_headers",
                    return_value=None,
                ),
            ):
                with self.assertRaisesRegex(installer.InstallerError, message):
                    installer.extract_tar_safely(
                        unused_tar, self.root, EXPECTED_LIBRARY
                    )

    def test_archive_member_cap_stops_stream_before_materializing_all_headers(
        self,
    ) -> None:
        installer = self.load_installer_module()
        yielded = 0
        unused_tar = self.root / "unused.tar"
        _ = unused_tar.write_bytes(b"")

        def member_stream() -> Iterator[tarfile.TarInfo]:
            nonlocal yielded
            for index in range(1024):
                yielded += 1
                member = tarfile.TarInfo(f"directory-{index}")
                member.type = tarfile.DIRTYPE
                yield member

        fake_archive = mock.MagicMock()
        fake_archive.__enter__.return_value = fake_archive
        fake_archive.__iter__.side_effect = member_stream
        fake_archive.getmembers.side_effect = AssertionError(
            "getmembers() would materialize the complete untrusted archive"
        )
        with (
            mock.patch.object(
                cast(Any, installer.tarfile), "open", return_value=fake_archive
            ),
            mock.patch.object(
                cast(Any, installer), "_prevalidate_raw_tar_headers", return_value=None
            ),
        ):
            with self.assertRaisesRegex(installer.InstallerError, "member count"):
                installer.extract_tar_safely(unused_tar, self.root, None)

        self.assertEqual(yielded, 129)
        fake_archive.getmembers.assert_not_called()

    def test_oversized_pax_and_gnu_extensions_are_rejected_before_large_read(
        self,
    ) -> None:
        # Catches tarfile reading an extension payload before normal member counters run.
        installer = self.load_installer_module()

        class GuardedTar(io.BytesIO):
            def __init__(self, content: bytes) -> None:
                super().__init__(content)
                self.read_sizes: list[int | None] = []

            def read(self, size: int | None = -1) -> bytes:
                self.read_sizes.append(size)
                if size is not None and size >= 64 * 1024 * 1024:
                    raise AssertionError(f"oversized pre-counter read: {size}")
                return super().read(size)

        staging = self.root / "staging"
        staging.mkdir()
        staging_fd = os.open(staging, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            for extension_type in (tarfile.XHDTYPE, tarfile.GNUTYPE_LONGNAME):
                with self.subTest(extension_type=extension_type):
                    header = tarfile.TarInfo("extension")
                    header.type = extension_type
                    header.size = 64 * 1024 * 1024
                    guarded = GuardedTar(header.tobuf(format=tarfile.USTAR_FORMAT))
                    with self.assertRaisesRegex(
                        installer.InstallerError,
                        "archive extension size",
                    ):
                        cast(Any, installer)._extract_tar_stream_safely(
                            guarded,
                            staging_fd,
                            EXPECTED_LIBRARY,
                        )
                    self.assertNotIn(64 * 1024 * 1024, guarded.read_sizes)
        finally:
            os.close(staging_fd)

    def test_sparse_archive_member_is_rejected(self) -> None:
        installer = self.load_installer_module()
        unused_tar = self.root / "unused.tar"
        _ = unused_tar.write_bytes(b"")
        sparse = tarfile.TarInfo(EXPECTED_LIBRARY)
        sparse.size = 1
        setattr(cast(Any, sparse), "sparse", [(0, 1)])
        fake_archive = mock.MagicMock()
        fake_archive.__enter__.return_value = fake_archive
        fake_archive.__iter__.side_effect = lambda: iter([sparse])
        with (
            mock.patch.object(
                cast(Any, installer.tarfile), "open", return_value=fake_archive
            ),
            mock.patch.object(
                cast(Any, installer), "_prevalidate_raw_tar_headers", return_value=None
            ),
        ):
            with self.assertRaisesRegex(installer.InstallerError, "sparse"):
                installer.extract_tar_safely(unused_tar, self.root, EXPECTED_LIBRARY)

    def test_raw_tar_rejects_nonzero_bytes_after_end_marker(self) -> None:
        # Catches accepting attacker bytes hidden after otherwise valid tar zero padding.
        tar_buffer = io.BytesIO()
        with tarfile.open(fileobj=tar_buffer, mode="w") as archive:
            info = tarfile.TarInfo(EXPECTED_LIBRARY)
            content = b"runtime"
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))
        encoded = lzma.compress(
            tar_buffer.getvalue() + b"attacker",
            format=lzma.FORMAT_RAW,
            filters=LZMA2_FILTERS,
        )
        self.archive.write_bytes(encoded)
        self.write_manifest(hashlib.sha256(encoded).hexdigest())

        result = self.run_installer(cache=self.cache)

        self.assertNotEqual(result.returncode, 0)
        self.assertRegex(result.stderr.lower(), "tar.*trailing|padding")
        digest = hashlib.sha256(encoded).hexdigest()
        self.assertFalse((self.cache / "dfbin" / TARGET / digest).exists())

    def test_existing_cache_entry_is_never_overwritten(self) -> None:
        # Catches a reinstall replacing an entry that ort-sys already trusts by directory existence.
        sha256 = build_archive(self.archive, {EXPECTED_LIBRARY: b"new runtime"})
        self.write_manifest(sha256)
        destination = self.cache / "dfbin" / TARGET / sha256
        destination.mkdir(parents=True)
        sentinel = destination / EXPECTED_LIBRARY
        _ = sentinel.write_bytes(b"existing runtime")

        result = self.run_installer(cache=self.cache)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("already exists", result.stderr.lower())
        self.assertEqual(sentinel.read_bytes(), b"existing runtime")

    def test_raw_lzma2_decompression_uses_bounded_output_chunks(self) -> None:
        # Catches one small compressed input chunk expanding into one huge allocation.
        installer = self.load_installer_module()
        content = b"x" * ((2 * 1024 * 1024) + 17)
        encoded = lzma.compress(
            content,
            format=lzma.FORMAT_RAW,
            filters=LZMA2_FILTERS,
        )

        chunks = list(installer.iter_decompressed_chunks(io.BytesIO(encoded), 1 << 26))

        self.assertGreater(len(chunks), 2)
        self.assertLessEqual(max(map(len, chunks)), 1024 * 1024)
        self.assertEqual(b"".join(chunks), content)

    def test_archive_path_swap_after_checksum_cannot_change_extracted_bytes(
        self,
    ) -> None:
        # Catches hashing one pathname lookup and extracting from a later attacker-swapped lookup.
        original_content = b"verified immutable runtime"
        malicious_content = b"swapped runtime"
        sha256 = build_archive(self.archive, {EXPECTED_LIBRARY: original_content})
        malicious = self.root / "malicious.tar.lzma2"
        _ = build_archive(malicious, {EXPECTED_LIBRARY: malicious_content})
        self.write_manifest(sha256)
        installer = self.load_installer_module()
        original_decompress = cast(Any, installer).decompressed_tar_snapshot

        @contextmanager
        def swap_then_decompress(
            source: BinaryIO,
            destination: Path,
            dictionary_bytes: int,
            *,
            destination_dir_fd: int | None = None,
        ) -> Iterator[BinaryIO]:
            os.replace(malicious, self.archive)
            with original_decompress(
                source,
                destination,
                dictionary_bytes,
                destination_dir_fd=destination_dir_fd,
            ) as tar_input:
                yield tar_input

        args = argparse.Namespace(
            archive=self.archive,
            target=TARGET,
            feature_set=FEATURE_SET,
        )
        with (
            mock.patch.dict(os.environ, {"ORT_CACHE_DIR": str(self.cache)}),
            mock.patch.object(
                installer,
                "decompressed_tar_snapshot",
                side_effect=swap_then_decompress,
            ),
        ):
            destination = installer.install(args)

        installed = (destination / EXPECTED_LIBRARY).read_bytes()
        self.assertEqual(installed, original_content)

    @unittest.skipIf(os.name == "nt", "descriptor-relative install is POSIX-only")
    def test_decompressed_tar_is_not_reopened_by_name_before_extraction(self) -> None:
        # Catches verifying a decompressed tar descriptor, then extracting a path replacement.
        trusted = b"verified immutable runtime"
        malicious = b"swapped runtime"
        sha256 = build_archive(self.archive, {EXPECTED_LIBRARY: trusted})
        self.write_manifest(sha256)
        installer = self.load_installer_module()
        real_open = cast(Any, installer).os.open
        real_extract = cast(Any, installer)._extract_tar_stream_safely
        swapped = False
        extraction_started = False

        malicious_tar = io.BytesIO()
        with tarfile.open(fileobj=malicious_tar, mode="w") as archive:
            info = tarfile.TarInfo(EXPECTED_LIBRARY)
            info.size = len(malicious)
            archive.addfile(info, io.BytesIO(malicious))

        def swap_on_tar_reopen(path: Any, flags: int, *args: Any, **kwargs: Any) -> int:
            nonlocal swapped
            if (
                os.fspath(path) == "archive.tar"
                and flags & os.O_ACCMODE == os.O_RDONLY
                and not extraction_started
            ):
                swapped = True
                directory_fd = kwargs.get("dir_fd")
                os.rename(
                    "archive.tar",
                    "verified-archive.tar",
                    src_dir_fd=directory_fd,
                    dst_dir_fd=directory_fd,
                )
                replacement_fd = real_open(
                    "archive.tar",
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o600,
                    dir_fd=directory_fd,
                )
                try:
                    os.write(replacement_fd, malicious_tar.getvalue())
                finally:
                    os.close(replacement_fd)
            return real_open(path, flags, *args, **kwargs)

        def mark_extraction_started(*args: Any, **kwargs: Any) -> Any:
            nonlocal extraction_started
            extraction_started = True
            return real_extract(*args, **kwargs)

        args = argparse.Namespace(
            archive=self.archive,
            target=TARGET,
            feature_set=FEATURE_SET,
        )
        with (
            mock.patch.dict(os.environ, {"ORT_CACHE_DIR": str(self.cache)}),
            mock.patch.object(
                cast(Any, installer),
                "_require_secure_posix_primitives",
                return_value=None,
            ),
            mock.patch.object(
                cast(Any, installer).os, "open", side_effect=swap_on_tar_reopen
            ),
            mock.patch.object(
                cast(Any, installer),
                "_extract_tar_stream_safely",
                side_effect=mark_extraction_started,
            ),
        ):
            destination = installer.install(args)

        self.assertFalse(swapped)
        self.assertEqual((destination / EXPECTED_LIBRARY).read_bytes(), trusted)

    def test_decompressed_tar_mutation_is_rejected_before_publication(self) -> None:
        # Catches discovering a held-tar mutation only after its payload is published.
        sha256 = build_archive(self.archive, {EXPECTED_LIBRARY: b"verified runtime"})
        self.write_manifest(sha256)
        installer = self.load_installer_module()
        original_extract = installer.extract_tar_safely
        destination = self.cache / "dfbin" / TARGET / sha256

        def mutate_after_extract(
            tar_path: Path,
            staging: Path,
            expected_library: str | None = None,
            *,
            tar_dir_fd: int | None = None,
            staging_dir_fd: int | None = None,
            tar_file: BinaryIO | None = None,
        ) -> Any:
            evidence = cast(Any, original_extract)(
                tar_path,
                staging,
                expected_library,
                tar_dir_fd=tar_dir_fd,
                staging_dir_fd=staging_dir_fd,
                tar_file=tar_file,
            )
            self.assertIsNotNone(tar_file)
            assert tar_file is not None
            _ = tar_file.seek(0, os.SEEK_END)
            _ = tar_file.write(b"mutated after validation")
            tar_file.flush()
            return evidence

        args = argparse.Namespace(
            archive=self.archive,
            target=TARGET,
            feature_set=FEATURE_SET,
        )
        with (
            mock.patch.dict(os.environ, {"ORT_CACHE_DIR": str(self.cache)}),
            mock.patch.object(
                installer,
                "extract_tar_safely",
                side_effect=mutate_after_extract,
            ),
            self.assertRaisesRegex(
                installer.InstallerError, "decompressed tar changed"
            ),
        ):
            _ = installer.install(args)

        self.assertFalse(destination.exists())

    def test_decompressed_tar_handoff_mutation_is_rejected_before_publication(
        self,
    ) -> None:
        # Catches accepting a new baseline after the decompressor yields its original snapshot.
        sha256 = build_archive(self.archive, {EXPECTED_LIBRARY: b"verified runtime"})
        self.write_manifest(sha256)
        installer = self.load_installer_module()
        original_decompress = cast(Any, installer).decompressed_tar_snapshot
        destination = self.cache / "dfbin" / TARGET / sha256

        @contextmanager
        def mutate_during_handoff(
            source: BinaryIO,
            tar_path: Path,
            dictionary_bytes: int,
            *,
            destination_dir_fd: int | None = None,
        ) -> Iterator[Any]:
            with original_decompress(
                source,
                tar_path,
                dictionary_bytes,
                destination_dir_fd=destination_dir_fd,
            ) as handoff:
                tar_input = getattr(handoff, "file", handoff)
                _ = tar_input.seek(-1, os.SEEK_END)
                final_byte = tar_input.read(1)
                _ = tar_input.seek(-1, os.SEEK_END)
                _ = tar_input.write(final_byte)
                tar_input.flush()
                yield handoff

        args = argparse.Namespace(
            archive=self.archive,
            target=TARGET,
            feature_set=FEATURE_SET,
        )
        with (
            mock.patch.dict(os.environ, {"ORT_CACHE_DIR": str(self.cache)}),
            mock.patch.object(
                installer,
                "decompressed_tar_snapshot",
                side_effect=mutate_during_handoff,
            ),
            self.assertRaisesRegex(
                installer.InstallerError, "decompressed tar changed"
            ),
        ):
            _ = installer.install(args)

        self.assertFalse(destination.exists())

    def test_verified_archive_open_is_nonblocking_and_nofollow(self) -> None:
        # Catches a regular source becoming a FIFO between lstat and open.
        content = b"runtime archive"
        self.archive.write_bytes(content)
        installer = self.load_installer_module()
        observed = 0
        real_open = cast(Any, installer).os.open

        def record_open(path: Any, flags: int, *args: Any, **kwargs: Any) -> int:
            nonlocal observed
            if Path(path) == self.archive:
                observed = flags
            return real_open(path, flags, *args, **kwargs)

        with mock.patch.object(
            cast(Any, installer).os, "open", side_effect=record_open
        ):
            with installer.verified_archive_snapshot(
                self.archive, hashlib.sha256(content).hexdigest()
            ):
                pass

        required = getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        self.assertNotEqual(required, 0)
        self.assertEqual(observed & required, required)

    def test_destination_appearing_during_install_is_not_replaced(self) -> None:
        # Catches POSIX rename replacing an empty directory created after the preflight check.
        sha256 = build_archive(self.archive, {EXPECTED_LIBRARY: b"verified runtime"})
        self.write_manifest(sha256)
        installer = self.load_installer_module()
        original_extract = installer.extract_tar_safely
        destination = self.cache / "dfbin" / TARGET / sha256

        def create_destination_then_extract(
            tar_path: Path,
            staging: Path,
            expected_library: str | None = None,
            *,
            tar_dir_fd: int | None = None,
            staging_dir_fd: int | None = None,
            tar_file: BinaryIO | None = None,
        ) -> Any:
            evidence = cast(Any, original_extract)(
                tar_path,
                staging,
                expected_library,
                tar_dir_fd=tar_dir_fd,
                staging_dir_fd=staging_dir_fd,
                tar_file=tar_file,
            )
            destination.mkdir()
            return evidence

        args = argparse.Namespace(
            archive=self.archive,
            target=TARGET,
            feature_set=FEATURE_SET,
        )
        with (
            mock.patch.dict(os.environ, {"ORT_CACHE_DIR": str(self.cache)}),
            mock.patch.object(
                installer,
                "extract_tar_safely",
                side_effect=create_destination_then_extract,
            ),
        ):
            with self.assertRaisesRegex(installer.InstallerError, "appeared"):
                _ = installer.install(args)

        self.assertTrue(destination.is_dir())
        self.assertEqual(list(destination.iterdir()), [])

    def test_cache_target_root_substitution_is_rejected_before_install(self) -> None:
        sha256 = build_archive(self.archive, {EXPECTED_LIBRARY: b"verified runtime"})
        self.write_manifest(sha256)
        installer = self.load_installer_module()
        original_extract = installer.extract_tar_safely
        target_root = self.cache / "dfbin" / TARGET
        displaced = self.root / "displaced-target-root"

        def substitute_target_root(
            tar_path: Path,
            staging: Path,
            expected_library: str | None = None,
            *,
            tar_dir_fd: int | None = None,
            staging_dir_fd: int | None = None,
            tar_file: BinaryIO | None = None,
        ) -> Any:
            evidence = cast(Any, original_extract)(
                tar_path,
                staging,
                expected_library,
                tar_dir_fd=tar_dir_fd,
                staging_dir_fd=staging_dir_fd,
                tar_file=tar_file,
            )
            target_root.rename(displaced)
            target_root.mkdir()
            return evidence

        args = argparse.Namespace(
            archive=self.archive,
            target=TARGET,
            feature_set=FEATURE_SET,
        )
        with (
            mock.patch.dict(os.environ, {"ORT_CACHE_DIR": str(self.cache)}),
            mock.patch.object(
                installer,
                "extract_tar_safely",
                side_effect=substitute_target_root,
            ),
        ):
            with self.assertRaisesRegex(installer.InstallerError, "changed"):
                _ = installer.install(args)

        self.assertEqual(list(target_root.iterdir()), [])
        self.assertFalse((target_root / sha256).exists())
        retained = list(displaced.iterdir())
        self.assertEqual(len(retained), 1)
        self.assertTrue(retained[0].name.startswith(f".install-{sha256}-"))
        self.assertTrue((retained[0] / "archive.tar").is_file())

    @unittest.skipIf(os.name == "nt", "POSIX directory descriptors are not available")
    def test_payload_substitution_at_publish_is_rejected(self) -> None:
        # Catches publishing a different payload name after validating the held payload fd.
        trusted = b"verified runtime"
        sha256 = build_archive(self.archive, {EXPECTED_LIBRARY: trusted})
        self.write_manifest(sha256)
        installer = self.load_installer_module()
        original_rename = installer.atomic_rename_noreplace
        malicious = b"attacker runtime"

        def substitute_then_rename(
            source: Path,
            destination: Path,
            *,
            source_dir_fd: int | None = None,
            destination_dir_fd: int | None = None,
            **identity: object,
        ) -> None:
            if source_dir_fd is None:
                self.fail("publication source must be descriptor-relative")
            os.rename(
                os.fspath(source),
                "validated-payload",
                src_dir_fd=source_dir_fd,
                dst_dir_fd=source_dir_fd,
            )
            os.mkdir(os.fspath(source), mode=0o700, dir_fd=source_dir_fd)
            replacement_dir_fd = os.open(
                os.fspath(source),
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
                dir_fd=source_dir_fd,
            )
            try:
                replacement_fd = os.open(
                    EXPECTED_LIBRARY,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o600,
                    dir_fd=replacement_dir_fd,
                )
                with os.fdopen(replacement_fd, "wb") as replacement:
                    _ = replacement.write(malicious)
            finally:
                os.close(replacement_dir_fd)
            cast(Any, original_rename)(
                source,
                destination,
                source_dir_fd=source_dir_fd,
                destination_dir_fd=destination_dir_fd,
                **identity,
            )

        args = argparse.Namespace(
            archive=self.archive,
            target=TARGET,
            feature_set=FEATURE_SET,
        )
        with (
            mock.patch.dict(os.environ, {"ORT_CACHE_DIR": str(self.cache)}),
            mock.patch.object(
                installer,
                "atomic_rename_noreplace",
                side_effect=substitute_then_rename,
            ),
            self.assertRaisesRegex(installer.InstallerError, "payload changed"),
        ):
            _ = installer.install(args)

        destination = self.cache / "dfbin" / TARGET / sha256
        if destination.exists():
            self.assertNotEqual(
                (destination / EXPECTED_LIBRARY).read_bytes(), malicious
            )

    @unittest.skipIf(os.name == "nt", "POSIX directory descriptors are not available")
    def test_extracted_runtime_leaf_replacement_is_rejected_before_publication(
        self,
    ) -> None:
        # Catches trusting archive-input validation after the extracted output
        # leaf has been replaced with different bytes under the same name.
        trusted = b"verified runtime"
        malicious = b"attacker runtime"
        self.assertEqual(len(trusted), len(malicious))
        sha256 = build_archive(self.archive, {EXPECTED_LIBRARY: trusted})
        self.write_manifest(sha256)
        installer = self.load_installer_module()
        original_extract = installer.extract_tar_safely

        def replace_output_leaf(*args: Any, **kwargs: Any) -> Any:
            evidence = original_extract(*args, **kwargs)
            payload_fd = kwargs.get("staging_dir_fd")
            self.assertIsInstance(payload_fd, int)
            assert isinstance(payload_fd, int)
            replacement_fd = os.open(
                ".replacement",
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=payload_fd,
            )
            with os.fdopen(replacement_fd, "wb") as replacement:
                replacement.write(malicious)
            os.replace(
                ".replacement",
                EXPECTED_LIBRARY,
                src_dir_fd=payload_fd,
                dst_dir_fd=payload_fd,
            )
            return evidence

        args = argparse.Namespace(
            archive=self.archive,
            target=TARGET,
            feature_set=FEATURE_SET,
        )
        with (
            mock.patch.dict(os.environ, {"ORT_CACHE_DIR": str(self.cache)}),
            mock.patch.object(
                installer, "extract_tar_safely", side_effect=replace_output_leaf
            ),
            self.assertRaisesRegex(installer.InstallerError, "output|changed|bytes"),
        ):
            _ = installer.install(args)

        self.assertFalse((self.cache / "dfbin" / TARGET / sha256).exists())

    @unittest.skipIf(os.name == "nt", "POSIX directory descriptors are not available")
    def test_extracted_runtime_leaf_inplace_change_is_rejected_before_publication(
        self,
    ) -> None:
        # Catches an in-place same-size rewrite after extraction but before the
        # output tree is atomically published.
        trusted = b"verified runtime"
        malicious = b"attacker runtime"
        self.assertEqual(len(trusted), len(malicious))
        sha256 = build_archive(self.archive, {EXPECTED_LIBRARY: trusted})
        self.write_manifest(sha256)
        installer = self.load_installer_module()
        original_extract = installer.extract_tar_safely

        def rewrite_output_leaf(*args: Any, **kwargs: Any) -> Any:
            evidence = original_extract(*args, **kwargs)
            payload_fd = kwargs.get("staging_dir_fd")
            self.assertIsInstance(payload_fd, int)
            assert isinstance(payload_fd, int)
            descriptor = os.open(
                EXPECTED_LIBRARY,
                os.O_WRONLY | os.O_TRUNC,
                dir_fd=payload_fd,
            )
            with os.fdopen(descriptor, "wb") as output:
                output.write(malicious)
            return evidence

        args = argparse.Namespace(
            archive=self.archive,
            target=TARGET,
            feature_set=FEATURE_SET,
        )
        with (
            mock.patch.dict(os.environ, {"ORT_CACHE_DIR": str(self.cache)}),
            mock.patch.object(
                installer, "extract_tar_safely", side_effect=rewrite_output_leaf
            ),
            self.assertRaisesRegex(installer.InstallerError, "output|changed|bytes"),
        ):
            _ = installer.install(args)

        self.assertFalse((self.cache / "dfbin" / TARGET / sha256).exists())

    def test_native_windows_installation_fails_closed_before_cache_mutation(
        self,
    ) -> None:
        sha256 = build_archive(self.archive, {EXPECTED_LIBRARY: b"verified runtime"})
        self.write_manifest(sha256)
        installer = self.load_installer_module()
        args = argparse.Namespace(
            archive=self.archive,
            target=TARGET,
            feature_set=FEATURE_SET,
        )

        with (
            mock.patch.dict(os.environ, {"ORT_CACHE_DIR": str(self.cache)}),
            mock.patch.object(cast(Any, installer), "_WINDOWS", True),
        ):
            with self.assertRaisesRegex(installer.InstallerError, "native Windows"):
                _ = installer.install(args)

        self.assertFalse(self.cache.exists())

    @unittest.skipIf(os.name == "nt", "POSIX directory descriptors are not available")
    def test_noreplace_rename_is_anchored_to_verified_directory_descriptor(
        self,
    ) -> None:
        installer = self.load_installer_module()
        parent = self.root / "anchored"
        parent.mkdir()
        (parent / "source").mkdir()
        parent_fd = os.open(
            parent,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
        displaced = self.root / "displaced"
        outside = self.root / "outside"
        parent.rename(displaced)
        outside.mkdir()
        parent.symlink_to(outside, target_is_directory=True)
        try:
            installer.atomic_rename_noreplace(
                Path("source"),
                Path("destination"),
                source_dir_fd=parent_fd,
                destination_dir_fd=parent_fd,
            )
        finally:
            os.close(parent_fd)

        self.assertTrue((displaced / "destination").is_dir())
        self.assertEqual(list(outside.iterdir()), [])

    @unittest.skipIf(os.name == "nt", "POSIX directory descriptors are not available")
    def test_target_root_swap_after_final_check_cannot_escape_install(self) -> None:
        sha256 = build_archive(self.archive, {EXPECTED_LIBRARY: b"verified runtime"})
        self.write_manifest(sha256)
        installer = self.load_installer_module()
        original_rename = installer.atomic_rename_noreplace
        target_root = self.cache / "dfbin" / TARGET
        displaced = self.root / "displaced-after-check"
        outside = self.root / "outside-after-check"

        def substitute_then_rename(
            source: Path,
            destination: Path,
            *,
            source_dir_fd: int | None = None,
            destination_dir_fd: int | None = None,
            source_identity: tuple[int, int] | None = None,
            publication_state: Any = None,
        ) -> None:
            target_root.rename(displaced)
            outside.mkdir()
            target_root.symlink_to(outside, target_is_directory=True)
            cast(Any, original_rename)(
                source,
                destination,
                source_dir_fd=source_dir_fd,
                destination_dir_fd=destination_dir_fd,
                source_identity=source_identity,
                publication_state=publication_state,
            )

        args = argparse.Namespace(
            archive=self.archive,
            target=TARGET,
            feature_set=FEATURE_SET,
        )
        with (
            mock.patch.dict(os.environ, {"ORT_CACHE_DIR": str(self.cache)}),
            mock.patch.object(
                installer,
                "atomic_rename_noreplace",
                side_effect=substitute_then_rename,
            ),
            self.assertRaisesRegex(
                installer.InstallDurabilityUnknown,
                "installed but durability is unknown",
            ),
        ):
            _ = installer.install(args)

        self.assertEqual(list(outside.iterdir()), [])
        retained = list(displaced.iterdir())
        self.assertEqual(len(retained), 2)
        self.assertTrue((displaced / sha256 / EXPECTED_LIBRARY).is_file())
        staging = next(
            entry for entry in retained if entry.name.startswith(f".install-{sha256}-")
        )
        self.assertTrue((staging / "archive.tar").is_file())

    @unittest.skipIf(os.name == "nt", "POSIX directory descriptors are not available")
    def test_recovery_preserves_foreign_output_replacing_published_payload(
        self,
    ) -> None:
        # Catches failure recovery recursively deleting an entry whose identity no
        # longer matches the held, installer-owned payload directory.
        sha256 = build_archive(self.archive, {EXPECTED_LIBRARY: b"verified runtime"})
        self.write_manifest(sha256)
        installer = self.load_installer_module()
        original_rename = installer.atomic_rename_noreplace
        target_root = self.cache / "dfbin" / TARGET
        displaced = self.root / "displaced-with-foreign"
        outside = self.root / "outside-replacement"

        def replace_output_then_invalidate_root(
            source: Path,
            destination: Path,
            *,
            source_dir_fd: int | None = None,
            destination_dir_fd: int | None = None,
            source_identity: tuple[int, int] | None = None,
            publication_state: Any = None,
        ) -> None:
            cast(Any, original_rename)(
                source,
                destination,
                source_dir_fd=source_dir_fd,
                destination_dir_fd=destination_dir_fd,
                source_identity=source_identity,
                publication_state=publication_state,
            )
            if destination_dir_fd is None:
                self.fail("runtime publication must remain descriptor-relative")
            os.rename(
                sha256,
                "installer-owned-output",
                src_dir_fd=destination_dir_fd,
                dst_dir_fd=destination_dir_fd,
            )
            os.mkdir(sha256, mode=0o700, dir_fd=destination_dir_fd)
            foreign_root_fd = os.open(
                sha256,
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
                dir_fd=destination_dir_fd,
            )
            try:
                foreign_fd = os.open(
                    "foreign-sentinel",
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o600,
                    dir_fd=foreign_root_fd,
                )
                os.close(foreign_fd)
            finally:
                os.close(foreign_root_fd)
            target_root.rename(displaced)
            outside.mkdir()
            target_root.symlink_to(outside, target_is_directory=True)

        args = argparse.Namespace(
            archive=self.archive,
            target=TARGET,
            feature_set=FEATURE_SET,
        )
        with (
            mock.patch.dict(os.environ, {"ORT_CACHE_DIR": str(self.cache)}),
            mock.patch.object(
                installer,
                "atomic_rename_noreplace",
                side_effect=replace_output_then_invalidate_root,
            ),
            self.assertRaisesRegex(
                installer.InstallDurabilityUnknown,
                "installed but durability is unknown",
            ),
        ):
            installer.install(args)

        self.assertTrue((displaced / sha256 / "foreign-sentinel").is_file())

    def test_runtime_output_validation_accepts_one_library_without_list_materialization(
        self,
    ) -> None:
        # Catches exact-inventory validation materializing even the accepted
        # directory instead of consuming its entries incrementally.
        installer = self.load_installer_module()
        implementation = cast(Any, installer)
        payload = self.root / "single-runtime-output"
        payload.mkdir()
        library = payload / EXPECTED_LIBRARY
        content = b"verified runtime"
        library.write_bytes(content)
        state = library.stat()
        evidence = implementation.ExtractedFileEvidence(
            identity=implementation.file_identity(state),
            mutable_state=implementation.mutable_file_state(state),
            sha256=hashlib.sha256(content).hexdigest(),
        )
        payload_fd = os.open(payload, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        validated_fd: int | None = None
        try:
            with mock.patch.object(
                implementation.os,
                "listdir",
                side_effect=AssertionError("runtime inventory must not materialize"),
            ):
                validated_fd = implementation._validate_runtime_output_tree(
                    payload_fd, EXPECTED_LIBRARY, evidence
                )
        finally:
            if validated_fd is not None:
                os.close(validated_fd)
            os.close(payload_fd)

    def test_runtime_output_validation_rejects_first_extra_entry_immediately(
        self,
    ) -> None:
        # Catches scanning an attacker-controlled tail after the first root entry
        # already proves the exact single-library inventory is invalid.
        installer = self.load_installer_module()
        implementation = cast(Any, installer)

        class ExtraThenUnbounded:
            advances = 0
            closed = False

            def __enter__(self) -> ExtraThenUnbounded:
                return self

            def __exit__(self, *_args: Any) -> None:
                self.closed = True

            def __iter__(self) -> ExtraThenUnbounded:
                return self

            def __next__(self) -> Any:
                self.advances += 1
                if self.advances == 1:
                    return type("Entry", (), {"name": "unexpected-runtime"})()
                raise AssertionError(
                    "runtime inventory advanced after first extra entry"
                )

        entries = ExtraThenUnbounded()
        with (
            mock.patch.object(implementation.os, "scandir", return_value=entries),
            mock.patch.object(
                implementation.os,
                "listdir",
                side_effect=AssertionError("runtime inventory must not materialize"),
            ),
            self.assertRaisesRegex(implementation.InstallerError, "inventory"),
        ):
            implementation._validate_runtime_output_tree(0, EXPECTED_LIBRARY, object())

        self.assertEqual(entries.advances, 1)
        self.assertTrue(entries.closed)

    def test_runtime_output_validation_rejects_extra_after_library_before_huge_tail(
        self,
    ) -> None:
        # Catches collecting or sorting a huge attacker-controlled tail after the
        # expected library followed by one extra entry has already invalidated it.
        installer = self.load_installer_module()
        implementation = cast(Any, installer)

        class LibraryExtraThenHugeTail:
            advances = 0
            closed = False

            def __enter__(self) -> LibraryExtraThenHugeTail:
                return self

            def __exit__(self, *_args: Any) -> None:
                self.closed = True

            def __iter__(self) -> LibraryExtraThenHugeTail:
                return self

            def __next__(self) -> Any:
                self.advances += 1
                if self.advances == 1:
                    return type("Entry", (), {"name": EXPECTED_LIBRARY})()
                if self.advances == 2:
                    return type("Entry", (), {"name": "first-of-huge-tail"})()
                raise AssertionError("runtime inventory consumed the huge tail")

        entries = LibraryExtraThenHugeTail()
        with (
            mock.patch.object(implementation.os, "scandir", return_value=entries),
            mock.patch.object(
                implementation.os,
                "listdir",
                side_effect=AssertionError("runtime inventory must not materialize"),
            ),
            self.assertRaisesRegex(implementation.InstallerError, "inventory"),
        ):
            implementation._validate_runtime_output_tree(0, EXPECTED_LIBRARY, object())

        self.assertEqual(entries.advances, 2)
        self.assertTrue(entries.closed)

    def test_private_runtime_staging_retains_rejected_tree_without_traversal(
        self,
    ) -> None:
        # Catches retained recovery cleanup recursively walking attacker-grown
        # staging after the platform cannot safely condition deletion on identity.
        installer = self.load_installer_module()
        implementation = cast(Any, installer)
        parent = self.root / "retained-runtime-staging"
        parent.mkdir()
        parent_fd = os.open(parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        staging_name = ""
        try:
            with mock.patch.object(
                implementation.os,
                "listdir",
                side_effect=AssertionError("retained staging must not be traversed"),
            ):
                with self.assertRaisesRegex(
                    implementation.InstallerError, "rejected staging inventory"
                ):
                    with implementation._private_staging_directory(
                        parent_fd, ".bounded-test-"
                    ) as staged:
                        staging_name, staging_fd = staged
                        os.mkdir("nested", mode=0o700, dir_fd=staging_fd)
                        raise implementation.InstallerError(
                            "rejected staging inventory"
                        )
        finally:
            os.close(parent_fd)

        self.assertTrue((parent / staging_name / "nested").is_dir())

    def test_cleanup_preserves_foreign_replacement_at_delete_boundary(self) -> None:
        installer = self.load_installer_module()
        implementation = cast(Any, installer)
        parent = self.root / "cleanup-parent"
        parent.mkdir()
        owned = parent / "owned"
        owned.mkdir()
        expected_identity = implementation.file_identity(owned.stat())
        displaced = self.root / "displaced-owned"
        real_rmdir = os.rmdir
        swapped = False

        def substitute() -> None:
            nonlocal swapped
            if swapped:
                return
            swapped = True
            owned.rename(displaced)
            owned.mkdir()

        def racing_rmdir(path: Any, *args: Any, **kwargs: Any) -> Any:
            if os.fspath(path) == "owned":
                substitute()
            return real_rmdir(path, *args, **kwargs)

        parent_fd = os.open(parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            with mock.patch.object(
                cast(Any, installer).os,
                "rmdir",
                side_effect=racing_rmdir,
            ):
                removed = implementation._remove_owned_directory_at(
                    parent_fd, "owned", expected_identity
                )
        finally:
            os.close(parent_fd)

        self.assertFalse(removed)
        self.assertFalse(swapped)
        self.assertTrue(owned.is_dir())

    def test_cleanup_preserves_leaf_replaced_at_unlink_boundary(self) -> None:
        installer = self.load_installer_module()
        implementation = cast(Any, installer)
        parent = self.root / "cleanup-leaf-parent"
        parent.mkdir()
        owned = parent / "owned"
        owned.mkdir()
        payload = owned / "payload"
        payload.write_bytes(b"owned")
        displaced = owned / "displaced-payload"
        real_unlink = os.unlink
        swapped = False

        def racing_unlink(path: Any, *args: Any, **kwargs: Any) -> Any:
            nonlocal swapped
            if os.fspath(path) == "payload" and not swapped:
                swapped = True
                payload.rename(displaced)
                payload.write_bytes(b"foreign")
            return real_unlink(path, *args, **kwargs)

        directory_fd = os.open(owned, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            with mock.patch.object(
                cast(Any, installer).os, "unlink", side_effect=racing_unlink
            ):
                cleared = implementation._clear_owned_directory_fd(directory_fd)
        finally:
            os.close(directory_fd)

        self.assertFalse(cleared)
        self.assertFalse(swapped)
        self.assertEqual(payload.read_bytes(), b"owned")
        self.assertFalse(displaced.exists())


if __name__ == "__main__":
    _ = unittest.main()
