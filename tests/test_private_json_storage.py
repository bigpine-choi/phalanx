from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest
from filelock import FileLock

import phalanx.portfolio.private_json_storage as private_storage
from phalanx.portfolio.private_json_storage import (
    PrivateJsonAlreadyExistsError,
    PrivateJsonLockTimeoutError,
    PrivateJsonStorageError,
    store_private_json_bytes,
)


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat(follow_symlinks=False).st_mode)


def test_stores_exact_bytes_with_private_directory_file_and_lock_modes(
    tmp_path: Path,
) -> None:
    output = tmp_path / "private" / "risk_trial.json"
    payload = b'{"schema_version":"1","opaque":"exact bytes"}\n'

    saved = store_private_json_bytes(output, payload)

    assert saved == output
    assert output.read_bytes() == payload
    assert _mode(output.parent) == 0o700
    assert _mode(output) == 0o600
    assert _mode(output.parent / f".{output.name}.lock") == 0o600


def test_refuses_to_overwrite_existing_output_without_changing_it(tmp_path: Path) -> None:
    output = tmp_path / "risk_trial.json"
    output.write_bytes(b"existing")

    with pytest.raises(PrivateJsonAlreadyExistsError):
        store_private_json_bytes(output, b"replacement")

    assert output.read_bytes() == b"existing"


def test_temporary_file_is_private_and_directory_fsync_runs_after_exclusive_publish(
    tmp_path: Path,
) -> None:
    output = tmp_path / "private" / "risk_trial.json"
    payload = b'{"exact":true}\n'
    original_link = os.link
    observed_temporary_modes: list[int] = []
    fsynced_directories: list[Path] = []

    def inspect_then_link(source: Path, target: Path) -> None:
        observed_temporary_modes.append(_mode(source))
        original_link(source, target)

    def record_directory_fsync(directory: Path) -> None:
        assert output.read_bytes() == payload
        fsynced_directories.append(directory)

    store_private_json_bytes(
        output,
        payload,
        link=inspect_then_link,
        fsync_directory=record_directory_fsync,
    )

    assert observed_temporary_modes == [0o600]
    assert fsynced_directories == [output.parent]


def test_write_failure_cleans_temporary_file_and_leaves_no_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "private" / "risk_trial.json"

    def fail_write(descriptor: int, payload: bytes) -> None:
        raise OSError("synthetic write failure")

    monkeypatch.setattr(private_storage, "_write_all", fail_write)

    with pytest.raises(PrivateJsonStorageError, match="atomic write"):
        store_private_json_bytes(output, b'{"never":"stored"}\n')

    assert not output.exists()
    assert list(output.parent.glob(f".{output.name}.*.tmp")) == []


def test_exclusive_publish_preserves_racing_output_and_cleans_temporary_file(
    tmp_path: Path,
) -> None:
    output = tmp_path / "private" / "risk_trial.json"
    racing_bytes = b"racing existing output"
    original_link = os.link

    def race_then_link(source: Path, target: Path) -> None:
        assert source.name.startswith(f".{output.name}.")
        assert target == output
        output.write_bytes(racing_bytes)
        original_link(source, target)

    with pytest.raises(PrivateJsonAlreadyExistsError, match="already exists"):
        store_private_json_bytes(output, b'{"new":"payload"}\n', link=race_then_link)

    assert output.read_bytes() == racing_bytes
    assert list(output.parent.glob(f".{output.name}.*.tmp")) == []


def test_hard_link_publish_failure_is_fail_closed_without_fallback(tmp_path: Path) -> None:
    output = tmp_path / "private" / "risk_trial.json"

    def fail_link(source: Path, target: Path) -> None:
        assert source.name.startswith(f".{output.name}.")
        assert target == output
        raise OSError("hard links unsupported")

    with pytest.raises(PrivateJsonStorageError, match="atomic write"):
        store_private_json_bytes(output, b'{"never":"stored"}\n', link=fail_link)

    assert not output.exists()
    assert list(output.parent.glob(f".{output.name}.*.tmp")) == []


def test_directory_fsync_failure_leaves_only_complete_published_output(tmp_path: Path) -> None:
    output = tmp_path / "private" / "risk_trial.json"
    payload = b'{"complete":true}\n'

    def fail_directory_fsync(directory: Path) -> None:
        assert directory == output.parent
        assert output.read_bytes() == payload
        raise OSError("synthetic directory fsync failure")

    with pytest.raises(PrivateJsonStorageError, match="atomic write"):
        store_private_json_bytes(output, payload, fsync_directory=fail_directory_fsync)

    assert output.read_bytes() == payload
    assert list(output.parent.glob(f".{output.name}.*.tmp")) == []


def test_output_specific_lock_timeout_has_dedicated_error(tmp_path: Path) -> None:
    output = tmp_path / "private" / "risk_trial.json"
    output.parent.mkdir()
    lock_path = output.parent / f".{output.name}.lock"

    with FileLock(lock_path, mode=0o600), pytest.raises(PrivateJsonLockTimeoutError):
        store_private_json_bytes(output, b"{}\n", lock_timeout=0)

    assert not output.exists()
    assert list(output.parent.glob(f".{output.name}.*.tmp")) == []
