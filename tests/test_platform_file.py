#!/usr/bin/env python3
"""Focused tests for portable advisory locking and atomic file replacement."""

from __future__ import annotations

import importlib.util
from contextlib import AbstractContextManager
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import time
from types import ModuleType
from typing import Callable, cast
import unittest
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "scripts/platform_file.py"
LOCK_WORKER = r"""
from pathlib import Path
import sys
import time

sys.path.insert(0, sys.argv[1])
from platform_file import advisory_lock

target = Path(sys.argv[2])
signal = Path(sys.argv[3])
release = Path(sys.argv[4])
role = sys.argv[5]
with advisory_lock(target):
    signal.write_text("acquired", encoding="utf-8")
    if role == "holder":
        while not release.exists():
            time.sleep(0.01)
"""


class _FakeWindowsFunction:
    """Callable WinDLL function stand-in with mutable ctypes metadata."""

    argtypes: object = None
    restype: object = None

    def __init__(self, operation: Callable[..., int]) -> None:
        self._operation = operation

    def __call__(self, *args: object) -> int:
        return self._operation(*args)


class _FakeWindowsKernel:
    """Minimal ownership model for exercising the native mutex adapter."""

    def __init__(self) -> None:
        self.abandon_next = False
        self.held = False
        self.open_handles = 0
        self.CreateMutexW = _FakeWindowsFunction(self._create_mutex)
        self.WaitForSingleObject = _FakeWindowsFunction(self._wait)
        self.ReleaseMutex = _FakeWindowsFunction(self._release)
        self.CloseHandle = _FakeWindowsFunction(self._close)

    def _create_mutex(self, _security: object, _owner: object, name: object) -> int:
        if not isinstance(name, str) or not name.startswith(
            "Global\\the-one-model-cache-"
        ):
            return 0
        self.open_handles += 1
        return self.open_handles + 100

    def _wait(self, _handle: object, _timeout: object) -> int:
        if self.abandon_next:
            self.abandon_next = False
            self.held = True
            return 0x00000080
        if self.held:
            return 0x00000102
        self.held = True
        return 0x00000000

    def _release(self, _handle: object) -> int:
        if not self.held:
            return 0
        self.held = False
        return 1

    def _close(self, _handle: object) -> int:
        if self.open_handles == 0:
            return 0
        self.open_handles -= 1
        return 1


def load_platform_file_module() -> ModuleType:
    if not MODULE_PATH.is_file():
        raise AssertionError("platform_file.py must exist")
    spec = importlib.util.spec_from_file_location("test_platform_file", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError("could not load platform-file module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    return module


class AtomicReplaceTests(unittest.TestCase):
    @staticmethod
    def _replace_function(module: ModuleType) -> Callable[[Path, bytes], None]:
        replace = cast(
            Callable[[Path, bytes], None],
            getattr(module, "atomic_replace_bytes", None),
        )
        if not callable(replace):
            raise AssertionError("atomic_replace_bytes must be exported")
        return replace

    @staticmethod
    def _error_type(module: ModuleType) -> type[Exception]:
        error_type = getattr(module, "PlatformFileError", None)
        if not isinstance(error_type, type) or not issubclass(error_type, Exception):
            raise AssertionError("PlatformFileError must be exported")
        return cast(type[Exception], error_type)

    @staticmethod
    def _durability_error_type(module: ModuleType) -> type[Exception]:
        error_type = getattr(module, "PlatformFileDurabilityUnknown", None)
        if not isinstance(error_type, type) or not issubclass(error_type, Exception):
            raise AssertionError("PlatformFileDurabilityUnknown must be exported")
        precommit_error = AtomicReplaceTests._error_type(module)
        if issubclass(error_type, precommit_error):
            raise AssertionError(
                "durability-unknown must not be caught as a pre-commit PlatformFileError"
            )
        return cast(type[Exception], error_type)

    def test_replaces_bytes_and_preserves_existing_mode(self) -> None:
        # Catches replacing a private manifest with temp-file default permissions.
        self.assertTrue(MODULE_PATH.is_file(), "platform_file.py must exist")
        module = load_platform_file_module()
        replace = self._replace_function(module)
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "manifest.toml"
            target.write_bytes(b"old")
            target.chmod(0o640)

            replace(target, b"new manifest\n")

            self.assertEqual(target.read_bytes(), b"new manifest\n")
            if os.name != "nt":
                self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o640)
            recovery = list(target.parent.glob(f".{target.name}.*.tmp"))
            self.assertEqual(len(recovery), 1)
            self.assertEqual(recovery[0].read_bytes(), b"old")
            recovery[0].unlink()

    def test_rejects_missing_non_regular_and_multiply_linked_targets(self) -> None:
        # Catches replacing an attacker-controlled target shape or silently breaking hard links.
        module = load_platform_file_module()
        replace = self._replace_function(module)
        error_type = self._error_type(module)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            missing = root / "missing.toml"
            directory = root / "directory.toml"
            directory.mkdir()
            linked = root / "linked.toml"
            alias = root / "linked-alias.toml"
            linked.write_bytes(b"linked")
            os.link(linked, alias)

            for target in (missing, directory, linked):
                with self.subTest(target=target.name):
                    with self.assertRaises(error_type):
                        replace(target, b"replacement")

            self.assertEqual(linked.read_bytes(), b"linked")
            self.assertEqual(alias.read_bytes(), b"linked")
            self.assertEqual(list(root.glob(".*.tmp")), [])

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks are unavailable")
    def test_rejects_symlink_target_without_changing_referent(self) -> None:
        # Catches following a manifest symlink into an unintended file.
        module = load_platform_file_module()
        replace = self._replace_function(module)
        error_type = self._error_type(module)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            referent = root / "referent.toml"
            target = root / "manifest.toml"
            referent.write_bytes(b"trusted")
            try:
                target.symlink_to(referent.name)
            except OSError as error:
                self.skipTest(f"symlink creation is unavailable: {error}")

            with self.assertRaises(error_type):
                replace(target, b"attacker controlled")

            self.assertEqual(referent.read_bytes(), b"trusted")
            self.assertTrue(target.is_symlink())
            self.assertEqual(list(root.glob(f".{target.name}.*.tmp")), [])

    def test_temp_sync_failure_preserves_original_and_recovery_entry(self) -> None:
        # Catches publishing bytes that were not successfully flushed to stable storage.
        module = load_platform_file_module()
        replace = self._replace_function(module)
        durability_error = self._durability_error_type(module)
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "manifest.toml"
            target.write_bytes(b"old")

            with mock.patch.object(
                module.os, "fsync", side_effect=OSError("injected temp sync failure")
            ):
                with self.assertRaisesRegex(
                    OSError, "injected temp sync failure"
                ) as raised:
                    replace(target, b"new")

            self.assertNotIsInstance(raised.exception, durability_error)
            self.assertEqual(target.read_bytes(), b"old")
            recovery = list(target.parent.glob(f".{target.name}.*.tmp"))
            self.assertEqual(len(recovery), 1)
            self.assertEqual(recovery[0].read_bytes(), b"new")
            recovery[0].unlink()

    def test_replace_failure_preserves_original_and_recovery_entry(self) -> None:
        # Catches leaking a prepared manifest when the atomic rename cannot complete.
        module = load_platform_file_module()
        replace = self._replace_function(module)
        durability_error = self._durability_error_type(module)
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "manifest.toml"
            target.write_bytes(b"old")

            with mock.patch.object(
                module,
                "_rename_exchange_at",
                side_effect=OSError("injected replace failure"),
            ):
                with self.assertRaisesRegex(
                    OSError, "injected replace failure"
                ) as raised:
                    replace(target, b"new")

            self.assertNotIsInstance(raised.exception, durability_error)
            self.assertEqual(target.read_bytes(), b"old")
            recovery = list(target.parent.glob(f".{target.name}.*.tmp"))
            self.assertEqual(len(recovery), 1)
            self.assertEqual(recovery[0].read_bytes(), b"new")
            recovery[0].unlink()

    def test_refuses_lost_update_if_target_changes_before_replace(self) -> None:
        # Catches overwriting a different manifest inode installed during preparation.
        module = load_platform_file_module()
        replace = self._replace_function(module)
        error_type = self._error_type(module)
        real_mkstemp = tempfile.mkstemp
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "manifest.toml"
            target.write_bytes(b"baseline")

            def replace_target_then_make_temp(
                *, suffix: str, prefix: str, dir: str | os.PathLike[str]
            ) -> tuple[int, str]:
                descriptor, name = real_mkstemp(suffix=suffix, prefix=prefix, dir=dir)
                concurrent = root / "concurrent.toml"
                concurrent.write_bytes(b"concurrent")
                os.replace(concurrent, target)
                return descriptor, name

            with mock.patch.object(
                module.tempfile, "mkstemp", side_effect=replace_target_then_make_temp
            ):
                with self.assertRaisesRegex(error_type, "changed"):
                    replace(target, b"ours")

            self.assertEqual(target.read_bytes(), b"concurrent")
            recovery = list(root.glob(f".{target.name}.*.tmp"))
            self.assertEqual(len(recovery), 1)
            self.assertEqual(recovery[0].read_bytes(), b"ours")
            recovery[0].unlink()

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks are unavailable")
    def test_refuses_temp_path_substitution_before_replace(self) -> None:
        # Catches replacing the manifest with a symlink swapped into the temp pathname.
        module = load_platform_file_module()
        replace = self._replace_function(module)
        error_type = self._error_type(module)
        real_fsync = os.fsync
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "manifest.toml"
            attacker = root / "attacker.toml"
            target.write_bytes(b"trusted manifest")
            attacker.write_bytes(b"attacker bytes")
            swapped = False

            def sync_then_swap(descriptor: int) -> None:
                nonlocal swapped
                real_fsync(descriptor)
                if swapped:
                    return
                candidate = next(root.glob(f".{target.name}.*.tmp"))
                candidate.unlink()
                try:
                    candidate.symlink_to(attacker.name)
                except OSError as error:
                    self.skipTest(f"symlink substitution is unavailable: {error}")
                swapped = True

            with mock.patch.object(module.os, "fsync", side_effect=sync_then_swap):
                with self.assertRaisesRegex(error_type, "temporary file changed"):
                    replace(target, b"replacement")

            self.assertFalse(target.is_symlink())
            self.assertEqual(target.read_bytes(), b"trusted manifest")
            self.assertEqual(attacker.read_bytes(), b"attacker bytes")
            preserved = list(root.glob(f".{target.name}.*.tmp"))
            self.assertEqual(len(preserved), 1)
            self.assertTrue(preserved[0].is_symlink())
            self.assertEqual(preserved[0].read_bytes(), b"attacker bytes")
            preserved[0].unlink()

    @unittest.skipIf(os.name == "nt", "exercises POSIX descriptor identity checks")
    def test_refuses_temp_substitution_inside_final_replace(self) -> None:
        # Catches a swap at publication without sacrificing the original manifest.
        module = load_platform_file_module()
        replace = self._replace_function(module)
        error_type = self._error_type(module)
        real_replace = os.replace
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "manifest.toml"
            target.write_bytes(b"trusted manifest")
            swapped = False

            def swap_source_at_replace(
                source: str | os.PathLike[str],
                destination: str | os.PathLike[str],
                *,
                src_dir_fd: int | None = None,
                dst_dir_fd: int | None = None,
            ) -> None:
                nonlocal swapped
                source_path = Path(source)
                if not source_path.is_absolute():
                    source_path = root / source_path
                if not swapped and source_path.name.startswith(f".{target.name}."):
                    source_path.unlink()
                    source_path.write_bytes(b"attacker bytes")
                    swapped = True
                real_replace(
                    source,
                    destination,
                    src_dir_fd=src_dir_fd,
                    dst_dir_fd=dst_dir_fd,
                )

            exchange = getattr(module, "_rename_exchange_at", None)
            if callable(exchange):

                def swap_source_at_exchange(
                    parent_descriptor: int,
                    source: str,
                    destination: str,
                ) -> None:
                    nonlocal swapped
                    source_path = root / source
                    if not swapped and source_path.name.startswith(f".{target.name}."):
                        source_path.unlink()
                        source_path.write_bytes(b"attacker bytes")
                        swapped = True
                    exchange(parent_descriptor, source, destination)

                publication_patch = mock.patch.object(
                    module,
                    "_rename_exchange_at",
                    side_effect=swap_source_at_exchange,
                )
            else:
                publication_patch = mock.patch.object(
                    module.os,
                    "replace",
                    side_effect=swap_source_at_replace,
                )

            with publication_patch:
                with self.assertRaisesRegex(error_type, "temporary file changed"):
                    replace(target, b"replacement")

            self.assertTrue(swapped)
            self.assertEqual(target.read_bytes(), b"trusted manifest")
            preserved = list(root.glob(f".{target.name}.*.tmp"))
            self.assertEqual(len(preserved), 1)
            self.assertEqual(preserved[0].read_bytes(), b"attacker bytes")
            preserved[0].unlink()

    @unittest.skipIf(os.name == "nt", "exercises POSIX exchange validation")
    def test_refuses_equal_size_inplace_temp_rewrite_during_exchange(self) -> None:
        # Catches accepting changed bytes when the candidate inode and size stay constant.
        module = load_platform_file_module()
        replace = self._replace_function(module)
        error_type = self._error_type(module)
        exchange = cast(
            Callable[[int, str, str], None],
            getattr(module, "_rename_exchange_at"),
        )
        replacement = b"validated replacement"
        attacker = b"attacker replacement!"
        self.assertEqual(len(replacement), len(attacker))

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "manifest.toml"
            target.write_bytes(b"trusted manifest")
            exchange_calls = 0

            def rewrite_candidate_then_exchange(
                parent_descriptor: int,
                source: str,
                destination: str,
            ) -> None:
                nonlocal exchange_calls
                exchange_calls += 1
                if exchange_calls == 1:
                    descriptor = os.open(
                        source,
                        os.O_WRONLY | os.O_TRUNC,
                        dir_fd=parent_descriptor,
                    )
                    try:
                        self.assertEqual(os.write(descriptor, attacker), len(attacker))
                    finally:
                        os.close(descriptor)
                exchange(parent_descriptor, source, destination)

            with mock.patch.object(
                module,
                "_rename_exchange_at",
                side_effect=rewrite_candidate_then_exchange,
            ):
                with self.assertRaisesRegex(error_type, "temporary file changed"):
                    replace(target, replacement)

            self.assertEqual(exchange_calls, 2)
            self.assertEqual(target.read_bytes(), b"trusted manifest")
            recovery = list(root.glob(f".{target.name}.*.tmp"))
            self.assertEqual(len(recovery), 1)
            self.assertEqual(recovery[0].read_bytes(), attacker)
            recovery[0].unlink()

    @unittest.skipIf(os.name == "nt", "exercises POSIX exchange rollback")
    def test_exchange_rollback_failure_preserves_original_recovery_entry(self) -> None:
        module = load_platform_file_module()
        replace = self._replace_function(module)
        durability_error = self._durability_error_type(module)
        exchange = cast(
            Callable[[int, str, str], None],
            getattr(module, "_rename_exchange_at"),
        )
        exchange_calls = 0
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "manifest.toml"
            target.write_bytes(b"trusted manifest")

            def substitute_then_fail_rollback(
                parent_descriptor: int,
                source: str,
                destination: str,
            ) -> None:
                nonlocal exchange_calls
                exchange_calls += 1
                if exchange_calls == 1:
                    source_path = root / source
                    source_path.unlink()
                    source_path.write_bytes(b"attacker bytes")
                    exchange(parent_descriptor, source, destination)
                    return
                raise OSError("injected exchange rollback failure")

            with mock.patch.object(
                module,
                "_rename_exchange_at",
                side_effect=substitute_then_fail_rollback,
            ):
                with self.assertRaisesRegex(
                    durability_error, "durability is unknown"
                ) as raised:
                    replace(target, b"replacement")

            self.assertRegex(str(raised.exception.__cause__), "rollback failed")
            self.assertEqual(target.read_bytes(), b"attacker bytes")
            recovery_entries = list(root.glob(f".{target.name}.*.tmp"))
            self.assertEqual(len(recovery_entries), 1)
            self.assertEqual(recovery_entries[0].read_bytes(), b"trusted manifest")
            recovery_entries[0].unlink()
            target.unlink()

    @unittest.skipIf(os.name == "nt", "exercises POSIX exchange rollback")
    def test_exchange_rollback_identity_failure_is_durability_unknown(self) -> None:
        # Catches clearing committed uncertainty before the restored inode is verified.
        module = load_platform_file_module()
        replace = self._replace_function(module)
        durability_error = self._durability_error_type(module)
        exchange = cast(
            Callable[[int, str, str], None],
            getattr(module, "_rename_exchange_at"),
        )
        replacement = b"validated replacement"
        attacker = b"attacker replacement!"
        self.assertEqual(len(replacement), len(attacker))

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "manifest.toml"
            target.write_bytes(b"trusted manifest")
            displaced_original = root / "displaced-original"
            exchange_calls = 0

            def substitute_then_replace_restored_target(
                parent_descriptor: int,
                source: str,
                destination: str,
            ) -> None:
                nonlocal exchange_calls
                exchange_calls += 1
                if exchange_calls == 1:
                    source_path = root / source
                    source_path.unlink()
                    source_path.write_bytes(attacker)
                    exchange(parent_descriptor, source, destination)
                    return
                exchange(parent_descriptor, source, destination)
                os.replace(target, displaced_original)
                target.write_bytes(b"foreign replacement")

            with (
                mock.patch.object(
                    module,
                    "_rename_exchange_at",
                    side_effect=substitute_then_replace_restored_target,
                ),
                self.assertRaisesRegex(
                    durability_error, "durability is unknown"
                ) as raised,
            ):
                replace(target, replacement)

            self.assertRegex(
                str(raised.exception.__cause__), "rollback did not restore"
            )
            self.assertEqual(target.read_bytes(), b"foreign replacement")
            self.assertEqual(displaced_original.read_bytes(), b"trusted manifest")

    @unittest.skipIf(os.name == "nt", "exercises POSIX exchange rollback")
    def test_exchange_rollback_parent_sync_failure_is_durability_unknown(
        self,
    ) -> None:
        # Catches treating an inode-restored but unflushed rollback as retry-safe.
        module = load_platform_file_module()
        replace = self._replace_function(module)
        durability_error = self._durability_error_type(module)
        exchange = cast(
            Callable[[int, str, str], None],
            getattr(module, "_rename_exchange_at"),
        )
        replacement = b"validated replacement"
        attacker = b"attacker replacement!"
        self.assertEqual(len(replacement), len(attacker))
        real_fsync = os.fsync
        sync_calls = 0

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "manifest.toml"
            target.write_bytes(b"trusted manifest")
            exchange_calls = 0

            def substitute_then_exchange(
                parent_descriptor: int,
                source: str,
                destination: str,
            ) -> None:
                nonlocal exchange_calls
                exchange_calls += 1
                if exchange_calls == 1:
                    source_path = root / source
                    source_path.unlink()
                    source_path.write_bytes(attacker)
                exchange(parent_descriptor, source, destination)

            def fail_rollback_parent_sync(descriptor: int) -> None:
                nonlocal sync_calls
                sync_calls += 1
                if sync_calls == 2:
                    raise OSError("injected rollback parent sync failure")
                real_fsync(descriptor)

            with (
                mock.patch.object(
                    module,
                    "_rename_exchange_at",
                    side_effect=substitute_then_exchange,
                ),
                mock.patch.object(
                    module.os,
                    "fsync",
                    side_effect=fail_rollback_parent_sync,
                ),
                self.assertRaisesRegex(
                    durability_error, "durability is unknown"
                ) as raised,
            ):
                replace(target, replacement)

            self.assertRegex(
                str(raised.exception.__cause__), "rollback parent sync failure"
            )
            self.assertEqual(target.read_bytes(), b"trusted manifest")

    @unittest.skipIf(os.name == "nt", "models the unavailable macOS native host")
    def test_macos_exchange_adapter_uses_rename_swap_with_dirfds(self) -> None:
        module = load_platform_file_module()
        exchange = getattr(module, "_rename_exchange_at", None)
        self.assertTrue(callable(exchange), "POSIX exchange adapter must be exported")
        exchange_function = cast(Callable[[int, str, str], None], exchange)
        observed: list[tuple[int, int, int]] = []
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            target = root / "target"
            source.write_bytes(b"source")
            target.write_bytes(b"target")
            descriptor = os.open(root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            self.addCleanup(os.close, descriptor)

            def emulate_renameatx_np(
                source_fd: int,
                source_name: bytes,
                target_fd: int,
                target_name: bytes,
                flags: int,
            ) -> int:
                observed.append((source_fd, target_fd, flags))
                source_path = root / os.fsdecode(source_name)
                target_path = root / os.fsdecode(target_name)
                holding = root / "exchange-holding"
                os.replace(source_path, holding)
                os.replace(target_path, source_path)
                os.replace(holding, target_path)
                return 0

            fake_library = ModuleType("fake_macos_libc")
            fake_library.renameatx_np = _FakeWindowsFunction(  # type: ignore[attr-defined]
                emulate_renameatx_np
            )
            with (
                mock.patch.object(module.sys, "platform", "darwin"),
                mock.patch.object(module.ctypes, "CDLL", return_value=fake_library),
            ):
                exchange_function(descriptor, source.name, target.name)

            self.assertEqual(observed, [(descriptor, descriptor, 2)])
            self.assertEqual(source.read_bytes(), b"target")
            self.assertEqual(target.read_bytes(), b"source")

    @unittest.skipIf(os.name == "nt", "models an unsupported POSIX host")
    def test_unknown_posix_atomic_replace_fails_closed(self) -> None:
        module = load_platform_file_module()
        replace = self._replace_function(module)
        error_type = self._error_type(module)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "manifest.toml"
            target.write_bytes(b"trusted manifest")

            with mock.patch.object(module.sys, "platform", "freebsd14"):
                with self.assertRaisesRegex(error_type, "unsupported"):
                    replace(target, b"replacement")

            self.assertEqual(target.read_bytes(), b"trusted manifest")
            recovery = list(root.glob(f".{target.name}.*.tmp"))
            self.assertEqual(len(recovery), 1)
            self.assertEqual(recovery[0].read_bytes(), b"replacement")
            recovery[0].unlink()

    def test_windows_path_preserves_mode_without_posix_only_chmod_options(self) -> None:
        # Catches passing follow_symlinks=False, which Windows chmod cannot implement.
        module = load_platform_file_module()
        replace = self._replace_function(module)
        windows_flag = getattr(module, "_WINDOWS", None)
        self.assertIsInstance(
            windows_flag, bool, "module must expose its platform branch"
        )
        real_chmod = os.chmod
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "manifest.toml"
            target.write_bytes(b"old")

            def windows_compatible_chmod(path: os.PathLike[str], mode: int) -> None:
                real_chmod(path, mode)

            def emulate_replace_file(
                source: Path,
                destination: Path,
                backup: Path | None,
            ) -> None:
                if backup is not None:
                    os.replace(destination, backup)
                os.replace(source, destination)

            with (
                mock.patch.object(module, "_WINDOWS", True),
                mock.patch.object(
                    module.os, "chmod", side_effect=windows_compatible_chmod
                ),
                mock.patch.object(
                    module,
                    "_windows_replace_file_with_backup",
                    side_effect=emulate_replace_file,
                ),
            ):
                replace(target, b"windows replacement")

            self.assertEqual(target.read_bytes(), b"windows replacement")
            self.assertEqual(list(target.parent.glob(f".{target.name}.*.tmp")), [])
            recovery = list(target.parent.glob(f".{target.name}.*.rollback"))
            self.assertEqual(len(recovery), 1)
            self.assertEqual(recovery[0].read_bytes(), b"old")
            recovery[0].unlink()

    def test_windows_replacefile_rolls_back_temp_path_substitution(self) -> None:
        # Models a Windows path swap at ReplaceFileW call entry.
        module = load_platform_file_module()
        replace = self._replace_function(module)
        error_type = self._error_type(module)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "manifest.toml"
            target.write_bytes(b"trusted manifest")
            swapped = False
            validated_inode = root / "validated-source-inode"

            def emulate_replace_file(
                source: Path,
                destination: Path,
                backup: Path | None,
            ) -> None:
                nonlocal swapped
                if not swapped:
                    os.replace(source, validated_inode)
                    source.write_bytes(b"attacker bytes")
                    swapped = True
                if backup is not None:
                    os.replace(destination, backup)
                os.replace(source, destination)

            with (
                mock.patch.object(module, "_WINDOWS", True),
                mock.patch.object(
                    module,
                    "_windows_replace_file_with_backup",
                    side_effect=emulate_replace_file,
                ),
            ):
                with self.assertRaisesRegex(error_type, "temporary file changed"):
                    replace(target, b"validated replacement")

            self.assertTrue(swapped)
            self.assertEqual(target.read_bytes(), b"trusted manifest")
            self.assertEqual(validated_inode.read_bytes(), b"validated replacement")
            validated_inode.unlink()
            self.assertEqual(list(root.glob(f".{target.name}.*.tmp")), [])

    def test_windows_rollback_failure_preserves_original_backup(self) -> None:
        module = load_platform_file_module()
        replace = self._replace_function(module)
        durability_error = self._durability_error_type(module)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "manifest.toml"
            target.write_bytes(b"trusted manifest")
            validated_inode = root / "validated-source-inode"
            replace_calls = 0

            def substitute_then_fail_rollback(
                source: Path,
                destination: Path,
                backup: Path | None,
            ) -> None:
                nonlocal replace_calls
                replace_calls += 1
                if replace_calls == 1:
                    os.replace(source, validated_inode)
                    source.write_bytes(b"attacker bytes")
                    if backup is None:
                        self.fail("initial ReplaceFileW call must retain a backup")
                    os.replace(destination, backup)
                    os.replace(source, destination)
                    return
                raise OSError("injected Windows rollback failure")

            with (
                mock.patch.object(module, "_WINDOWS", True),
                mock.patch.object(
                    module,
                    "_windows_replace_file_with_backup",
                    side_effect=substitute_then_fail_rollback,
                ),
            ):
                with self.assertRaisesRegex(
                    durability_error, "durability is unknown"
                ) as raised:
                    replace(target, b"validated replacement")

            self.assertRegex(str(raised.exception.__cause__), "rollback failed")
            self.assertEqual(target.read_bytes(), b"attacker bytes")
            recovery_entries = list(root.glob(f".{target.name}.*.rollback"))
            self.assertEqual(len(recovery_entries), 1)
            self.assertEqual(recovery_entries[0].read_bytes(), b"trusted manifest")
            recovery_entries[0].unlink()
            target.unlink()
            validated_inode.unlink()
            self.assertEqual(list(root.glob(f".{target.name}.*.tmp")), [])

    def test_windows_rollback_identity_failure_is_durability_unknown(self) -> None:
        # Catches clearing committed uncertainty before the restored inode is verified.
        module = load_platform_file_module()
        replace = self._replace_function(module)
        durability_error = self._durability_error_type(module)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "manifest.toml"
            target.write_bytes(b"trusted manifest")
            validated_inode = root / "validated-source-inode"
            displaced_original = root / "displaced-original"
            replace_calls = 0

            def substitute_then_replace_restored_target(
                source: Path,
                destination: Path,
                backup: Path | None,
            ) -> None:
                nonlocal replace_calls
                replace_calls += 1
                if replace_calls == 1:
                    os.replace(source, validated_inode)
                    source.write_bytes(b"attacker bytes")
                    if backup is None:
                        self.fail("initial ReplaceFileW call must retain a backup")
                    os.replace(destination, backup)
                    os.replace(source, destination)
                    return
                os.replace(source, destination)
                os.replace(destination, displaced_original)
                destination.write_bytes(b"foreign replacement")

            with (
                mock.patch.object(module, "_WINDOWS", True),
                mock.patch.object(
                    module,
                    "_windows_replace_file_with_backup",
                    side_effect=substitute_then_replace_restored_target,
                ),
                self.assertRaisesRegex(
                    durability_error, "durability is unknown"
                ) as raised,
            ):
                replace(target, b"validated replacement")

            self.assertRegex(
                str(raised.exception.__cause__), "rollback did not restore"
            )
            self.assertEqual(target.read_bytes(), b"foreign replacement")
            self.assertEqual(displaced_original.read_bytes(), b"trusted manifest")
            self.assertEqual(validated_inode.read_bytes(), b"validated replacement")

    def test_windows_rollback_parent_sync_failure_is_durability_unknown(
        self,
    ) -> None:
        # Catches treating an inode-restored but unflushed rollback as retry-safe.
        module = load_platform_file_module()
        replace = self._replace_function(module)
        durability_error = self._durability_error_type(module)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "manifest.toml"
            target.write_bytes(b"trusted manifest")
            validated_inode = root / "validated-source-inode"
            replace_calls = 0

            def substitute_then_restore_original(
                source: Path,
                destination: Path,
                backup: Path | None,
            ) -> None:
                nonlocal replace_calls
                replace_calls += 1
                if replace_calls == 1:
                    os.replace(source, validated_inode)
                    source.write_bytes(b"attacker bytes")
                    if backup is None:
                        self.fail("initial ReplaceFileW call must retain a backup")
                    os.replace(destination, backup)
                    os.replace(source, destination)
                    return
                os.replace(source, destination)

            with (
                mock.patch.object(module, "_WINDOWS", True),
                mock.patch.object(
                    module,
                    "_windows_replace_file_with_backup",
                    side_effect=substitute_then_restore_original,
                ),
                mock.patch.object(
                    module,
                    "_sync_parent_directory",
                    side_effect=OSError("injected rollback parent sync failure"),
                ),
                self.assertRaisesRegex(
                    durability_error, "durability is unknown"
                ) as raised,
            ):
                replace(target, b"validated replacement")

            self.assertRegex(
                str(raised.exception.__cause__), "rollback parent sync failure"
            )
            self.assertEqual(target.read_bytes(), b"trusted manifest")
            self.assertEqual(validated_inode.read_bytes(), b"validated replacement")

    @unittest.skipIf(os.name == "nt", "exercises the POSIX directory-sync branch")
    def test_posix_post_replace_sync_failure_reports_durability_unknown(self) -> None:
        # Catches misreporting a committed replacement as a pre-commit failure.
        module = load_platform_file_module()
        replace = self._replace_function(module)
        durability_error = self._durability_error_type(module)
        real_fsync = os.fsync
        sync_calls = 0
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "manifest.toml"
            target.write_bytes(b"old")

            def fail_directory_sync(descriptor: int) -> None:
                nonlocal sync_calls
                sync_calls += 1
                if sync_calls == 2:
                    raise OSError("injected POSIX directory sync failure")
                real_fsync(descriptor)

            with mock.patch.object(module.os, "fsync", side_effect=fail_directory_sync):
                with self.assertRaisesRegex(
                    durability_error, "replacement installed but durability is unknown"
                ) as raised:
                    replace(target, b"new POSIX bytes")

            self.assertIsInstance(raised.exception.__cause__, OSError)
            self.assertRegex(
                str(raised.exception.__cause__), "injected POSIX directory sync failure"
            )
            self.assertEqual(target.read_bytes(), b"new POSIX bytes")
            recovery = list(root.glob(f".{target.name}.*.tmp"))
            self.assertEqual(len(recovery), 1)
            self.assertEqual(recovery[0].read_bytes(), b"old")
            recovery[0].unlink()
            self.assertFalse((root / ".models-manifest.lock").exists())

    @unittest.skipIf(os.name == "nt", "exercises the POSIX replacement cleanup")
    def test_posix_post_replace_parent_close_failure_reports_durability_unknown(
        self,
    ) -> None:
        # Catches a committed replacement escaping as an ordinary close failure.
        module = load_platform_file_module()
        replace = self._replace_function(module)
        durability_error = self._durability_error_type(module)
        real_close = os.close
        parent_descriptor: int | None = None
        committed = False
        exchange = cast(
            Callable[[int, str, str], None],
            getattr(module, "_rename_exchange_at"),
        )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "manifest.toml"
            target.write_bytes(b"old")

            def exchange_then_mark(
                descriptor: int, source: str, destination: str
            ) -> None:
                nonlocal committed, parent_descriptor
                parent_descriptor = descriptor
                exchange(descriptor, source, destination)
                committed = True

            def close_then_fail(descriptor: int) -> None:
                real_close(descriptor)
                if committed and descriptor == parent_descriptor:
                    raise OSError("injected replacement parent close failure")

            with (
                mock.patch.object(
                    module,
                    "_rename_exchange_at",
                    side_effect=exchange_then_mark,
                ),
                mock.patch.object(module.os, "close", side_effect=close_then_fail),
                self.assertRaisesRegex(
                    durability_error, "replacement installed but durability is unknown"
                ) as raised,
            ):
                replace(target, b"new POSIX bytes")

            self.assertRegex(
                str(raised.exception.__cause__),
                "injected replacement parent close failure",
            )
            self.assertEqual(target.read_bytes(), b"new POSIX bytes")
            recovery = list(root.glob(f".{target.name}.*.tmp"))
            self.assertEqual(len(recovery), 1)
            self.assertEqual(recovery[0].read_bytes(), b"old")
            recovery[0].unlink()

    def test_windows_post_replace_sync_failure_reports_durability_unknown(self) -> None:
        # Catches losing the commit point when Windows cannot flush the installed file.
        module = load_platform_file_module()
        replace = self._replace_function(module)
        durability_error = self._durability_error_type(module)
        real_fsync = os.fsync
        sync_calls = 0
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "manifest.toml"
            target.write_bytes(b"old")

            def fail_installed_file_sync(descriptor: int) -> None:
                nonlocal sync_calls
                sync_calls += 1
                if sync_calls == 3:
                    raise OSError("injected Windows installed-file sync failure")
                real_fsync(descriptor)

            def emulate_replace_file(
                source: Path,
                destination: Path,
                backup: Path | None,
            ) -> None:
                if backup is not None:
                    os.replace(destination, backup)
                os.replace(source, destination)

            with (
                mock.patch.object(module, "_WINDOWS", True),
                mock.patch.object(
                    module.os, "fsync", side_effect=fail_installed_file_sync
                ),
                mock.patch.object(
                    module,
                    "_windows_replace_file_with_backup",
                    side_effect=emulate_replace_file,
                ),
            ):
                with self.assertRaisesRegex(
                    durability_error, "replacement installed but durability is unknown"
                ) as raised:
                    replace(target, b"new Windows bytes")

            self.assertIsInstance(raised.exception.__cause__, OSError)
            self.assertRegex(
                str(raised.exception.__cause__),
                "injected Windows installed-file sync failure",
            )
            self.assertEqual(target.read_bytes(), b"new Windows bytes")
            self.assertEqual(list(root.glob(f".{target.name}.*.tmp")), [])
            recovery = list(root.glob(f".{target.name}.*.rollback"))
            self.assertEqual(len(recovery), 1)
            self.assertEqual(recovery[0].read_bytes(), b"old")
            recovery[0].unlink()
            self.assertFalse((root / ".models-manifest.lock").exists())


class AdvisoryLockTests(unittest.TestCase):
    @staticmethod
    def _lock_function(
        module: ModuleType,
    ) -> Callable[[Path], AbstractContextManager[None]]:
        lock = cast(
            Callable[[Path], AbstractContextManager[None]],
            getattr(module, "advisory_lock", None),
        )
        if not callable(lock):
            raise AssertionError("advisory_lock must be exported")
        return lock

    @staticmethod
    def _stop_process(process: subprocess.Popen[str]) -> None:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

    def _wait_for_signal(
        self, signal: Path, process: subprocess.Popen[str], timeout: float = 5.0
    ) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if signal.exists():
                return
            return_code = process.poll()
            if return_code is not None:
                _, stderr = process.communicate()
                self.fail(
                    f"lock worker exited {return_code} before acquiring lock: {stderr}"
                )
            time.sleep(0.01)
        self.fail("lock worker did not acquire within timeout")

    def test_serializes_processes_in_same_directory_without_lock_artifact(self) -> None:
        # Catches inode-split overlap caused by deleting and recreating a lock file around waiters.
        module = load_platform_file_module()
        self._lock_function(module)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            holder_target = root / "manifest.toml"
            contender_target = root / "other-manifest.toml"
            ready = root / "ready"
            release = root / "release"
            acquired = root / "contender-acquired"
            holder = subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    LOCK_WORKER,
                    str(REPO_ROOT / "scripts"),
                    str(holder_target),
                    str(ready),
                    str(release),
                    "holder",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self.addCleanup(self._stop_process, holder)
            self._wait_for_signal(ready, holder)
            contender = subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    LOCK_WORKER,
                    str(REPO_ROOT / "scripts"),
                    str(contender_target),
                    str(acquired),
                    str(release),
                    "contender",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self.addCleanup(self._stop_process, contender)

            time.sleep(0.25)
            self.assertFalse(
                acquired.exists(), "contender entered the locked directory"
            )
            release.write_text("release", encoding="utf-8")
            holder_stdout, holder_stderr = holder.communicate(timeout=5)
            contender_stdout, contender_stderr = contender.communicate(timeout=5)

            self.assertEqual(holder.returncode, 0, holder_stdout + holder_stderr)
            self.assertEqual(
                contender.returncode, 0, contender_stdout + contender_stderr
            )
            self.assertTrue(acquired.exists())
            self.assertFalse((root / ".models-manifest.lock").exists())

    def test_releases_after_body_exception_without_creating_residue(self) -> None:
        # Catches masking the body error, retaining the OS lock, or leaking a lock file.
        module = load_platform_file_module()
        lock = self._lock_function(module)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "manifest.toml"

            with self.assertRaisesRegex(RuntimeError, "body failed"):
                with lock(target):
                    raise RuntimeError("body failed")
            with lock(target):
                pass

            self.assertEqual(list(root.iterdir()), [])

    def test_rejects_missing_or_symlink_parent_without_creating_it(self) -> None:
        # Catches silently locking a different directory or creating ambient path state.
        module = load_platform_file_module()
        lock = self._lock_function(module)
        error_type = AtomicReplaceTests._error_type(module)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            missing_parent = root / "missing"
            with self.assertRaises(error_type):
                with lock(missing_parent / "manifest.toml"):
                    pass
            self.assertFalse(missing_parent.exists())

            real_parent = root / "real"
            real_parent.mkdir()
            linked_parent = root / "linked"
            try:
                linked_parent.symlink_to(real_parent, target_is_directory=True)
            except OSError as error:
                self.skipTest(f"directory symlink creation is unavailable: {error}")
            with self.assertRaises(error_type):
                with lock(linked_parent / "manifest.toml"):
                    pass
            self.assertEqual(list(real_parent.iterdir()), [])

    def test_windows_mutex_abandonment_fails_closed_then_allows_retry(self) -> None:
        # Catches entering after a crashed owner or leaking ownership while rejecting it.
        module = load_platform_file_module()
        lock = self._lock_function(module)
        error_type = AtomicReplaceTests._error_type(module)
        kernel = _FakeWindowsKernel()

        def load_kernel(_name: str, *, use_last_error: bool) -> _FakeWindowsKernel:
            if not use_last_error:
                raise AssertionError("WinDLL must preserve the native error code")
            return kernel

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "manifest.toml"
            with (
                mock.patch.object(module, "_WINDOWS", True),
                mock.patch.object(
                    module.ctypes,
                    "WinDLL",
                    side_effect=load_kernel,
                    create=True,
                ),
            ):
                kernel.abandon_next = True
                with self.assertRaisesRegex(error_type, "terminated unexpectedly"):
                    with lock(target):
                        self.fail(
                            "an abandoned mutex must not enter the protected body"
                        )
                with lock(target):
                    pass

            self.assertFalse(kernel.held)
            self.assertEqual(kernel.open_handles, 0)
            self.assertEqual(list(root.iterdir()), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
