#!/usr/bin/env python3
"""Cross-platform advisory locking and durable atomic file replacement.

The lock is deliberately directory-scoped. POSIX systems lock the stable
directory inode directly; Windows systems use a named kernel mutex derived
from the canonical directory path. Neither backend creates a lock artifact,
so process termination cannot leave stale lock files behind.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
import ctypes
import errno
import hashlib
import os
from pathlib import Path
import secrets
import stat
import sys
import tempfile
from typing import cast


_WINDOWS = os.name == "nt"
_RENAME_EXCHANGE = 2


class PlatformFileError(RuntimeError):
    """A file target failed a safety precondition."""


class PlatformFileDurabilityUnknown(RuntimeError):
    """The replacement is installed, but its durable persistence is unknown."""

    def __init__(self, path: Path) -> None:
        self.path = path
        super().__init__(f"replacement installed but durability is unknown: {path}")


def _directory_state(parent: Path) -> os.stat_result:
    """Validate a lock directory without following its final component."""
    try:
        directory_state = parent.lstat()
    except OSError as error:
        raise PlatformFileError(
            f"advisory lock directory is unavailable: {parent}"
        ) from error
    if not stat.S_ISDIR(directory_state.st_mode):
        raise PlatformFileError(
            f"advisory lock parent is not a regular directory: {parent}"
        )
    return directory_state


@contextmanager
def _posix_directory_lock(parent: Path, expected: os.stat_result) -> Iterator[None]:
    """Hold an exclusive advisory lock on one stable directory inode."""
    import fcntl

    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor = os.open(parent, flags)
    acquired = False
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISDIR(opened.st_mode) or (opened.st_dev, opened.st_ino) != (
            expected.st_dev,
            expected.st_ino,
        ):
            raise PlatformFileError(
                f"advisory lock directory changed during acquisition: {parent}"
            )
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        acquired = True
        yield
    finally:
        try:
            if acquired:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def _windows_mutex_name(parent: Path) -> str:
    """Derive a fixed-size global mutex name from a canonical directory path."""
    canonical = os.path.normcase(os.path.realpath(os.path.abspath(parent)))
    digest = hashlib.sha256(os.fsencode(canonical)).hexdigest()
    return f"Global\\the-one-model-cache-{digest}"


def _windows_last_error(operation: str) -> OSError:
    get_last_error = cast(
        Callable[[], int] | None, getattr(ctypes, "get_last_error", None)
    )
    error_code = get_last_error() if get_last_error is not None else 0
    return OSError(error_code, f"{operation} failed with Windows error {error_code}")


@contextmanager
def _windows_directory_lock(parent: Path) -> Iterator[None]:
    """Hold a named Windows kernel mutex until the context exits."""
    win_dll = getattr(ctypes, "WinDLL", None)
    if win_dll is None:
        raise PlatformFileError("Windows kernel locking API is unavailable")
    kernel32 = win_dll("kernel32", use_last_error=True)
    create_mutex = kernel32.CreateMutexW
    create_mutex.argtypes = (ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p)
    create_mutex.restype = ctypes.c_void_p
    wait_for_single_object = kernel32.WaitForSingleObject
    wait_for_single_object.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
    wait_for_single_object.restype = ctypes.c_uint32
    release_mutex = kernel32.ReleaseMutex
    release_mutex.argtypes = (ctypes.c_void_p,)
    release_mutex.restype = ctypes.c_int
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = (ctypes.c_void_p,)
    close_handle.restype = ctypes.c_int

    handle = create_mutex(None, 0, _windows_mutex_name(parent))
    if not handle:
        raise _windows_last_error("CreateMutexW")
    acquired = False
    try:
        wait_result = wait_for_single_object(handle, 0xFFFFFFFF)
        if wait_result == 0x00000080:
            acquired = True
            raise PlatformFileError(
                f"previous advisory lock owner terminated unexpectedly: {parent}"
            )
        if wait_result != 0x00000000:
            raise _windows_last_error("WaitForSingleObject")
        acquired = True
        yield
    finally:
        try:
            if acquired and not release_mutex(handle):
                raise _windows_last_error("ReleaseMutex")
        finally:
            if not close_handle(handle):
                raise _windows_last_error("CloseHandle")


@contextmanager
def advisory_lock(path: Path) -> Iterator[None]:
    """Serialize cooperating file operations within the target's directory.

    The target itself need not exist. Its immediate parent must already be a
    real directory rather than a symlink. Locks are released by the operating
    system if the process exits, and no filesystem lock artifact is created.
    """
    target = Path(path)
    parent = target.parent
    directory_state = _directory_state(parent)
    if _WINDOWS:
        with _windows_directory_lock(parent):
            yield
    else:
        with _posix_directory_lock(parent, directory_state):
            yield


def _regular_file_state(path: Path) -> os.stat_result:
    """Return one non-symlink, single-link regular-file state."""
    try:
        file_state = path.lstat()
    except OSError as error:
        raise PlatformFileError(
            f"atomic replacement target is unavailable: {path}"
        ) from error
    return _validated_regular_file_state(file_state, path)


def _validated_regular_file_state(
    file_state: os.stat_result, path: Path
) -> os.stat_result:
    """Validate an already descriptor-anchored target state."""
    if not stat.S_ISREG(file_state.st_mode):
        raise PlatformFileError(
            f"atomic replacement target is not a regular non-symlink file: {path}"
        )
    if file_state.st_nlink != 1:
        raise PlatformFileError(
            f"atomic replacement target must have exactly one hard link: {path}"
        )
    return file_state


def _regular_file_state_at(
    parent_descriptor: int, name: str, path: Path
) -> os.stat_result:
    """Return a regular-file state anchored to an already verified directory."""
    try:
        file_state = os.stat(
            name,
            dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
    except OSError as error:
        raise PlatformFileError(
            f"atomic replacement target is unavailable: {path}"
        ) from error
    return _validated_regular_file_state(file_state, path)


def _state_signature(file_state: os.stat_result) -> tuple[int, ...]:
    """Capture fields that expose replacement or mutation of the target."""
    return (
        file_state.st_dev,
        file_state.st_ino,
        file_state.st_mode,
        file_state.st_nlink,
        file_state.st_size,
        file_state.st_mtime_ns,
        file_state.st_ctime_ns,
    )


def _sync_parent_directory(parent: Path) -> None:
    """Persist a directory-entry replacement through its reopened parent."""
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
            raise PlatformFileError(f"replacement parent is not a directory: {parent}")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _sync_replaced_file(path: Path) -> None:
    """Flush the installed file on platforms without directory-fd syncing."""
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_CLOEXEC", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _verify_temporary_file(path: Path, expected: os.stat_result) -> None:
    """Reject a temp pathname replaced after its exclusive creation."""
    try:
        current = path.lstat()
    except OSError as error:
        raise PlatformFileError(f"atomic temporary file changed: {path}") from error
    if (
        not stat.S_ISREG(current.st_mode)
        or current.st_nlink != 1
        or (current.st_dev, current.st_ino) != (expected.st_dev, expected.st_ino)
        or current.st_size != expected.st_size
    ):
        raise PlatformFileError(f"atomic temporary file changed: {path}")


def _verify_temporary_file_at(
    parent_descriptor: int, path: Path, expected: os.stat_result
) -> None:
    """Reject a temp entry that no longer names the held inode beneath its parent fd."""
    try:
        current = os.stat(
            path.name,
            dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
    except OSError as error:
        raise PlatformFileError(f"atomic temporary file changed: {path}") from error
    if (
        not stat.S_ISREG(current.st_mode)
        or current.st_nlink != 1
        or (current.st_dev, current.st_ino) != (expected.st_dev, expected.st_ino)
        or current.st_size != expected.st_size
    ):
        raise PlatformFileError(f"atomic temporary file changed: {path}")


def _verified_descriptor_content_state(
    descriptor: int,
    path: Path,
    *,
    expected_size: int,
    expected_sha256: bytes,
) -> os.stat_result:
    """Bind one held regular descriptor to exact bytes and stable mutable state."""
    before = _validated_regular_file_state(os.fstat(descriptor), path)
    if before.st_size != expected_size:
        raise PlatformFileError(f"atomic temporary file changed: {path}")
    original_offset = os.lseek(descriptor, 0, os.SEEK_CUR)
    digest = hashlib.sha256()
    size = 0
    try:
        os.lseek(descriptor, 0, os.SEEK_SET)
        while chunk := os.read(descriptor, 1024 * 1024):
            size += len(chunk)
            if size > expected_size:
                raise PlatformFileError(f"atomic temporary file changed: {path}")
            digest.update(chunk)
    finally:
        os.lseek(descriptor, original_offset, os.SEEK_SET)
    after = _validated_regular_file_state(os.fstat(descriptor), path)
    if (
        _state_signature(before) != _state_signature(after)
        or size != expected_size
        or digest.digest() != expected_sha256
    ):
        raise PlatformFileError(f"atomic temporary file changed: {path}")
    return after


def _verified_installed_content_state(
    path: Path,
    expected_identity: os.stat_result,
    *,
    expected_size: int,
    expected_sha256: bytes,
) -> os.stat_result:
    """Reopen a published Windows candidate and bind its path, identity, and bytes."""
    path_before = _regular_file_state(path)
    flags = (
        os.O_RDONLY
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor = os.open(path, flags)
    try:
        descriptor_state = _verified_descriptor_content_state(
            descriptor,
            path,
            expected_size=expected_size,
            expected_sha256=expected_sha256,
        )
    finally:
        os.close(descriptor)
    path_after = _regular_file_state(path)
    if (
        not _same_file_identity(path_before, expected_identity)
        or not _same_file_identity(descriptor_state, expected_identity)
        or _state_signature(path_before) != _state_signature(descriptor_state)
        or _state_signature(path_before) != _state_signature(path_after)
    ):
        raise PlatformFileError(f"atomic temporary file changed: {path}")
    return path_after


def _same_file_identity(left: os.stat_result, right: os.stat_result) -> bool:
    """Return whether two states describe the same filesystem object."""
    return (left.st_dev, left.st_ino) == (right.st_dev, right.st_ino)


def _report_preserved_entry(
    path: Path, *, kind: str, parent_descriptor: int = -1
) -> None:
    """Report a retained entry without reopening it for deletion."""
    try:
        if parent_descriptor >= 0:
            os.stat(
                path.name,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
        else:
            path.lstat()
    except FileNotFoundError:
        return
    except OSError:
        pass
    print(
        f"warning: preserved {kind} at {path}; "
        + "safe identity-bound deletion is unavailable",
        file=sys.stderr,
    )


def _unused_windows_backup_path(target: Path) -> Path:
    """Choose an absent backup name without deleting a reopened pathname."""
    for _ in range(128):
        candidate = target.parent / f".{target.name}.{secrets.token_hex(16)}.rollback"
        try:
            candidate.lstat()
        except FileNotFoundError:
            return candidate
        except OSError as error:
            raise PlatformFileError(
                f"could not inspect Windows recovery path: {candidate}"
            ) from error
    raise PlatformFileError("could not allocate a Windows recovery path")


def _rename_exchange_at(
    parent_descriptor: int,
    source_name: str,
    target_name: str,
) -> None:
    """Atomically exchange two entries beneath one verified POSIX directory."""
    if sys.platform.startswith("linux"):
        library = ctypes.CDLL(None, use_errno=True)
        rename_exchange = getattr(library, "renameat2", None)
        operation = "renameat2(RENAME_EXCHANGE)"
    elif sys.platform == "darwin":
        library = ctypes.CDLL(None, use_errno=True)
        rename_exchange = getattr(library, "renameatx_np", None)
        operation = "renameatx_np(RENAME_SWAP)"
    else:
        rename_exchange = None
        operation = "native atomic exchange"
    if rename_exchange is None:
        raise PlatformFileError(
            f"secure atomic replacement is unsupported: {operation} is unavailable"
        )

    rename_exchange.argtypes = (
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    )
    rename_exchange.restype = ctypes.c_int
    ctypes.set_errno(0)
    result = rename_exchange(
        parent_descriptor,
        os.fsencode(source_name),
        parent_descriptor,
        os.fsencode(target_name),
        _RENAME_EXCHANGE,
    )
    if result == 0:
        return

    error_code = ctypes.get_errno()
    error = OSError(error_code, os.strerror(error_code))
    unavailable_errors = {
        errno.EINVAL,
        errno.ENOSYS,
        getattr(errno, "ENOTSUP", errno.EOPNOTSUPP),
        errno.EOPNOTSUPP,
    }
    if error_code in unavailable_errors:
        raise PlatformFileError(
            f"secure atomic replacement is unsupported: {operation} failed"
        ) from error
    raise error


def _windows_replace_file_with_backup(
    source: Path,
    target: Path,
    backup: Path | None,
) -> None:
    """Atomically replace a Windows target while optionally retaining its prior entry."""
    if not _WINDOWS:
        raise PlatformFileError("Windows replacement requested on a non-Windows host")

    win_dll = getattr(ctypes, "WinDLL", None)
    if win_dll is None:
        raise PlatformFileError("Windows ReplaceFileW API is unavailable")
    kernel32 = win_dll("kernel32", use_last_error=True)
    replace_file = kernel32.ReplaceFileW
    replace_file.argtypes = (
        ctypes.c_wchar_p,
        ctypes.c_wchar_p,
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_void_p,
    )
    replace_file.restype = ctypes.c_int
    if not replace_file(
        os.path.abspath(target),
        os.path.abspath(source),
        os.path.abspath(backup) if backup is not None else None,
        0,
        None,
        None,
    ):
        raise PlatformFileError(
            f"secure Windows replacement failed: {target}"
        ) from _windows_last_error("ReplaceFileW")


def atomic_replace_bytes(path: Path, content: bytes) -> None:
    """Durably replace an existing regular file while preserving its mode.

    The caller should hold :func:`advisory_lock` for the target directory.
    A same-directory exclusive temporary file guarantees that the final
    replacement stays on one filesystem. Failures before replacement leave the
    original untouched. A failure while syncing after replacement raises
    :class:`PlatformFileDurabilityUnknown`, because the new bytes are visible
    but crash persistence is unconfirmed. Temporary and recovery names are retained
    and reported whenever removal would require an unsafe pathname reopen.
    """
    target = Path(path)
    parent_descriptor = -1
    if _WINDOWS:
        initial_state = _regular_file_state(target)
    else:
        expected_parent = _directory_state(target.parent)
        parent_descriptor = os.open(
            target.parent,
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0),
        )
        opened_parent = os.fstat(parent_descriptor)
        if not stat.S_ISDIR(opened_parent.st_mode) or (
            opened_parent.st_dev,
            opened_parent.st_ino,
        ) != (expected_parent.st_dev, expected_parent.st_ino):
            os.close(parent_descriptor)
            raise PlatformFileError(
                f"atomic replacement parent changed during opening: {target.parent}"
            )
        try:
            initial_state = _regular_file_state_at(
                parent_descriptor,
                target.name,
                target,
            )
        except BaseException:
            os.close(parent_descriptor)
            raise
    initial_signature = _state_signature(initial_state)
    original_mode = stat.S_IMODE(initial_state.st_mode)
    descriptor = -1
    temporary: Path | None = None
    temporary_state: os.stat_result | None = None
    windows_backup: Path | None = None
    expected_content_sha256 = hashlib.sha256(content).digest()
    replacement_committed = False
    try:
        try:
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
            )
            temporary = Path(temporary_name)
            with os.fdopen(descriptor, "wb", closefd=False) as output:
                output.write(content)
                output.flush()
                if not _WINDOWS:
                    os.fchmod(output.fileno(), original_mode)
                os.fsync(output.fileno())
                temporary_state = os.fstat(output.fileno())

            if temporary_state is None:
                raise PlatformFileError("atomic temporary file state was not captured")
            if _WINDOWS:
                _verify_temporary_file(temporary, temporary_state)
                os.chmod(temporary, original_mode)
                _sync_replaced_file(temporary)
            else:
                _verify_temporary_file_at(parent_descriptor, temporary, temporary_state)
            temporary_state = _verified_descriptor_content_state(
                descriptor,
                temporary,
                expected_size=len(content),
                expected_sha256=expected_content_sha256,
            )
            if _WINDOWS:
                _verify_temporary_file(temporary, temporary_state)
                current_state = _regular_file_state(target)
            else:
                _verify_temporary_file_at(parent_descriptor, temporary, temporary_state)
                current_state = _regular_file_state_at(
                    parent_descriptor,
                    target.name,
                    target,
                )
            if _state_signature(current_state) != initial_signature:
                raise PlatformFileError(
                    f"atomic replacement target changed during operation: {target}"
                )

            if _WINDOWS:
                _verify_temporary_file(temporary, temporary_state)
                # CRT file descriptors do not reliably share Windows delete/rename
                # access. ReplaceFileW supplies transactional rollback protection for
                # the identity check after this descriptor is closed.
                os.close(descriptor)
                descriptor = -1
                windows_backup = _unused_windows_backup_path(target)
                _windows_replace_file_with_backup(temporary, target, windows_backup)
                replacement_committed = True
                windows_installed_state: os.stat_result | None = None
                windows_displaced_state: os.stat_result | None = None
                windows_validation_error: BaseException | None = None
                try:
                    windows_installed_state = _verified_installed_content_state(
                        target,
                        temporary_state,
                        expected_size=len(content),
                        expected_sha256=expected_content_sha256,
                    )
                    windows_displaced_state = _regular_file_state(windows_backup)
                except BaseException as error:
                    windows_validation_error = error

                candidate_installed = windows_installed_state is not None
                original_displaced = (
                    windows_displaced_state is not None
                    and _same_file_identity(windows_displaced_state, initial_state)
                )
                if not candidate_installed or not original_displaced:
                    try:
                        _windows_replace_file_with_backup(windows_backup, target, None)
                        restored_state = _regular_file_state(target)
                    except BaseException as rollback_error:
                        raise PlatformFileError(
                            "atomic Windows publication rollback failed; the prior "
                            + f"target may remain under {windows_backup}"
                        ) from rollback_error
                    expected_restored = windows_displaced_state or initial_state
                    if not _same_file_identity(restored_state, expected_restored):
                        raise PlatformFileError(
                            "atomic Windows publication rollback did not restore: "
                            + str(target)
                        )
                    _sync_replaced_file(target)
                    _sync_parent_directory(target.parent)
                    replacement_committed = False
                    windows_backup = None
                    if not candidate_installed:
                        raise PlatformFileError(
                            "atomic temporary file changed during publication: "
                            + str(temporary)
                        ) from windows_validation_error
                    raise PlatformFileError(
                        f"atomic replacement target changed during publication: {target}"
                    ) from windows_validation_error

                temporary = None
            else:
                _verify_temporary_file_at(parent_descriptor, temporary, temporary_state)
                _rename_exchange_at(parent_descriptor, temporary.name, target.name)
                replacement_committed = True
                installed_state: os.stat_result | None = None
                displaced_state: os.stat_result | None = None
                validation_error: BaseException | None = None
                try:
                    installed_state = _regular_file_state_at(
                        parent_descriptor,
                        target.name,
                        target,
                    )
                    displaced_state = _regular_file_state_at(
                        parent_descriptor,
                        temporary.name,
                        temporary,
                    )
                    verified_installed = _verified_descriptor_content_state(
                        descriptor,
                        target,
                        expected_size=len(content),
                        expected_sha256=expected_content_sha256,
                    )
                    if _state_signature(installed_state) != _state_signature(
                        verified_installed
                    ):
                        raise PlatformFileError(
                            f"atomic temporary file changed during publication: {temporary}"
                        )
                except BaseException as error:
                    validation_error = error

                candidate_installed = (
                    installed_state is not None
                    and _same_file_identity(installed_state, temporary_state)
                    and validation_error is None
                )
                original_displaced = (
                    displaced_state is not None
                    and _same_file_identity(displaced_state, initial_state)
                )
                if not candidate_installed or not original_displaced:
                    try:
                        _rename_exchange_at(
                            parent_descriptor, temporary.name, target.name
                        )
                        restored_state = _regular_file_state_at(
                            parent_descriptor,
                            target.name,
                            target,
                        )
                    except BaseException as rollback_error:
                        expected_recovery = displaced_state or initial_state
                        try:
                            recovery_state = _regular_file_state_at(
                                parent_descriptor,
                                temporary.name,
                                temporary,
                            )
                            _ = _same_file_identity(recovery_state, expected_recovery)
                        except (OSError, PlatformFileError):
                            pass
                        raise PlatformFileError(
                            "atomic publication rollback failed; the prior target may "
                            + f"remain under {temporary}"
                        ) from rollback_error
                    expected_restored = displaced_state or initial_state
                    if not _same_file_identity(restored_state, expected_restored):
                        raise PlatformFileError(
                            f"atomic publication rollback did not restore: {target}"
                        )
                    os.fsync(parent_descriptor)
                    replacement_committed = False
                    if not candidate_installed:
                        raise PlatformFileError(
                            "atomic temporary file changed during publication: "
                            + str(temporary)
                        ) from validation_error
                    raise PlatformFileError(
                        f"atomic replacement target changed during publication: {target}"
                    ) from validation_error

            if _WINDOWS:
                _sync_replaced_file(target)
            else:
                os.fsync(parent_descriptor)
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            if temporary is not None:
                _report_preserved_entry(
                    temporary,
                    kind="atomic replacement recovery entry",
                    parent_descriptor=-1 if _WINDOWS else parent_descriptor,
                )
            if windows_backup is not None:
                _report_preserved_entry(
                    windows_backup,
                    kind="Windows atomic replacement recovery entry",
                )
            if parent_descriptor >= 0:
                os.close(parent_descriptor)
    except PlatformFileDurabilityUnknown:
        raise
    except BaseException as error:
        if replacement_committed:
            raise PlatformFileDurabilityUnknown(target) from error
        raise


__all__ = [
    "PlatformFileDurabilityUnknown",
    "PlatformFileError",
    "advisory_lock",
    "atomic_replace_bytes",
]
