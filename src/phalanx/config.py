"""Strict loading for KIS credentials kept outside the repository."""

from __future__ import annotations

import os
import re
import stat
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, SecretStr, ValidationError, field_validator

DEFAULT_CREDENTIALS_PATH = Path("~/.config/phalanx/credentials.env")

_CREDENTIAL_KEYS = {
    "PHALANX_KIS_APP_KEY": "app_key",
    "PHALANX_KIS_APP_SECRET": "app_secret",
    "PHALANX_KIS_ACCOUNT_NUMBER": "account_number",
}
_MAX_CREDENTIAL_FILE_BYTES = 64 * 1024
_ACCOUNT_NUMBER_PATTERN = re.compile(r"^\d{8}-\d{2}$")
_SAFE_SETUP_GUIDANCE = (
    "KIS credentials are missing or unsafe. Configure "
    "~/.config/phalanx/credentials.env manually; the directory must be mode 0700 "
    "and the file mode 0600. Phalanx will not create, modify, or chmod them."
)


class ConfigError(RuntimeError):
    """A credential configuration failure whose message never contains secret values."""


class KisCredentials(BaseModel):
    """Immutable real-account credentials with secret-safe display behavior."""

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)

    app_key: SecretStr
    app_secret: SecretStr
    account_number: SecretStr

    @field_validator("app_key", "app_secret", "account_number", mode="before")
    @classmethod
    def _reject_blank_secrets(cls, value: Any) -> Any:
        raw_value = value.get_secret_value() if isinstance(value, SecretStr) else value
        if not isinstance(raw_value, str) or not raw_value.strip():
            raise ValueError("credential values must be non-empty strings")
        return value

    @field_validator("account_number")
    @classmethod
    def _validate_account_number(cls, value: SecretStr) -> SecretStr:
        if _ACCOUNT_NUMBER_PATTERN.fullmatch(value.get_secret_value()) is None:
            raise ValueError("account number must use the 8-digit-2-digit format")
        return value

    @property
    def cano(self) -> str:
        """Return the eight-digit comprehensive account number for KIS requests."""

        return self.account_number.get_secret_value().split("-", maxsplit=1)[0]

    @property
    def acnt_prdt_cd(self) -> str:
        """Return the two-digit account product code for KIS requests."""

        return self.account_number.get_secret_value().split("-", maxsplit=1)[1]

    @property
    def masked_account_number(self) -> str:
        """Return the only account-number representation safe for display."""

        return f"{self.cano[:4]}****-**"


def load_kis_credentials(credentials_path: Path | None = None) -> KisCredentials:
    """Load the one supported KIS credential file without dotenv or environment lookup."""

    path = (
        Path.home() / ".config" / "phalanx" / "credentials.env"
        if credentials_path is None
        else Path(credentials_path)
    )
    contents = _read_private_file(path)
    values = _parse_credentials(contents)
    try:
        return KisCredentials(
            app_key=SecretStr(values["app_key"]),
            app_secret=SecretStr(values["app_secret"]),
            account_number=SecretStr(values["account_number"]),
        )
    except ValidationError:
        raise ConfigError("KIS credential values are invalid. " + _SAFE_SETUP_GUIDANCE) from None


def _read_private_file(path: Path) -> str:
    directory_fd: int | None = None
    file_fd: int | None = None
    try:
        directory_before = os.lstat(path.parent)
        _validate_directory_stat(directory_before)

        directory_fd = os.open(
            path.parent,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
        )
        directory_opened = os.fstat(directory_fd)
        _validate_directory_stat(directory_opened)
        if not _same_file(directory_before, directory_opened):
            raise ConfigError(_SAFE_SETUP_GUIDANCE)

        file_before = os.stat(path.name, dir_fd=directory_fd, follow_symlinks=False)
        _validate_file_stat(file_before)
        file_fd = os.open(
            path.name,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=directory_fd,
        )
        file_opened = os.fstat(file_fd)
        _validate_file_stat(file_opened)
        if not _same_file(file_before, file_opened):
            raise ConfigError(_SAFE_SETUP_GUIDANCE)

        with os.fdopen(file_fd, mode="r", encoding="utf-8", errors="strict") as handle:
            file_fd = None
            contents = handle.read(_MAX_CREDENTIAL_FILE_BYTES + 1)
        if len(contents.encode("utf-8")) > _MAX_CREDENTIAL_FILE_BYTES:
            raise ConfigError("KIS credential file is unexpectedly large. " + _SAFE_SETUP_GUIDANCE)
        return contents
    except ConfigError:
        raise
    except (OSError, UnicodeError):
        raise ConfigError(_SAFE_SETUP_GUIDANCE) from None
    finally:
        if file_fd is not None:
            os.close(file_fd)
        if directory_fd is not None:
            os.close(directory_fd)


def _validate_directory_stat(file_stat: os.stat_result) -> None:
    if not stat.S_ISDIR(file_stat.st_mode):
        raise ConfigError(_SAFE_SETUP_GUIDANCE)
    if file_stat.st_uid != os.geteuid():
        raise ConfigError(_SAFE_SETUP_GUIDANCE)
    if stat.S_IMODE(file_stat.st_mode) != 0o700:
        raise ConfigError(_SAFE_SETUP_GUIDANCE)


def _validate_file_stat(file_stat: os.stat_result) -> None:
    if not stat.S_ISREG(file_stat.st_mode):
        raise ConfigError(_SAFE_SETUP_GUIDANCE)
    if file_stat.st_uid != os.geteuid():
        raise ConfigError(_SAFE_SETUP_GUIDANCE)
    if stat.S_IMODE(file_stat.st_mode) != 0o600:
        raise ConfigError(_SAFE_SETUP_GUIDANCE)


def _same_file(first: os.stat_result, second: os.stat_result) -> bool:
    return (first.st_dev, first.st_ino) == (second.st_dev, second.st_ino)


def _parse_credentials(contents: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for raw_line in contents.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue

        key, separator, value = raw_line.partition("=")
        if separator != "=" or not key or key != key.strip():
            raise ConfigError(
                "KIS credential file contains an invalid row. " + _SAFE_SETUP_GUIDANCE
            )
        if key not in _CREDENTIAL_KEYS:
            raise ConfigError(
                "KIS credential file contains an unknown key. " + _SAFE_SETUP_GUIDANCE
            )
        if key in parsed:
            raise ConfigError(
                "KIS credential file contains a duplicate key. " + _SAFE_SETUP_GUIDANCE
            )
        if not value.strip():
            raise ConfigError(
                "KIS credential file contains an empty value. " + _SAFE_SETUP_GUIDANCE
            )
        parsed[key] = value

    missing_keys = _CREDENTIAL_KEYS.keys() - parsed.keys()
    if missing_keys:
        raise ConfigError("KIS credential file is missing required keys. " + _SAFE_SETUP_GUIDANCE)

    return {_CREDENTIAL_KEYS[key]: parsed[key] for key in _CREDENTIAL_KEYS}
