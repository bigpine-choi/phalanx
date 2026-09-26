"""Headless desktop storage: bounded input, exact results, and small preferences."""

from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from phalanx.portfolio.private_json_storage import store_private_json_bytes

DEFAULT_SETTINGS: dict[str, bool | int] = {
    "sfxVolume": 22,
    "musicVolume": 16,
    "reduceMotion": False,
}
_SETTINGS_LIMIT = 4096


class StorageError(ValueError):
    """Desktop data could not be read or saved safely."""


@dataclass(frozen=True)
class SettingsLoad:
    settings: dict[str, bool | int]
    notice: str | None = None


def app_data_directory() -> Path:
    """Choose per-user storage independently from checkout and working directory."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA")
        if not base:
            raise StorageError("LOCALAPPDATA가 없습니다. 네이티브 Windows 사용자로 실행하세요.")
        directory = Path(base) / "Phalanx"
    else:
        base = os.environ.get("XDG_DATA_HOME")
        directory = (Path(base) if base else Path.home() / ".local" / "share") / "phalanx"
    if not directory.is_absolute():
        raise StorageError("앱 데이터 경로는 절대 경로여야 합니다.")
    if any((ancestor / ".git").exists() for ancestor in (directory, *directory.parents)):
        raise StorageError("앱 데이터는 Git 저장소 밖에 저장해야 합니다.")
    _ensure_private_directory(directory)
    return directory


def _ensure_private_directory(directory: Path) -> None:
    if sys.platform == "win32":
        from phalanx.platforms.windows_files import ensure_private_directory

        ensure_private_directory(directory)
        return
    try:
        # Existing ancestors are not chmod'ed: the application only owns its leaf.
        if any(parent.is_symlink() for parent in (directory, *directory.parents)):
            raise StorageError("앱 데이터 디렉터리에 심볼릭 링크를 사용할 수 없습니다.")
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        metadata = directory.lstat()
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or stat.S_IMODE(metadata.st_mode) != 0o700
        ):
            raise StorageError("앱 데이터 디렉터리는 현재 사용자 소유, 권한 0700이어야 합니다.")
    except OSError as exc:
        raise StorageError("앱 데이터 디렉터리를 안전하게 준비할 수 없습니다.") from exc


def read_selected_file(path: Path, max_bytes: int) -> bytes:
    """Read one bounded immutable byte snapshot; never follow a file link."""
    if max_bytes < 0:
        raise ValueError("max_bytes must be non-negative")
    if sys.platform == "win32":
        from phalanx.platforms.windows_files import guard_local_file

        with guard_local_file(path) as guarded:
            return guarded.read_bytes(max_bytes)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise StorageError("선택한 파일은 링크가 아닌 일반 파일이어야 합니다.")
        if before.st_size > max_bytes:
            raise StorageError("선택한 파일이 크기 제한을 초과합니다.")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            payload = stream.read(max_bytes + 1)
        after = os.fstat(descriptor)
        if len(payload) > max_bytes:
            raise StorageError("선택한 파일이 크기 제한을 초과합니다.")
        if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ):
            raise StorageError("읽는 도중 입력 파일이 변경되었습니다. 다시 선택하세요.")
        return payload
    finally:
        os.close(descriptor)


def store_result(output: Path, payload: bytes) -> Path:
    """Preserve service bytes, refuse overwrite, and use native private storage."""
    if sys.platform == "win32":
        from phalanx.platforms.windows_files import store_private_bytes

        return store_private_bytes(output, payload)
    return store_private_json_bytes(output, payload)


def _validate_settings(settings: Mapping[str, object]) -> dict[str, bool | int]:
    if set(settings) != set(DEFAULT_SETTINGS):
        raise StorageError("설정에는 음량과 모션 항목만 포함할 수 있습니다.")
    validated: dict[str, bool | int] = {}
    for name in ("sfxVolume", "musicVolume"):
        volume = settings[name]
        if type(volume) is not int or not 0 <= volume <= 100:
            raise StorageError("음량은 0부터 100까지의 정수여야 합니다.")
        validated[name] = volume
    motion = settings["reduceMotion"]
    if not isinstance(motion, bool):
        raise StorageError("모션 축소 설정은 참/거짓이어야 합니다.")
    validated["reduceMotion"] = motion
    return validated


class SettingsStore:
    """Only audio volumes and reduced motion persist; launch is always muted."""

    def __init__(self, directory: Path | None = None) -> None:
        self.directory = app_data_directory() if directory is None else directory
        _ensure_private_directory(self.directory)
        self.path = self.directory / "settings.json"

    def load(self) -> SettingsLoad:
        try:
            if sys.platform == "win32":
                from phalanx.platforms.windows_files import guard_local_file

                with guard_local_file(self.path, require_private=True) as guarded:
                    payload = guarded.read_bytes(_SETTINGS_LIMIT)
            else:
                if not self.path.exists() and not self.path.is_symlink():
                    return SettingsLoad(dict(DEFAULT_SETTINGS))
                metadata = self.path.lstat()
                if metadata.st_uid != os.geteuid() or stat.S_IMODE(metadata.st_mode) != 0o600:
                    raise StorageError("설정 파일의 접근 권한을 검증할 수 없습니다.")
                payload = read_selected_file(self.path, _SETTINGS_LIMIT)
            parsed = json.loads(payload)
            if not isinstance(parsed, dict):
                raise StorageError("설정 구조가 잘못되었습니다.")
            return SettingsLoad(_validate_settings(parsed))
        except FileNotFoundError:
            return SettingsLoad(dict(DEFAULT_SETTINGS))
        except (OSError, ValueError, UnicodeError):
            return SettingsLoad(
                dict(DEFAULT_SETTINGS),
                "설정 파일을 읽을 수 없어 기본값으로 복구했습니다. 설정 변경 시 다시 저장합니다.",
            )

    def save(self, settings: Mapping[str, object]) -> dict[str, bool | int]:
        validated = _validate_settings(settings)
        payload = (json.dumps(validated, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
        _ensure_private_directory(self.directory)
        if sys.platform == "win32":
            from phalanx.platforms.windows_files import store_private_bytes

            store_private_bytes(self.path, payload, replace=True)
        else:
            descriptor, temporary = tempfile.mkstemp(prefix=".settings.", dir=self.directory)
            try:
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self.path)
                directory_fd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            finally:
                with suppress(FileNotFoundError):
                    os.unlink(temporary)
        return validated
