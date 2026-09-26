"""Create a consistent, closed Linux history backup for transfer to Windows.

Run with the Linux/WSL environment. This module deliberately does not import the
CLI aggregator, start the GUI, or copy an active SQLite file and its sidecars.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from collections.abc import Sequence
from pathlib import Path
from tempfile import TemporaryDirectory

from phalanx.market_data.history.errors import HistoryError, HistoryStorageError
from phalanx.market_data.history.reader import validate_database
from phalanx.portfolio.private_json_storage import (
    PrivateJsonStorageError,
    store_private_json_bytes,
)


def export_history_snapshot(source: Path, output: Path) -> Path:
    """Backup one guarded read transaction and publish exact bytes without overwrite."""
    if not sys.platform.startswith("linux"):
        raise HistoryStorageError()
    # Keep native-only repository imports outside the portable desktop graph.
    from phalanx.market_data.history.repository import SqliteHistoryRepository

    repository = SqliteHistoryRepository(source)
    with TemporaryDirectory(prefix="phalanx-history-export-") as directory:
        temporary = Path(directory) / "history.sqlite3"
        descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(descriptor)
        with repository._connect() as original:
            destination = sqlite3.connect(temporary, isolation_level=None)
            try:
                original.backup(destination)
                destination.execute("PRAGMA journal_mode = DELETE")
                validate_database(destination)
            finally:
                destination.close()
        # Reopen through the existing Linux checks, including sidecars and file
        # identity, only after the backup writer is fully closed.
        with SqliteHistoryRepository(temporary)._connect():
            payload = temporary.read_bytes()
        return store_private_json_bytes(output, payload)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Windows로 옮길 일관된 일봉 DB 백업을 만듭니다.")
    parser.add_argument("--source", required=True, type=Path, help="Linux/WSL 원본 history DB")
    parser.add_argument("--output", required=True, type=Path, help="새 백업 파일; 덮어쓰기 금지")
    arguments = parser.parse_args(None if argv is None else list(argv))
    if not sys.platform.startswith("linux"):
        print("이 백업 명령은 원본 DB가 있는 Linux/WSL Python에서 실행하세요.", file=sys.stderr)
        return 2
    try:
        result = export_history_snapshot(arguments.source, arguments.output)
    except (HistoryError, PrivateJsonStorageError, OSError, sqlite3.Error):
        print(
            "백업하지 못했습니다. 원본 DB·권한과 출력 경로를 확인하세요. "
            "출력은 새 파일이어야 합니다.",
            file=sys.stderr,
        )
        return 2
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
