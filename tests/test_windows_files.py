"""Path syntax tests run everywhere; native tests require actual Windows APIs."""

from __future__ import annotations

import importlib
import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from phalanx.platforms import windows_files
from phalanx.platforms.windows_files import (
    WindowsPathError,
    ensure_private_directory,
    guard_local_file,
    store_private_bytes,
    validate_local_path,
)


@pytest.mark.parametrize(
    "path",
    [
        r"\\server\share\data.db",
        r"\\wsl.localhost\Ubuntu\history.db",
        r"\\?\C:\data.db",
        r"\\.\C:\data.db",
        r"C:data.db",
        r"data.db",
        r"C:\data.db:secret",
        r"C:\CON.json",
        r"C:\dir.\data.db",
        r"C:\dir \data.db",
        r"C:\dir\..\data.db",
        r"C:\dir\NUL",
    ],
)
def test_windows_path_syntax_rejects_ambiguous_nonlocal_and_device_paths(path: str) -> None:
    with pytest.raises(WindowsPathError):
        validate_local_path(path)


def test_windows_path_syntax_accepts_local_unicode_spaces() -> None:
    assert str(validate_local_path(r"C:\Users\테스트 사용자\저장 결과.json")) == (
        r"C:\Users\테스트 사용자\저장 결과.json"
    )


@pytest.mark.parametrize("query_fails", [False, True])
def test_win32_closes_non_context_manager_token(
    monkeypatch: pytest.MonkeyPatch, query_fails: bool
) -> None:
    class NativeError(Exception):
        winerror = 5

    class Token:
        closes = 0

        def Close(self) -> None:
            self.closes += 1

    token = Token()  # PyHANDLE has Close(), but no context-manager protocol.

    def get_token_information(handle: Any, _kind: int) -> tuple[str]:
        assert handle is token and token.closes == 0
        if query_fails:
            raise NativeError()
        return ("user-sid",)

    modules = {
        "win32file": SimpleNamespace(),
        "win32security": SimpleNamespace(
            OpenProcessToken=lambda *_: token,
            GetTokenInformation=get_token_information,
            TokenUser=1,
            ConvertSidToStringSid=lambda sid: sid,
        ),
        "win32api": SimpleNamespace(GetCurrentProcess=lambda: 42),
        "pywintypes": SimpleNamespace(error=NativeError),
    }
    with monkeypatch.context() as patch:
        patch.setattr(windows_files.importlib, "import_module", modules.__getitem__)
        if query_fails:
            with pytest.raises(WindowsPathError, match="5"):
                windows_files._Win32()
        else:
            assert windows_files._Win32().user_sid == "user-sid"
    assert token.closes == 1


windows_only = pytest.mark.skipif(sys.platform != "win32", reason="requires native Windows Win32")


@contextmanager
def _open_native_directory(api: Any, path: Path, access: int) -> Iterator[Any]:
    # Deliberately permit all sharing: a failure must come from the guard.
    handle = api.file.CreateFile(str(path), access, 0x07, None, 3, 0x02200000, None)
    try:
        yield handle
    finally:
        handle.Close()


@windows_only
@pytest.mark.parametrize("access", [0x02, 0x04, 0x10000], ids=["add-file", "add-dir", "delete"])
@pytest.mark.parametrize("ancestor", [False, True], ids=["leaf", "ancestor"])
def test_windows_directory_guard_alone_denies_conflicting_access(
    tmp_path: Path, access: int, ancestor: bool
) -> None:
    api = windows_files._api()
    directory = tmp_path / "guarded" / "nested"
    directory.mkdir(parents=True)
    attacked = directory.parent if ancestor else directory
    # No child file exists or is open: an input-file handle cannot mask a broken
    # metadata-only directory guard by separately blocking ancestor deletion.
    with windows_files._directory_guard(api, directory):
        with (
            pytest.raises(api.types.error) as failure,
            _open_native_directory(api, attacked, access),
        ):
            pytest.fail("guard allowed conflicting directory access")
        assert failure.value.winerror == 32  # ERROR_SHARING_VIOLATION, not an ACL denial
        with _open_native_directory(api, attacked, 0x01):
            pass  # compatible directory readers remain allowed
    with _open_native_directory(api, attacked, access):
        pass  # proves the same request is permitted once the guard is released


@windows_only
@pytest.mark.parametrize("access", [0x02, 0x04, 0x10000], ids=["add-file", "add-dir", "delete"])
def test_windows_directory_guard_rejects_preexisting_conflicting_access(
    tmp_path: Path, access: int
) -> None:
    api = windows_files._api()
    directory = tmp_path / "guarded"
    directory.mkdir()
    with _open_native_directory(api, directory, access):
        with (
            pytest.raises(api.types.error) as failure,
            windows_files._directory_guard(api, directory),
        ):
            pytest.fail("guard accepted an existing conflicting directory handle")
        assert failure.value.winerror == 32
    with windows_files._directory_guard(api, directory):
        pass
    # A failed acquisition must also close every already-acquired ancestor handle.
    moved = tmp_path.with_name(tmp_path.name + "-released")
    tmp_path.rename(moved)
    moved.rename(tmp_path)


@windows_only
@pytest.mark.parametrize("ancestor", [False, True], ids=["leaf", "ancestor"])
def test_windows_directory_guard_alone_denies_rename_and_path_replacement(
    tmp_path: Path, ancestor: bool
) -> None:
    api = windows_files._api()
    directory = tmp_path / "guarded" / "nested"
    directory.mkdir(parents=True)
    attacked = directory.parent if ancestor else directory
    displaced = attacked.with_name("displaced")
    redirected = tmp_path / "redirected"
    redirected.mkdir()
    junction = importlib.import_module("_winapi").CreateJunction
    with windows_files._directory_guard(api, directory):
        with pytest.raises(OSError) as failure:
            attacked.rename(displaced)
            junction(str(redirected), str(attacked))
        assert failure.value.winerror == 32
        assert attacked.is_dir()
        assert not attacked.is_junction()
        assert not displaced.exists()
        # Removing an empty leaf is a second way to free the name for a junction.
        with pytest.raises(OSError) as removal:
            directory.rmdir()
        assert removal.value.winerror == 32
        assert list(directory.iterdir()) == []
    attacked.rename(displaced)
    junction(str(redirected), str(attacked))
    try:
        assert attacked.is_junction()
        with (
            pytest.raises(WindowsPathError, match="reparse"),
            windows_files._directory_guard(api, attacked),
        ):
            pytest.fail("guard followed a replaced path")
    finally:
        attacked.rmdir()
        displaced.rename(attacked)


@windows_only
@pytest.mark.parametrize("filename", ["결과.json", "결과 📊.json"])
def test_windows_directory_guard_allows_child_save_and_atomic_replace(
    tmp_path: Path, filename: str
) -> None:
    api = windows_files._api()
    directory = ensure_private_directory(tmp_path / "private")
    target = directory / filename
    original = b'{"version":1}\r\n'
    replacement = b'{"version":2}\r\n'
    # Hold only ancestor directory handles before starting the application's save.
    with windows_files._directory_guard(api, directory):
        assert store_private_bytes(target, original) == target
        with guard_local_file(target, require_private=True) as guarded:
            assert guarded.read_bytes(100) == original
        assert store_private_bytes(target, replacement, replace=True) == target
        with guard_local_file(target, require_private=True) as guarded:
            assert guarded.read_bytes(100) == replacement
        assert list(directory.iterdir()) == [target]
    directory.rename(tmp_path / "released")


@windows_only
def test_windows_private_acl_and_no_overwrite(tmp_path: Path) -> None:
    directory = ensure_private_directory(tmp_path / "private")
    result = directory / "결과.json"
    payload = b'{"exact":true}\r\n'
    assert store_private_bytes(result, payload) == result
    with guard_local_file(result, require_private=True) as guarded:
        assert guarded.read_bytes(100) == payload
    with pytest.raises(FileExistsError, match="덮어"):
        store_private_bytes(result, b"replacement")
    assert result.read_bytes() == payload
    assert list(directory.iterdir()) == [result]


@windows_only
def test_windows_guard_denies_write_delete_ancestor_rename_and_hardlinks(tmp_path: Path) -> None:
    directory = tmp_path / "guarded"
    directory.mkdir()
    source = directory / "input.json"
    source.write_bytes(b"{}")
    with guard_local_file(source) as guarded:
        assert guarded.read_bytes(10) == b"{}"
        with pytest.raises(OSError):
            source.write_bytes(b"replacement")
        with pytest.raises(OSError):
            source.unlink()
        with pytest.raises(OSError):
            directory.rename(tmp_path / "moved")
    alias = directory / "hardlink.json"
    os.link(source, alias)
    with pytest.raises(WindowsPathError, match="하드 링크"), guard_local_file(source):
        pass


@windows_only
@pytest.mark.parametrize("stage", ["write", "flush", "acl", "rename"])
def test_windows_failed_write_preserves_destination_and_removes_temp_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    api = windows_files._api()
    result = store_private_bytes(tmp_path / "result.json", b"preserve")

    def fail(*_args: Any, **_kwargs: Any) -> None:
        raise OSError(f"injected {stage} failure")

    with monkeypatch.context() as patch:
        patch.setattr(windows_files, "_api", lambda: api)
        if stage == "rename":
            patch.setattr(windows_files, "_rename_handle", fail)
        elif stage == "acl":
            patch.setattr(api, "check_private", fail)
        else:
            patch.setattr(api.file, "WriteFile" if stage == "write" else "FlushFileBuffers", fail)
        with pytest.raises(OSError, match="injected"):
            store_private_bytes(result, b"replacement", replace=True)
    assert result.read_bytes() == b"preserve"
    assert list(tmp_path.iterdir()) == [result]
    with guard_local_file(result, require_private=True) as guarded:
        assert guarded.read_bytes(100) == b"preserve"
    moved = tmp_path.with_name(tmp_path.name + "-released")
    tmp_path.rename(moved)
    moved.rename(tmp_path)


@windows_only
def test_windows_rejects_public_file_acl(tmp_path: Path) -> None:
    api = windows_files._api()
    target = store_private_bytes(tmp_path / "private.json", b"{}")
    descriptor = api.security.GetFileSecurity(str(target), 0x04)
    dacl = descriptor.GetSecurityDescriptorDacl()
    everyone = api.security.ConvertStringSidToSid("S-1-1-0")
    dacl.AddAccessAllowedAce(2, 0x01, everyone)  # FILE_READ_DATA, an actual public read ACE
    descriptor.SetSecurityDescriptorDacl(True, dacl, False)
    api.security.SetFileSecurity(str(target), 0x04, descriptor)
    with (
        pytest.raises(WindowsPathError, match="ACL"),
        guard_local_file(target, require_private=True),
    ):
        pass


@windows_only
def test_windows_rejects_junction_ancestor_for_read_and_write(tmp_path: Path) -> None:
    target = tmp_path / "real"
    target.mkdir()
    source = target / "source.json"
    source.write_bytes(b"{}")
    alias = tmp_path / "junction"
    # CPython's junction helper needs no symbolic-link privilege.
    importlib.import_module("_winapi").CreateJunction(str(target), str(alias))
    try:
        with (
            pytest.raises(WindowsPathError, match="reparse"),
            guard_local_file(alias / source.name),
        ):
            pass
        with pytest.raises(WindowsPathError, match="reparse"):
            store_private_bytes(alias / "output.json", b"{}")
        assert not (target / "output.json").exists()
    finally:
        alias.rmdir()


@pytest.mark.parametrize(
    ("code", "exception"),
    [
        (2, FileNotFoundError),
        (3, FileNotFoundError),
        (183, FileExistsError),
        (32, WindowsPathError),
    ],
)
def test_native_exception_translation_catches_non_oserror(
    code: int, exception: type[Exception]
) -> None:
    class NativeError(Exception):
        def __init__(self, winerror: int) -> None:
            self.winerror = winerror

    api = SimpleNamespace(types=SimpleNamespace(error=NativeError))
    with pytest.raises(exception), windows_files._translate_errors(api):
        raise NativeError(code)
