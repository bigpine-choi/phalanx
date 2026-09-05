"""Automatic private storage of complete account overview observations."""

from __future__ import annotations

import json
import secrets
from pathlib import Path
from zoneinfo import ZoneInfo

from phalanx.domain.account_overview import AccountOverview
from phalanx.portfolio.private_json_storage import (
    PrivateJsonDirectoryError,
    store_private_json_bytes,
)
from phalanx.snapshots import SnapshotStorageError, _ensure_private_directory


def serialize_account_overview(overview: AccountOverview) -> bytes:
    """Preserve Decimal strings and source observations without runtime file paths."""

    return (
        json.dumps(
            overview.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


class JsonAccountOverviewStore:
    """Linux/WSL adapter; future platform adapters can implement the same save contract."""

    def __init__(self, directory: Path | None = None) -> None:
        self.directory = directory

    def save(self, overview: AccountOverview) -> Path:
        payload = serialize_account_overview(overview)
        directory = self.directory
        if directory is None:
            directory = Path.home() / ".local" / "share" / "phalanx" / "account-overviews"
        try:
            private_directory = _ensure_private_directory(directory)
        except (SnapshotStorageError, OSError):
            raise PrivateJsonDirectoryError(
                "통합 현황 저장 폴더를 안전하게 준비하지 못했습니다."
            ) from None
        observed_at = overview.observation_completed_at.astimezone(ZoneInfo("Asia/Seoul"))
        filename = f"account_overview_{observed_at:%Y%m%dT%H%M%S%f%z}_{secrets.token_hex(8)}.json"
        return store_private_json_bytes(private_directory / filename, payload)
