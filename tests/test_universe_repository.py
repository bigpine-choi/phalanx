from __future__ import annotations

import json
import os
import stat
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

import phalanx.universe.repository as universe_repository
from phalanx.domain import KoreanStock, StockMarket
from phalanx.universe.errors import (
    CorruptUniverseError,
    DuplicateStockError,
    UniverseStorageError,
    UnsafeUniversePathError,
)
from phalanx.universe.repository import JsonUniverseRepository, default_universe_path


def _stock(
    stock_code: str = "005930",
    stock_name: str = "삼성전자",
    market: StockMarket = StockMarket.KOSPI,
) -> KoreanStock:
    return KoreanStock(
        stock_code=stock_code,
        stock_name=stock_name,
        market=market,
        enabled=True,
        note="합성 테스트 메모",
    )


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat(follow_symlinks=False).st_mode)


def _write_private(path: Path, contents: str) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(descriptor, contents.encode("utf-8"))
    finally:
        os.close(descriptor)


@pytest.mark.parametrize(
    ("platform_name", "expected_parts"),
    (
        ("linux", (".local", "share", "phalanx", "universe.json")),
        ("darwin", ("Library", "Application Support", "Phalanx", "universe.json")),
        ("win32", ("AppData", "Local", "Phalanx", "universe.json")),
    ),
)
def test_default_path_uses_os_specific_user_data_directory(
    tmp_path: Path,
    platform_name: str,
    expected_parts: tuple[str, ...],
) -> None:
    home = tmp_path / "home"

    assert default_universe_path(home=home, platform_name=platform_name) == home.joinpath(
        *expected_parts
    )


def test_injected_repository_path_never_resolves_home(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_home(cls: type[Path]) -> Path:
        raise AssertionError("Path.home must not be called for an injected universe path")

    monkeypatch.setattr(Path, "home", classmethod(fail_home))
    path = tmp_path / "data" / "universe.json"
    repository = JsonUniverseRepository(path)

    repository.add(_stock())

    assert repository.path == path
    assert repository.list_all() == (_stock(),)


def test_missing_universe_is_empty_without_creating_directories(tmp_path: Path) -> None:
    path = tmp_path / "data" / "universe.json"
    repository = JsonUniverseRepository(path)

    assert repository.list_all() == ()
    assert not path.parent.exists()


def test_repository_persists_versioned_utf8_json_with_private_modes(tmp_path: Path) -> None:
    path = tmp_path / "data" / "universe.json"
    repository = JsonUniverseRepository(path)
    first = _stock()
    second = _stock("035720", "카카오", StockMarket.KOSDAQ)

    repository.add(first)
    repository.add(second)

    assert repository.list_all() == (first, second)
    assert _mode(path.parent) == 0o700
    assert _mode(path) == 0o600
    assert _mode(repository.lock_path) == 0o600
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload == {
        "schema_version": "1",
        "stocks": [
            {
                "enabled": True,
                "market": "KOSPI",
                "note": "합성 테스트 메모",
                "stock_code": "005930",
                "stock_name": "삼성전자",
            },
            {
                "enabled": True,
                "market": "KOSDAQ",
                "note": "합성 테스트 메모",
                "stock_code": "035720",
                "stock_name": "카카오",
            },
        ],
    }


def test_atomic_temporary_file_is_private_before_replace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "data" / "universe.json"
    repository = JsonUniverseRepository(path)
    original_replace = universe_repository.os.replace
    observed_modes: list[int] = []

    def inspect_then_replace(
        source: str,
        destination: str,
        *,
        src_dir_fd: int | None = None,
        dst_dir_fd: int | None = None,
    ) -> None:
        temporary_files = tuple(path.parent.glob(f".{path.name}.*.tmp"))
        assert len(temporary_files) == 1
        observed_modes.append(_mode(temporary_files[0]))
        original_replace(
            source,
            destination,
            src_dir_fd=src_dir_fd,
            dst_dir_fd=dst_dir_fd,
        )

    monkeypatch.setattr(universe_repository.os, "replace", inspect_then_replace)

    repository.add(_stock())

    assert observed_modes == [0o600]


def test_atomic_replace_failure_preserves_existing_file_and_repository_recovers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "data" / "universe.json"
    repository = JsonUniverseRepository(path)
    repository.add(_stock())
    original_contents = path.read_bytes()
    original_replace = universe_repository.os.replace

    def fail_replace(*args: object, **kwargs: object) -> None:
        raise OSError("synthetic replace failure")

    monkeypatch.setattr(universe_repository.os, "replace", fail_replace)
    with pytest.raises(UniverseStorageError, match="원자적으로 저장"):
        repository.add(_stock("035720", "카카오", StockMarket.KOSDAQ))

    assert path.read_bytes() == original_contents
    assert repository.list_all() == (_stock(),)
    assert not tuple(path.parent.glob(f".{path.name}.*.tmp"))

    monkeypatch.setattr(universe_repository.os, "replace", original_replace)
    repository.add(_stock("035720", "카카오", StockMarket.KOSDAQ))
    assert tuple(stock.stock_code for stock in repository.list_all()) == ("005930", "035720")


def test_write_failure_leaves_no_partial_universe_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "data" / "universe.json"
    repository = JsonUniverseRepository(path)

    def fail_write(_file_fd: int, _payload: bytes) -> None:
        raise OSError("synthetic write failure")

    monkeypatch.setattr(universe_repository, "_write_all", fail_write)

    with pytest.raises(UniverseStorageError):
        repository.add(_stock())

    assert not path.exists()
    assert not tuple(path.parent.glob(f".{path.name}.*.tmp"))


def test_corrupt_json_is_reported_and_never_silently_replaced(tmp_path: Path) -> None:
    path = tmp_path / "data" / "universe.json"
    corrupt_contents = "{not valid json\n"
    _write_private(path, corrupt_contents)
    repository = JsonUniverseRepository(path)

    with pytest.raises(CorruptUniverseError, match="손상"):
        repository.list_all()
    with pytest.raises(CorruptUniverseError):
        repository.add(_stock())

    assert path.read_text(encoding="utf-8") == corrupt_contents


def test_duplicate_codes_in_existing_file_are_reported_as_corruption(tmp_path: Path) -> None:
    path = tmp_path / "data" / "universe.json"
    record = {
        "stock_code": "005930",
        "stock_name": "삼성전자",
        "market": "KOSPI",
        "enabled": True,
        "note": None,
    }
    _write_private(
        path,
        json.dumps({"schema_version": "1", "stocks": [record, record]}, ensure_ascii=False),
    )

    with pytest.raises(CorruptUniverseError, match="중복 종목코드"):
        JsonUniverseRepository(path).list_all()


def test_universe_file_symbolic_link_is_rejected_without_touching_target(tmp_path: Path) -> None:
    directory = tmp_path / "data"
    directory.mkdir(mode=0o700)
    victim = tmp_path / "victim.json"
    _write_private(victim, "do not modify")
    path = directory / "universe.json"
    path.symlink_to(victim)

    with pytest.raises(UnsafeUniversePathError, match="심볼릭 링크"):
        JsonUniverseRepository(path).list_all()

    assert victim.read_text(encoding="utf-8") == "do not modify"


def test_insecure_existing_directory_is_rejected_without_chmod(tmp_path: Path) -> None:
    directory = tmp_path / "data"
    directory.mkdir(mode=0o700)
    directory.chmod(0o755)
    repository = JsonUniverseRepository(directory / "universe.json")

    with pytest.raises(UnsafeUniversePathError, match="0700"):
        repository.add(_stock())

    assert _mode(directory) == 0o755
    assert not (directory / "universe.json").exists()


def test_concurrent_duplicate_add_has_exactly_one_winner(tmp_path: Path) -> None:
    path = tmp_path / "data" / "universe.json"
    repositories = (JsonUniverseRepository(path), JsonUniverseRepository(path))

    def add(repository: JsonUniverseRepository) -> str:
        try:
            repository.add(_stock())
        except DuplicateStockError:
            return "duplicate"
        return "added"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(add, repositories))

    assert sorted(results) == ["added", "duplicate"]
    assert repositories[0].list_all() == (_stock(),)
