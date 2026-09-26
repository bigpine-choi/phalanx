"""Native Windows file guards and private, atomic publication.

No Win32 module is imported until a Windows operation is requested. Input handles
allow other readers but deny writes and deletion for the full operation. Directory
handles deny writing and deletion, pinning every ancestor against rename/reparse replacement.
"""

from __future__ import annotations

import ctypes
import importlib
import re
import secrets
import sys
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any


class WindowsPathError(OSError):
    """A path, ACL, or native file operation did not meet the local-file policy."""


def validate_local_path(value: str) -> PureWindowsPath:
    """Validate Windows syntax without resolving links or accessing the filesystem."""
    path = PureWindowsPath(value)
    if (
        not path.is_absolute()
        or len(path.drive) != 2
        or path.drive[1] != ":"
        or not path.drive[0].isascii()
        or not path.drive[0].isalpha()
        or value.startswith(("\\\\", "//"))
    ):
        raise WindowsPathError("Windows 로컬 드라이브의 절대 경로만 지원합니다.")
    reserved = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
    reserved.update(
        f"{kind}{number}" for kind in ("COM", "LPT") for number in (*range(1, 10), "¹", "²", "³")
    )
    for part in path.parts[1:]:
        if (
            part in (".", "..")
            or part.endswith((" ", "."))
            or any(ord(character) < 32 or character in '<>:"|?*' for character in part)
            or part.split(".", 1)[0].rstrip(" ").upper() in reserved
        ):
            raise WindowsPathError("Windows 경로에 지원하지 않는 이름이 있습니다.")
    return path


def _api() -> Any:
    if sys.platform != "win32":
        raise WindowsPathError("이 파일 작업은 네이티브 Windows Python에서만 지원합니다.")
    try:
        return _Win32()
    except ImportError:
        raise WindowsPathError(
            "Windows 파일 보호에 pywin32가 필요합니다. desktop extra를 설치하세요."
        ) from None


@contextmanager
def _translate_errors(api: Any) -> Iterator[None]:
    # pywintypes.error derives directly from Exception, not from OSError.
    try:
        yield
    except api.types.error as exc:
        code = exc.winerror
        if code in (2, 3):
            raise FileNotFoundError("Windows 파일 또는 디렉터리가 없습니다.") from exc
        if code in (80, 183):
            raise FileExistsError("기존 파일을 덮어쓰지 않습니다.") from exc
        raise WindowsPathError(f"Windows 파일 보호 작업이 실패했습니다 (오류 {code}).") from exc


class _Win32:
    def __init__(self) -> None:
        self.file = importlib.import_module("win32file")
        self.security = importlib.import_module("win32security")
        self.api = importlib.import_module("win32api")
        self.types = importlib.import_module("pywintypes")
        with _translate_errors(self):
            token = self.security.OpenProcessToken(self.api.GetCurrentProcess(), 0x0008)
            try:
                self.user_sid = self.security.GetTokenInformation(token, self.security.TokenUser)[0]
            finally:
                token.Close()
        self.allowed_sids = {
            self.security.ConvertSidToStringSid(self.user_sid),
            "S-1-5-18",  # LocalSystem
            "S-1-5-32-544",  # Builtin Administrators
        }

    def private_attributes(self, *, directory: bool) -> Any:
        security = self.security
        dacl = security.ACL()
        inherit = 0x03 if directory else 0  # OBJECT_INHERIT_ACE | CONTAINER_INHERIT_ACE
        for sid in sorted(self.allowed_sids):
            dacl.AddAccessAllowedAceEx(2, inherit, 0x1F01FF, security.ConvertStringSidToSid(sid))
        descriptor = security.SECURITY_DESCRIPTOR()
        descriptor.SetSecurityDescriptorOwner(self.user_sid, False)
        descriptor.SetSecurityDescriptorDacl(True, dacl, False)
        descriptor.SetSecurityDescriptorControl(0x1000, 0x1000)  # SE_DACL_PROTECTED
        attributes = self.types.SECURITY_ATTRIBUTES()
        attributes.SECURITY_DESCRIPTOR = descriptor
        attributes.bInheritHandle = False
        return attributes

    def check_private(self, handle: Any) -> None:
        security = self.security
        descriptor = security.GetSecurityInfo(handle, security.SE_FILE_OBJECT, 0x01 | 0x04)
        owner = security.ConvertSidToStringSid(descriptor.GetSecurityDescriptorOwner())
        if owner != security.ConvertSidToStringSid(self.user_sid):
            raise WindowsPathError("앱 파일 소유자가 현재 Windows 사용자와 다릅니다.")
        dacl = descriptor.GetSecurityDescriptorDacl()
        if dacl is None or dacl.GetAceCount() == 0:
            raise WindowsPathError("앱 파일에 제한된 Windows ACL이 필요합니다.")
        user_allowed = False
        for index in range(dacl.GetAceCount()):
            ace = dacl.GetAce(index)
            ace_type, flags = ace[0]
            if flags & 0x08:  # INHERIT_ONLY_ACE does not affect this object
                continue
            if ace_type != 0 or len(ace) != 3:
                raise WindowsPathError("앱 파일의 ACL 형식을 검증할 수 없습니다.")
            sid = security.ConvertSidToStringSid(ace[2])
            if sid not in self.allowed_sids:
                raise WindowsPathError("다른 사용자에게 공개된 앱 파일 ACL은 허용하지 않습니다.")
            if sid == owner and ace[1] & 0x1F01FF == 0x1F01FF:
                user_allowed = True
        if not user_allowed:
            raise WindowsPathError("현재 사용자의 앱 파일 전체 접근 권한이 필요합니다.")

    def open_existing(self, path: Path, *, directory: bool) -> Any:
        # MS-FSA 2.1.5.1.2.2 excludes metadata-only opens from sharing checks.
        # FILE_LIST_DIRECTORY == FILE_READ_DATA (0x01) makes the directory handle
        # participate, so omitting SHARE_WRITE/SHARE_DELETE pins its own name.
        # This does not prevent creating or atomically renaming child files.
        access = 0x01 | 0x80 | 0x20000 if directory else 0x80000000 | 0x20000
        share = 0x01
        flags = 0x00200000 | (0x02000000 if directory else 0)  # OPEN_REPARSE_POINT / BACKUP
        return self.file.CreateFile(str(path), access, share, None, 3, flags, None)

    def check_handle(self, handle: Any, *, directory: bool) -> tuple[Any, ...]:
        info: tuple[Any, ...] = self.file.GetFileInformationByHandle(handle)
        if info[0] & 0x400 or bool(info[0] & 0x10) != directory:
            raise WindowsPathError("reparse point 또는 지원하지 않는 파일 형식입니다.")
        if not directory and info[7] != 1:
            raise WindowsPathError("하드 링크된 입력/출력 파일은 지원하지 않습니다.")
        return info


@contextmanager
def _directory_guard(api: Any, path: Path, *, create_private: bool = False) -> Iterator[None]:
    parsed = validate_local_path(str(path))
    if api.file.GetDriveType(str(parsed.anchor)) != 3:  # DRIVE_FIXED only; no network/removable
        raise WindowsPathError("고정된 Windows 로컬 드라이브만 지원합니다.")
    mapping = api.file.QueryDosDevice(parsed.drive).split("\0", 1)[0]
    if re.fullmatch(r"\\Device\\HarddiskVolume[0-9]+", mapping) is None:
        # SUBST skips inspection of underlying ancestors and can change while a
        # held handle still refers to the previous target.
        raise WindowsPathError("SUBST 또는 별칭 드라이브 경로는 지원하지 않습니다.")
    current = Path(parsed.anchor)
    with ExitStack() as stack:
        for component in (None, *parsed.parts[1:]):
            if component is not None:
                current = current / component
            try:
                handle = api.open_existing(current, directory=True)
            except (OSError, api.types.error) as exc:
                if not create_private or getattr(exc, "winerror", None) not in (2, 3):
                    raise
                try:
                    api.file.CreateDirectory(str(current), api.private_attributes(directory=True))
                except (OSError, api.types.error) as create_error:
                    if getattr(create_error, "winerror", None) != 183:
                        raise
                handle = api.open_existing(current, directory=True)
            stack.callback(handle.Close)
            api.check_handle(handle, directory=True)
            if current == path and create_private:
                api.check_private(handle)
        yield


@dataclass
class GuardedFile:
    path: Path
    _api: Any
    _handle: Any

    def read_bytes(self, limit: int) -> bytes:
        if limit < 0:
            raise ValueError("file limit must be non-negative")
        info = self._api.check_handle(self._handle, directory=False)
        if (info[5] << 32) + info[6] > limit:
            raise WindowsPathError("선택한 파일이 크기 제한을 초과합니다.")
        self._api.file.SetFilePointer(self._handle, 0, 0)
        parts: list[bytes] = []
        count = 0
        while True:
            _, chunk = self._api.file.ReadFile(self._handle, min(1024 * 1024, limit + 1 - count))
            if not chunk:
                break
            parts.append(chunk)
            count += len(chunk)
            if count > limit:
                raise WindowsPathError("선택한 파일이 크기 제한을 초과합니다.")
        return b"".join(parts)


@contextmanager
def guard_local_file(path: Path, *, require_private: bool = False) -> Iterator[GuardedFile]:
    """Keep the exact local file and all ancestor names pinned until context exit."""
    api = _api()
    target = Path(str(validate_local_path(str(path))))
    try:
        with _translate_errors(api), _directory_guard(api, target.parent):
            handle = api.open_existing(target, directory=False)
            try:
                api.check_handle(handle, directory=False)
                if require_private:
                    api.check_private(handle)
                yield GuardedFile(target, api, handle)
            finally:
                handle.Close()
    except WindowsPathError:
        raise
    except FileNotFoundError:
        raise
    except OSError as exc:
        raise WindowsPathError("Windows 파일을 안전하게 열 수 없습니다.") from exc


def ensure_private_directory(path: Path) -> Path:
    """Create missing ancestors with a private DACL; verify the final directory ACL."""
    api = _api()
    target = Path(str(validate_local_path(str(path))))
    with _translate_errors(api), _directory_guard(api, target, create_private=True):
        return target


def _rename_handle(handle: Any, target: Path, *, replace: bool) -> None:
    # FILE_RENAME_INFORMATION with a bare name and NULL RootDirectory performs
    # a same-directory rename relative to this already-open file. An absolute
    # target would reopen the parent for FILE_WRITE_DATA and conflict with its
    # directory guard. NtSetInformationFile preserves every guard during rename.
    # Use UTF-16 code units: ctypes.c_wchar would miscount non-BMP names.
    encoded = target.name.encode("utf-16-le")

    class RenameInfo(ctypes.Structure):
        _fields_ = [
            ("ReplaceIfExists", ctypes.c_uint32),
            ("RootDirectory", ctypes.c_void_p),
            ("FileNameLength", ctypes.c_uint32),
            ("FileName", ctypes.c_uint16 * (len(encoded) // 2 + 1)),
        ]

    info = RenameInfo()
    info.ReplaceIfExists = int(replace)
    info.FileNameLength = len(encoded)
    ctypes.memmove(ctypes.addressof(info) + RenameInfo.FileName.offset, encoded, len(encoded))

    class IoStatusBlock(ctypes.Structure):
        # The first member is an NTSTATUS/pointer union; pointer size provides
        # its required size and alignment on both 32-bit and 64-bit Windows.
        _fields_ = [("Status", ctypes.c_void_p), ("Information", ctypes.c_size_t)]

    native: Any = ctypes  # WinDLL is absent from non-Windows typeshed.
    ntdll = native.WinDLL("ntdll")
    rename = ntdll.NtSetInformationFile
    rename.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_int,
    ]
    rename.restype = ctypes.c_int32
    status = IoStatusBlock()
    # CreateFile opened a synchronous handle, so this returns the final status.
    result = rename(int(handle), ctypes.byref(status), ctypes.byref(info), ctypes.sizeof(info), 10)
    if result < 0:
        translate = ntdll.RtlNtStatusToDosError
        translate.argtypes = [ctypes.c_int32]
        translate.restype = ctypes.c_uint32
        raise native.WinError(translate(result))


def _delete_handle(handle: Any) -> None:
    native: Any = ctypes  # WinDLL is absent from non-Windows typeshed.
    kernel = native.WinDLL("kernel32", use_last_error=True)
    remove = kernel.SetFileInformationByHandle
    remove.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
    remove.restype = ctypes.c_int
    disposition = ctypes.c_ubyte(1)
    if not remove(int(handle), 4, ctypes.byref(disposition), ctypes.sizeof(disposition)):
        raise native.WinError(native.get_last_error())


def store_private_bytes(path: Path, payload: bytes, *, replace: bool = False) -> Path:
    """Publish exact bytes by same-volume handle rename, with no overwrite by default.

    A CREATE_NEW temporary file carries its final private DACL from birth. An
    exclusive handle stays open through flush, ACL verification and rename. The
    default rename fails atomically if another process wins the destination name.
    """
    if not isinstance(payload, bytes):
        raise TypeError("private payload must be bytes")
    api = _api()
    target = Path(str(validate_local_path(str(path))))
    with _translate_errors(api), _directory_guard(api, target.parent):
        temporary = target.parent / f".{target.name}.{secrets.token_hex(16)}.tmp"
        handle = api.file.CreateFile(
            str(temporary),
            0x40000000 | 0x10000 | 0x20000,
            0,
            api.private_attributes(directory=False),
            1,
            0x00200000 | 0x80,
            None,
        )
        published = False
        try:
            api.check_handle(handle, directory=False)
            api.check_private(handle)
            remaining = memoryview(payload)
            while remaining:
                _, written = api.file.WriteFile(handle, remaining[: 1024 * 1024].tobytes())
                if written <= 0:
                    raise WindowsPathError("Windows 파일 저장이 진행되지 않습니다.")
                remaining = remaining[written:]
            api.file.FlushFileBuffers(handle)
            api.check_private(handle)
            _rename_handle(handle, target, replace=replace)
            published = True
            return target
        except OSError as exc:
            if getattr(exc, "winerror", None) in (80, 183):
                raise FileExistsError("기존 결과 파일을 덮어쓰지 않습니다.") from exc
            raise
        finally:
            try:
                if not published:
                    _delete_handle(handle)
            finally:
                handle.Close()
