"""Private, atomic JSON persistence for the local investment universe."""

from __future__ import annotations

import json
import os
import secrets
import stat
import sys
from collections.abc import Iterator, Sequence
from contextlib import contextmanager, suppress
from dataclasses import replace
from pathlib import Path
from typing import Protocol, cast

from filelock import FileLock
from filelock import Timeout as FileLockTimeout

from phalanx.domain import KoreanStock, StockMarket
from phalanx.universe.errors import (
    CorruptUniverseError,
    DuplicateStockError,
    StockNotFoundError,
    UniverseStorageError,
    UniverseValidationError,
    UnsafeUniversePathError,
    UnsupportedPlatformError,
)

PRIVATE_DIRECTORY_MODE = 0o700
PRIVATE_FILE_MODE = 0o600
_SCHEMA_VERSION = "1"
_MAX_UNIVERSE_FILE_BYTES = 1024 * 1024
_LOCK_TIMEOUT_SECONDS = 30.0
_ROOT_FIELDS = frozenset({"schema_version", "stocks"})
_STOCK_FIELDS = frozenset({"stock_code", "stock_name", "market", "enabled", "note"})


class UniverseRepository(Protocol):
    """Storage contract consumed by the application service and future GUI."""

    def list_all(self) -> tuple[KoreanStock, ...]: ...

    def add(self, stock: KoreanStock) -> KoreanStock: ...

    def set_enabled(self, stock_code: str, *, enabled: bool) -> KoreanStock: ...

    def remove(self, stock_code: str) -> KoreanStock: ...


def _require_supported_platform(platform_name: str) -> None:
    if not platform_name.startswith("linux"):
        raise UnsupportedPlatformError("로컬 유니버스 저장소는 현재 Linux와 WSL에서만 지원됩니다.")


def default_universe_path(
    *,
    home: Path | None = None,
    platform_name: str | None = None,
) -> Path:
    """Resolve the Linux/WSL per-user data path without using the working directory."""

    selected_platform = sys.platform if platform_name is None else platform_name
    _require_supported_platform(selected_platform)
    user_home = Path.home() if home is None else Path(home)
    return user_home / ".local" / "share" / "phalanx" / "universe.json"


class JsonUniverseRepository:
    """Store one human-curated universe in a versioned, atomically replaced JSON file."""

    def __init__(self, path: Path | None = None) -> None:
        _require_supported_platform(sys.platform)
        resolved_path = (
            default_universe_path(platform_name=sys.platform)
            if path is None
            else Path(path).absolute()
        )
        self.path = resolved_path
        self.directory = resolved_path.parent
        self.lock_path = resolved_path.with_name(f"{resolved_path.name}.lock")

    def list_all(self) -> tuple[KoreanStock, ...]:
        """Return a complete immutable snapshot of the stored universe."""

        return self._load()

    def add(self, stock: KoreanStock) -> KoreanStock:
        """Atomically append a stock while enforcing code uniqueness under the lock."""

        with self._locked():
            stocks = self._load()
            if any(existing.stock_code == stock.stock_code for existing in stocks):
                raise DuplicateStockError(
                    f"종목코드 {stock.stock_code}는 이미 유니버스에 등록되어 있습니다."
                )
            self._store((*stocks, stock))
        return stock

    def set_enabled(self, stock_code: str, *, enabled: bool) -> KoreanStock:
        """Atomically replace one stock's activation state."""

        with self._locked():
            stocks = list(self._load())
            for index, stock in enumerate(stocks):
                if stock.stock_code != stock_code:
                    continue
                updated = replace(stock, enabled=enabled)
                if updated != stock:
                    stocks[index] = updated
                    self._store(stocks)
                return updated
        raise StockNotFoundError(f"종목코드 {stock_code}는 유니버스에 등록되어 있지 않습니다.")

    def remove(self, stock_code: str) -> KoreanStock:
        """Atomically remove and return one registered stock."""

        with self._locked():
            stocks = list(self._load())
            for index, stock in enumerate(stocks):
                if stock.stock_code != stock_code:
                    continue
                removed = stocks.pop(index)
                self._store(stocks)
                return removed
        raise StockNotFoundError(f"종목코드 {stock_code}는 유니버스에 등록되어 있지 않습니다.")

    @contextmanager
    def _locked(self) -> Iterator[None]:
        self._ensure_private_directory()
        self._ensure_lock_file()
        lock = FileLock(self.lock_path, timeout=_LOCK_TIMEOUT_SECONDS, mode=PRIVATE_FILE_MODE)
        try:
            with lock:
                self._validate_lock_file()
                yield
        except FileLockTimeout:
            raise UniverseStorageError(
                "유니버스 파일 잠금을 기다리는 시간이 초과되었습니다."
            ) from None
        except UniverseStorageError:
            raise
        except OSError:
            raise UniverseStorageError(
                "유니버스 파일 잠금을 안전하게 사용할 수 없습니다."
            ) from None

    def _load(self) -> tuple[KoreanStock, ...]:
        absolute_path = self.path.absolute()
        _assert_no_symlink_components(absolute_path)
        if not self.directory.exists():
            return ()
        _validate_private_directory(self.directory)

        directory_fd = _open_directory(self.directory)
        file_fd: int | None = None
        try:
            before = _stat_private_file(directory_fd, self.path.name)
            if before is None:
                return ()
            file_fd = os.open(
                self.path.name,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
                dir_fd=directory_fd,
            )
            opened = os.fstat(file_fd)
            _validate_private_file_stat(opened, self.path)
            if not _same_file(before, opened):
                raise UnsafeUniversePathError(
                    "유니버스 파일이 열리는 동안 변경되어 읽기를 중단했습니다."
                )
            contents = _read_file(file_fd)
            os.close(file_fd)
            file_fd = None
            return _deserialize_universe(contents)
        except UniverseStorageError:
            raise
        except (OSError, UnicodeError):
            raise UniverseStorageError("유니버스 파일을 안전하게 읽지 못했습니다.") from None
        finally:
            if file_fd is not None:
                os.close(file_fd)
            os.close(directory_fd)

    def _store(self, stocks: Sequence[KoreanStock]) -> None:
        payload = _serialize_universe(stocks)
        directory_fd = _open_directory(self.directory)
        temporary_name = f".{self.path.name}.{secrets.token_hex(8)}.tmp"
        temporary_fd: int | None = None
        temporary_exists = False
        try:
            _stat_private_file(directory_fd, self.path.name)
            temporary_fd = os.open(
                temporary_name,
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0),
                PRIVATE_FILE_MODE,
                dir_fd=directory_fd,
            )
            temporary_exists = True
            os.fchmod(temporary_fd, PRIVATE_FILE_MODE)
            _write_all(temporary_fd, payload)
            os.close(temporary_fd)
            temporary_fd = None

            _stat_private_file(directory_fd, self.path.name)
            os.replace(
                temporary_name,
                self.path.name,
                src_dir_fd=directory_fd,
                dst_dir_fd=directory_fd,
            )
            temporary_exists = False
            os.fsync(directory_fd)
        except UniverseStorageError:
            raise
        except OSError:
            raise UniverseStorageError("유니버스 파일을 원자적으로 저장하지 못했습니다.") from None
        finally:
            if temporary_fd is not None:
                os.close(temporary_fd)
            if temporary_exists:
                with suppress(FileNotFoundError):
                    os.unlink(temporary_name, dir_fd=directory_fd)
            os.close(directory_fd)

    def _ensure_private_directory(self) -> None:
        absolute_directory = self.directory.absolute()
        _assert_no_symlink_components(absolute_directory)
        try:
            absolute_directory.mkdir(mode=PRIVATE_DIRECTORY_MODE, parents=True, exist_ok=True)
        except OSError:
            raise UnsafeUniversePathError(
                "유니버스 저장 디렉터리를 안전하게 만들 수 없습니다."
            ) from None
        _assert_no_symlink_components(absolute_directory)
        _validate_private_directory(absolute_directory)

    def _ensure_lock_file(self) -> None:
        directory_fd = _open_directory(self.directory)
        lock_fd: int | None = None
        try:
            try:
                lock_fd = os.open(
                    self.lock_path.name,
                    os.O_WRONLY
                    | os.O_CREAT
                    | os.O_EXCL
                    | getattr(os, "O_NOFOLLOW", 0)
                    | getattr(os, "O_CLOEXEC", 0),
                    PRIVATE_FILE_MODE,
                    dir_fd=directory_fd,
                )
                os.fchmod(lock_fd, PRIVATE_FILE_MODE)
                _validate_private_file_stat(os.fstat(lock_fd), self.lock_path)
            except FileExistsError:
                existing = _stat_private_file(directory_fd, self.lock_path.name)
                if existing is None:
                    raise UniverseStorageError(
                        "유니버스 잠금 파일을 확인하지 못했습니다."
                    ) from None
        except UniverseStorageError:
            raise
        except OSError:
            raise UniverseStorageError("유니버스 잠금 파일을 안전하게 만들지 못했습니다.") from None
        finally:
            if lock_fd is not None:
                os.close(lock_fd)
            os.close(directory_fd)

    def _validate_lock_file(self) -> None:
        directory_fd = _open_directory(self.directory)
        try:
            if _stat_private_file(directory_fd, self.lock_path.name) is None:
                raise UniverseStorageError("유니버스 잠금 파일이 사라졌습니다.")
        finally:
            os.close(directory_fd)


def _assert_no_symlink_components(path: Path) -> None:
    for candidate in (path, *path.parents):
        try:
            metadata = candidate.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(metadata.st_mode):
            raise UnsafeUniversePathError(
                f"유니버스 경로에는 심볼릭 링크를 사용할 수 없습니다: {candidate}"
            )


def _validate_private_directory(path: Path) -> None:
    try:
        metadata = path.lstat()
    except OSError:
        raise UnsafeUniversePathError("유니버스 저장 디렉터리를 확인할 수 없습니다.") from None
    if not stat.S_ISDIR(metadata.st_mode):
        raise UnsafeUniversePathError("유니버스 저장 경로가 실제 디렉터리가 아닙니다.")
    if metadata.st_uid != os.geteuid():
        raise UnsafeUniversePathError("유니버스 저장 디렉터리는 현재 사용자 소유여야 합니다.")
    if stat.S_IMODE(metadata.st_mode) != PRIVATE_DIRECTORY_MODE:
        raise UnsafeUniversePathError("유니버스 저장 디렉터리 권한은 0700이어야 합니다.")


def _open_directory(path: Path) -> int:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        before = path.lstat()
        _validate_private_directory(path)
        directory_fd = os.open(path, flags)
        opened = os.fstat(directory_fd)
        if not _same_file(before, opened):
            os.close(directory_fd)
            raise UnsafeUniversePathError("유니버스 저장 디렉터리가 열리는 동안 변경되었습니다.")
        return directory_fd
    except UniverseStorageError:
        raise
    except OSError:
        raise UnsafeUniversePathError("유니버스 저장 디렉터리를 안전하게 열 수 없습니다.") from None


def _stat_private_file(directory_fd: int, name: str) -> os.stat_result | None:
    try:
        metadata = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None
    _validate_private_file_stat(metadata, Path(name))
    return metadata


def _validate_private_file_stat(metadata: os.stat_result, path: Path) -> None:
    if not stat.S_ISREG(metadata.st_mode):
        raise UnsafeUniversePathError(f"유니버스 파일 경로가 일반 파일이 아닙니다: {path}")
    if metadata.st_uid != os.geteuid():
        raise UnsafeUniversePathError(f"유니버스 파일은 현재 사용자 소유여야 합니다: {path}")
    if stat.S_IMODE(metadata.st_mode) != PRIVATE_FILE_MODE:
        raise UnsafeUniversePathError(f"유니버스 파일 권한은 0600이어야 합니다: {path}")


def _same_file(first: os.stat_result, second: os.stat_result) -> bool:
    return (first.st_dev, first.st_ino) == (second.st_dev, second.st_ino)


def _read_file(file_fd: int) -> str:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = os.read(file_fd, 64 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > _MAX_UNIVERSE_FILE_BYTES:
            raise CorruptUniverseError("유니버스 파일이 허용된 크기를 초과했습니다.")
        chunks.append(chunk)
    try:
        return b"".join(chunks).decode("utf-8", errors="strict")
    except UnicodeError:
        raise CorruptUniverseError("유니버스 파일이 올바른 UTF-8 텍스트가 아닙니다.") from None


def _write_all(file_fd: int, payload: bytes) -> None:
    remaining = memoryview(payload)
    while remaining:
        written = os.write(file_fd, remaining)
        if written <= 0:
            raise OSError("universe write made no progress")
        remaining = remaining[written:]
    os.fsync(file_fd)


def _serialize_universe(stocks: Sequence[KoreanStock]) -> bytes:
    stock_codes = [stock.stock_code for stock in stocks]
    if len(stock_codes) != len(set(stock_codes)):
        duplicate = next(code for code in stock_codes if stock_codes.count(code) > 1)
        raise DuplicateStockError(f"종목코드 {duplicate}는 중복 저장할 수 없습니다.")
    payload = {
        "schema_version": _SCHEMA_VERSION,
        "stocks": [
            {
                "stock_code": stock.stock_code,
                "stock_name": stock.stock_name,
                "market": stock.market.value,
                "enabled": stock.enabled,
                "note": stock.note,
            }
            for stock in stocks
        ],
    }
    serialized = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    return serialized.encode("utf-8")


def _deserialize_universe(contents: str) -> tuple[KoreanStock, ...]:
    try:
        payload = json.loads(contents)
    except json.JSONDecodeError:
        raise CorruptUniverseError(
            "유니버스 파일이 손상되어 JSON을 해석할 수 없습니다. 원본 파일을 확인해 주세요."
        ) from None
    if not isinstance(payload, dict) or set(payload) != _ROOT_FIELDS:
        raise CorruptUniverseError("유니버스 파일의 최상위 구조가 올바르지 않습니다.")
    if payload.get("schema_version") != _SCHEMA_VERSION:
        raise CorruptUniverseError("지원하지 않는 유니버스 파일 버전입니다.")
    raw_stocks = payload.get("stocks")
    if not isinstance(raw_stocks, list):
        raise CorruptUniverseError("유니버스 stocks 값은 배열이어야 합니다.")

    stocks: list[KoreanStock] = []
    try:
        for raw_stock in raw_stocks:
            if not isinstance(raw_stock, dict) or set(raw_stock) != _STOCK_FIELDS:
                raise CorruptUniverseError("유니버스 종목 레코드 구조가 올바르지 않습니다.")
            record = cast(dict[str, object], raw_stock)
            stocks.append(
                KoreanStock(
                    stock_code=cast(str, record["stock_code"]),
                    stock_name=cast(str, record["stock_name"]),
                    market=StockMarket.parse(record["market"]),
                    enabled=cast(bool, record["enabled"]),
                    note=cast(str | None, record["note"]),
                )
            )
    except UniverseValidationError as error:
        raise CorruptUniverseError(f"유니버스 종목 데이터가 올바르지 않습니다: {error}") from None

    stock_codes = [stock.stock_code for stock in stocks]
    if len(stock_codes) != len(set(stock_codes)):
        raise CorruptUniverseError("유니버스 파일에 중복 종목코드가 있습니다.")
    return tuple(stocks)


__all__ = [
    "JsonUniverseRepository",
    "UniverseRepository",
    "default_universe_path",
]
