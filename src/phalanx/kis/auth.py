"""Real-account KIS OAuth issuance and a private, serialized token cache."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import stat
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from filelock import FileLock
from filelock import Timeout as FileLockTimeout
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError, field_validator

from phalanx.config import KisCredentials
from phalanx.kis.errors import KisHttpError, KisProtocolError, KisTimeoutError, TokenCacheError

KIS_REAL_BASE_URL = "https://openapi.koreainvestment.com:9443"
KIS_TOKEN_URL = f"{KIS_REAL_BASE_URL}/oauth2/tokenP"
DEFAULT_TOKEN_CACHE_PATH = Path("runtime/token-cache/kis-access-token.json")

_SEOUL = ZoneInfo("Asia/Seoul")
_EXPIRATION_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")
_FINGERPRINT_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_CACHE_FIELDS = {
    "schema_version",
    "access_token",
    "token_type",
    "expires_at",
    "app_key_fingerprint",
}
_CACHE_SCHEMA_VERSION = "1"
_CACHE_REUSE_MARGIN = timedelta(minutes=5)
_EXPIRATION_TOLERANCE = timedelta(minutes=5)
_DEFAULT_TIMEOUT = httpx.Timeout(10.0, connect=5.0)
_LOCK_TIMEOUT_SECONDS = 30.0
_MAX_CACHE_FILE_BYTES = 1024 * 1024

Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


class AccessToken(BaseModel):
    """A validated OAuth token whose secret is excluded from display."""

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)

    access_token: SecretStr = Field(repr=False)
    token_type: str
    expires_at: datetime

    @field_validator("access_token", mode="before")
    @classmethod
    def _reject_blank_access_token(cls, value: Any) -> Any:
        raw_value = value.get_secret_value() if isinstance(value, SecretStr) else value
        if not isinstance(raw_value, str) or not raw_value.strip():
            raise ValueError("access token must be a non-empty string")
        return value

    @field_validator("token_type", mode="before")
    @classmethod
    def _validate_token_type(cls, value: Any) -> Any:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("token type must be a non-empty string")
        return value.strip()

    @field_validator("expires_at")
    @classmethod
    def _require_aware_expiration(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("token expiration must be timezone-aware")
        return value


@dataclass(frozen=True, repr=False)
class _CachedToken:
    token: AccessToken
    app_key_fingerprint: str


class KisTokenManager:
    """Issue or safely reuse the single supported real-account OAuth token."""

    def __init__(
        self,
        credentials: KisCredentials,
        *,
        cache_path: Path = DEFAULT_TOKEN_CACHE_PATH,
        client: httpx.Client | None = None,
        timeout: httpx.Timeout | float = _DEFAULT_TIMEOUT,
        clock: Clock = _utc_now,
    ) -> None:
        self._credentials = credentials
        self._cache = _TokenCache(Path(cache_path))
        self._client = client
        self._timeout = timeout
        self._clock = clock

    def get_access_token(self) -> AccessToken:
        """Return a reusable token or issue one while holding the cache lock."""

        fingerprint = _app_key_fingerprint(self._credentials)
        with self._cache.locked():
            cached = self._cache.load()
            now = self._now()
            if (
                cached is not None
                and hmac.compare_digest(cached.app_key_fingerprint, fingerprint)
                and cached.token.expires_at - now >= _CACHE_REUSE_MARGIN
            ):
                return cached.token

            issued = self._issue_access_token()
            self._cache.save(issued, fingerprint)
            return issued

    def invalidate_if_current(self, token: AccessToken) -> bool:
        """Remove the cache only when it still contains the caller's exact token."""

        fingerprint = _app_key_fingerprint(self._credentials)
        with self._cache.locked():
            cached = self._cache.load()
            if cached is None or not hmac.compare_digest(cached.app_key_fingerprint, fingerprint):
                return False
            if not hmac.compare_digest(
                cached.token.access_token.get_secret_value(),
                token.access_token.get_secret_value(),
            ):
                return False
            self._cache.delete()
            return True

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise KisProtocolError("The OAuth clock must be timezone-aware.")
        return value

    def _issue_access_token(self) -> AccessToken:
        if self._client is not None:
            return self._send_token_request(self._client)
        with httpx.Client() as client:
            return self._send_token_request(client)

    def _send_token_request(self, client: httpx.Client) -> AccessToken:
        body = {
            "grant_type": "client_credentials",
            "appkey": self._credentials.app_key.get_secret_value(),
            "appsecret": self._credentials.app_secret.get_secret_value(),
        }
        try:
            response = client.post(KIS_TOKEN_URL, json=body, timeout=self._timeout)
        except httpx.TimeoutException:
            raise KisTimeoutError("The KIS OAuth request timed out.") from None
        except httpx.HTTPError:
            raise KisHttpError(
                "The KIS OAuth request failed before a response was received."
            ) from None

        if not 200 <= response.status_code < 300:
            raise KisHttpError(f"The KIS OAuth request failed with HTTP {response.status_code}.")

        try:
            payload = response.json()
        except ValueError:
            raise KisProtocolError("The KIS OAuth response was not valid JSON.") from None
        if not isinstance(payload, dict):
            raise KisProtocolError("The KIS OAuth response must be a JSON object.")

        received_at = self._now()
        return _parse_token_response(payload, received_at)


class _TokenCache:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.directory = path.parent
        self.lock_path = path.with_name(f"{path.name}.lock")

    @contextmanager
    def locked(self) -> Iterator[None]:
        self._ensure_directory()
        self._ensure_lock_file()
        lock = FileLock(
            self.lock_path,
            timeout=_LOCK_TIMEOUT_SECONDS,
            mode=0o600,
        )
        try:
            with lock:
                directory_fd = self._open_directory()
                try:
                    self._validate_named_file(directory_fd, self.lock_path.name)
                finally:
                    os.close(directory_fd)
                yield
        except FileLockTimeout:
            raise TokenCacheError("Timed out waiting for the KIS token cache lock.") from None
        except OSError:
            raise TokenCacheError(
                "The KIS token cache lock could not be acquired safely."
            ) from None

    def load(self) -> _CachedToken | None:
        directory_fd = self._open_directory()
        file_fd: int | None = None
        try:
            before = self._stat_named_file(directory_fd, self.path.name)
            if before is None:
                return None
            file_fd = os.open(
                self.path.name,
                os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=directory_fd,
            )
            opened = os.fstat(file_fd)
            _validate_private_file_stat(opened)
            if not _same_file(before, opened):
                raise TokenCacheError("The KIS token cache changed while it was opened.")

            with os.fdopen(file_fd, mode="r", encoding="utf-8", errors="strict") as handle:
                file_fd = None
                contents = handle.read(_MAX_CACHE_FILE_BYTES + 1)
            if len(contents.encode("utf-8")) > _MAX_CACHE_FILE_BYTES:
                return None
            return _parse_cached_token(contents)
        except TokenCacheError:
            raise
        except UnicodeError:
            return None
        except OSError:
            raise TokenCacheError("The KIS token cache could not be read safely.") from None
        finally:
            if file_fd is not None:
                os.close(file_fd)
            os.close(directory_fd)

    def save(self, token: AccessToken, app_key_fingerprint: str) -> None:
        payload = (
            json.dumps(
                {
                    "schema_version": _CACHE_SCHEMA_VERSION,
                    "access_token": token.access_token.get_secret_value(),
                    "token_type": token.token_type,
                    "expires_at": token.expires_at.isoformat(),
                    "app_key_fingerprint": app_key_fingerprint,
                },
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        )
        self._atomic_write(payload)

    def delete(self) -> None:
        directory_fd = self._open_directory()
        try:
            existing = self._stat_named_file(directory_fd, self.path.name)
            if existing is None:
                return
            os.unlink(self.path.name, dir_fd=directory_fd)
            os.fsync(directory_fd)
        except TokenCacheError:
            raise
        except OSError:
            raise TokenCacheError("The KIS token cache could not be invalidated safely.") from None
        finally:
            os.close(directory_fd)

    def _ensure_directory(self) -> None:
        try:
            if self.directory.parent.exists() and self.directory.parent.is_symlink():
                raise TokenCacheError("The KIS token cache parent must not be a symbolic link.")
            self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            directory_stat = os.lstat(self.directory)
            _validate_private_directory_stat(directory_stat)
        except TokenCacheError:
            raise
        except OSError:
            raise TokenCacheError("The KIS token cache directory is unsafe.") from None

    def _ensure_lock_file(self) -> None:
        directory_fd = self._open_directory()
        lock_fd: int | None = None
        try:
            try:
                lock_fd = os.open(
                    self.lock_path.name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                    0o600,
                    dir_fd=directory_fd,
                )
                _validate_private_file_stat(os.fstat(lock_fd))
            except FileExistsError:
                self._validate_named_file(directory_fd, self.lock_path.name)
        except TokenCacheError:
            raise
        except OSError:
            raise TokenCacheError("The KIS token cache lock is unsafe.") from None
        finally:
            if lock_fd is not None:
                os.close(lock_fd)
            os.close(directory_fd)

    def _atomic_write(self, payload: str) -> None:
        directory_fd = self._open_directory()
        temporary_name = f".{self.path.name}.{uuid.uuid4().hex}.tmp"
        temporary_fd: int | None = None
        temporary_exists = False
        try:
            self._stat_named_file(directory_fd, self.path.name)
            temporary_fd = os.open(
                temporary_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                0o600,
                dir_fd=directory_fd,
            )
            temporary_exists = True
            _validate_private_file_stat(os.fstat(temporary_fd))
            with os.fdopen(temporary_fd, mode="w", encoding="utf-8", errors="strict") as handle:
                temporary_fd = None
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())

            self._stat_named_file(directory_fd, self.path.name)
            os.replace(
                temporary_name,
                self.path.name,
                src_dir_fd=directory_fd,
                dst_dir_fd=directory_fd,
            )
            temporary_exists = False
            os.fsync(directory_fd)
        except TokenCacheError:
            raise
        except (OSError, UnicodeError):
            raise TokenCacheError("The KIS token cache could not be stored safely.") from None
        finally:
            if temporary_fd is not None:
                os.close(temporary_fd)
            if temporary_exists:
                with suppress(FileNotFoundError):
                    os.unlink(temporary_name, dir_fd=directory_fd)
            os.close(directory_fd)

    def _open_directory(self) -> int:
        try:
            before = os.lstat(self.directory)
            _validate_private_directory_stat(before)
            directory_fd = os.open(
                self.directory,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
            )
            opened = os.fstat(directory_fd)
            _validate_private_directory_stat(opened)
            if not _same_file(before, opened):
                os.close(directory_fd)
                raise TokenCacheError("The KIS token cache directory changed while opening.")
            return directory_fd
        except TokenCacheError:
            raise
        except OSError:
            raise TokenCacheError("The KIS token cache directory is unsafe.") from None

    def _validate_named_file(self, directory_fd: int, name: str) -> os.stat_result:
        file_stat = self._stat_named_file(directory_fd, name)
        if file_stat is None:
            raise TokenCacheError("A required KIS token cache file is missing.")
        return file_stat

    def _stat_named_file(self, directory_fd: int, name: str) -> os.stat_result | None:
        try:
            file_stat = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        except FileNotFoundError:
            return None
        _validate_private_file_stat(file_stat)
        return file_stat


def _parse_token_response(payload: dict[Any, Any], received_at: datetime) -> AccessToken:
    access_token = payload.get("access_token")
    token_type = payload.get("token_type")
    expiration_value = payload.get("access_token_token_expired")
    if not isinstance(access_token, str) or not access_token.strip():
        raise KisProtocolError("The KIS OAuth response omitted a valid access token.")
    if not isinstance(token_type, str) or not token_type.strip():
        raise KisProtocolError("The KIS OAuth response omitted a valid token type.")

    expires_at = _parse_kis_expiration(expiration_value)
    if expires_at <= received_at:
        raise KisProtocolError("The KIS OAuth response contained an expired token.")

    if "expires_in" in payload:
        expires_in = payload["expires_in"]
        if type(expires_in) is not int or expires_in <= 0:
            raise KisProtocolError("The KIS OAuth expires_in field must be a positive integer.")
        expected_expiration = received_at + timedelta(seconds=expires_in)
        if abs(expires_at - expected_expiration) > _EXPIRATION_TOLERANCE:
            raise KisProtocolError("The KIS OAuth expiration fields are inconsistent.")

    try:
        return AccessToken(
            access_token=SecretStr(access_token),
            token_type=token_type,
            expires_at=expires_at,
        )
    except ValidationError:
        raise KisProtocolError("The KIS OAuth token response is invalid.") from None


def _parse_kis_expiration(value: Any) -> datetime:
    if not isinstance(value, str) or _EXPIRATION_PATTERN.fullmatch(value) is None:
        raise KisProtocolError("The KIS OAuth expiration must use YYYY-MM-DD HH:MM:SS.")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        raise KisProtocolError("The KIS OAuth expiration is not a valid date and time.") from None
    return parsed.replace(tzinfo=_SEOUL)


def _parse_cached_token(contents: str) -> _CachedToken | None:
    try:
        payload = json.loads(contents)
    except (json.JSONDecodeError, UnicodeError):
        return None
    if not isinstance(payload, dict) or set(payload) != _CACHE_FIELDS:
        return None
    if payload.get("schema_version") != _CACHE_SCHEMA_VERSION:
        return None

    access_token = payload.get("access_token")
    token_type = payload.get("token_type")
    expires_at_value = payload.get("expires_at")
    fingerprint = payload.get("app_key_fingerprint")
    if not isinstance(access_token, str) or not access_token.strip():
        return None
    if not isinstance(token_type, str) or not token_type.strip():
        return None
    if not isinstance(expires_at_value, str):
        return None
    if not isinstance(fingerprint, str) or _FINGERPRINT_PATTERN.fullmatch(fingerprint) is None:
        return None

    try:
        expires_at = datetime.fromisoformat(expires_at_value)
        token = AccessToken(
            access_token=SecretStr(access_token),
            token_type=token_type,
            expires_at=expires_at,
        )
    except (ValueError, ValidationError):
        return None
    return _CachedToken(token=token, app_key_fingerprint=fingerprint)


def _app_key_fingerprint(credentials: KisCredentials) -> str:
    app_key = credentials.app_key.get_secret_value().encode("utf-8")
    return hashlib.sha256(app_key).hexdigest()


def _validate_private_directory_stat(file_stat: os.stat_result) -> None:
    if not stat.S_ISDIR(file_stat.st_mode):
        raise TokenCacheError("The KIS token cache directory is not a directory.")
    if file_stat.st_uid != os.geteuid():
        raise TokenCacheError("The KIS token cache directory has an unsafe owner.")
    if stat.S_IMODE(file_stat.st_mode) != 0o700:
        raise TokenCacheError("The KIS token cache directory must have mode 0700.")


def _validate_private_file_stat(file_stat: os.stat_result) -> None:
    if not stat.S_ISREG(file_stat.st_mode):
        raise TokenCacheError("A KIS token cache path is not a regular file.")
    if file_stat.st_uid != os.geteuid():
        raise TokenCacheError("A KIS token cache file has an unsafe owner.")
    if stat.S_IMODE(file_stat.st_mode) != 0o600:
        raise TokenCacheError("KIS token cache files must have mode 0600.")


def _same_file(first: os.stat_result, second: os.stat_result) -> bool:
    return (first.st_dev, first.st_ino) == (second.st_dev, second.st_ino)
