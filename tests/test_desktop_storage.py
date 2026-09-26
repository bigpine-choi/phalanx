from __future__ import annotations

import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from phalanx.desktop.storage import (
    DEFAULT_SETTINGS,
    SettingsStore,
    StorageError,
    app_data_directory,
    read_selected_file,
    store_result,
)
from phalanx.portfolio.private_json_storage import PrivateJsonStorageError


def test_settings_only_persist_supported_values(tmp_path: Path) -> None:
    store = SettingsStore(tmp_path / "prefs")
    assert store.load().settings == DEFAULT_SETTINGS
    assert store.load().notice is None
    settings = {"sfxVolume": 0, "musicVolume": 100, "reduceMotion": True}
    assert store.save(settings) == settings
    assert store.load().settings == settings
    assert json.loads(store.path.read_bytes()) == settings
    with pytest.raises(StorageError):
        store.save({**settings, "credentials": "never persist"})
    assert store.load().settings == settings


@pytest.mark.parametrize("bad", [True, -1, 101, 2.5, "12"])
def test_settings_reject_invalid_volume(tmp_path: Path, bad: object) -> None:
    store = SettingsStore(tmp_path / "prefs")
    with pytest.raises(StorageError):
        store.save({**DEFAULT_SETTINGS, "sfxVolume": bad})


def test_corrupt_settings_restore_defaults_with_notice(tmp_path: Path) -> None:
    store = SettingsStore(tmp_path / "prefs")
    store.save(DEFAULT_SETTINGS)
    store.path.write_bytes(b"{ broken }")
    recovered = store.load()
    assert recovered.settings == DEFAULT_SETTINGS
    assert recovered.notice
    store.save({**DEFAULT_SETTINGS, "reduceMotion": True})
    assert store.load().notice is None


def test_selection_read_is_bounded_and_preserves_exact_bytes(tmp_path: Path) -> None:
    path = tmp_path / "한글 입력.json"
    payload = b'{"value":"literal bytes"}\r\n'
    path.write_bytes(payload)
    assert read_selected_file(path, len(payload)) == payload
    with pytest.raises((StorageError, OSError)):
        read_selected_file(path, len(payload) - 1)
    with pytest.raises(FileNotFoundError):
        read_selected_file(tmp_path / "absent.json", 10)


def test_result_collision_has_one_exact_winner(tmp_path: Path) -> None:
    path = tmp_path / "한글 결과.json"
    payloads = [b'{"input":1}\n', b'{"input":2}\r\n']

    def save(payload: bytes) -> bytes | None:
        try:
            store_result(path, payload)
            return payload
        except (PrivateJsonStorageError, OSError):
            return None

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(save, payloads))
    successes = [outcome for outcome in outcomes if outcome is not None]
    assert len(successes) == 1
    assert path.read_bytes() == successes[0]
    assert not list(tmp_path.glob("*.tmp"))
    assert not list(tmp_path.glob(".*.tmp"))


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission and symlink checks")
def test_linux_selection_rejects_links_and_result_is_private(tmp_path: Path) -> None:
    path = tmp_path / "input.json"
    path.write_bytes(b"{}")
    alias = tmp_path / "link.json"
    alias.symlink_to(path)
    with pytest.raises(OSError):
        read_selected_file(alias, 100)
    alias.unlink()
    os.link(path, alias)
    with pytest.raises(StorageError):
        read_selected_file(path, 100)
    result = store_result(tmp_path / "result.json", b"{}")
    assert result.stat().st_mode & 0o777 == 0o600


@pytest.mark.skipif(sys.platform == "win32", reason="XDG and POSIX directory permissions")
def test_app_data_is_outside_checkout_and_private(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    directory = app_data_directory()
    assert directory == tmp_path / "phalanx"
    assert directory.stat().st_mode & 0o777 == 0o700
    (tmp_path / ".git").mkdir()
    with pytest.raises(StorageError, match="Git"):
        app_data_directory()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX atomic rename injection")
def test_failed_settings_publish_cleans_temporary_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = SettingsStore(tmp_path / "prefs")
    store.save(DEFAULT_SETTINGS)
    original = store.path.read_bytes()

    def fail(*_args: object) -> None:
        raise OSError("injected rename failure")

    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(OSError):
        store.save({**DEFAULT_SETTINGS, "reduceMotion": True})
    assert store.path.read_bytes() == original
    assert list(store.directory.iterdir()) == [store.path]
