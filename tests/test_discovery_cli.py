from __future__ import annotations

from pathlib import Path

import pytest
from discovery_helpers import archive, master, provider
from typer.testing import CliRunner

import phalanx.discovery.cli as discovery_cli
from phalanx.cli import app
from phalanx.discovery.errors import DiscoveryStorageError
from phalanx.discovery.repository import SqliteDiscoveryRepository
from phalanx.discovery.service import DiscoveryService
from phalanx.domain.discovery import Market


def test_refresh_list_filter_show_and_no_network_on_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "discovery" / "data.sqlite3"
    repository = SqliteDiscoveryRepository(path)
    source = provider(
        {
            Market.KOSPI: archive(Market.KOSPI, master()),
            Market.KOSDAQ: archive(Market.KOSDAQ, master(Market.KOSDAQ, {85: b"Y"})),
        }
    )
    service = DiscoveryService(repository, source)
    monkeypatch.setattr(discovery_cli, "build_service", lambda path: service)
    runner = CliRunner()
    refresh = runner.invoke(app, ["discovery", "refresh"])
    assert refresh.exit_code == 0, refresh.output
    assert "수집 상태: success" in refresh.stdout
    assert "KOSPI: 전체 1 / 정규화 1 / 적격 1 / 제외 0 / 미확인 0" in refresh.stdout
    assert "KOSDAQ: 전체 1 / 정규화 1 / 적격 0 / 제외 1 / 미확인 0" in refresh.stdout
    assert str(path) in refresh.stdout
    assert "미검증" in refresh.stdout

    monkeypatch.setattr(
        source, "download", lambda *args: pytest.fail("offline commands must not download")
    )
    original = path.read_bytes()
    eligible = runner.invoke(app, ["discovery", "list", "--status", "eligible"])
    excluded = runner.invoke(app, ["discovery", "list", "--status", "excluded"])
    unknown = runner.invoke(app, ["discovery", "list", "--status", "unknown"])
    shown = runner.invoke(app, ["discovery", "show", "005930"])
    assert all(r.exit_code == 0 for r in [eligible, excluded, unknown, shown])
    assert "005930" in eligible.stdout and "035900" not in eligible.stdout
    assert "035900" in excluded.stdout and "005930" not in excluded.stdout
    assert "005930" not in unknown.stdout and "035900" not in unknown.stdout
    for expected in (
        "삼성전자",
        "KR7005930003",
        '"issuer_id": null',
        "raw_fields",
        "V2_PASSED",
        "provider_as_of",
        "http_last_modified",
        "sha256",
        "schema_version",
        "parser_version",
        "policy_version",
    ):
        assert expected in shown.stdout
    assert path.read_bytes() == original
    assert runner.invoke(app, ["discovery", "list", "--status", "invalid"]).exit_code == 2
    missing = runner.invoke(app, ["discovery", "show", "5930"])
    assert missing.exit_code == 1
    assert "상장폐지를 의미하지 않습니다" in missing.stdout


@pytest.mark.parametrize("command", [["list"], ["show", "005930"]])
def test_missing_store_asks_to_refresh_without_creating_files(
    tmp_path: Path, command: list[str]
) -> None:
    path = tmp_path / "missing" / "data.sqlite3"
    result = CliRunner().invoke(app, ["discovery", *command, "--db", str(path)])
    assert result.exit_code == 1
    assert "phalanx discovery refresh가 필요합니다" in result.stdout
    assert not path.parent.exists()


def test_failed_refresh_and_stale_reads_have_nonzero_status_and_failure_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = SqliteDiscoveryRepository(tmp_path / "d" / "data.sqlite3")
    first = DiscoveryService(repository, provider()).refresh()
    service = DiscoveryService(
        repository,
        provider({Market.KOSPI: 500, Market.KOSDAQ: archive(Market.KOSDAQ, master(Market.KOSDAQ))}),
    )
    monkeypatch.setattr(discovery_cli, "build_service", lambda path: service)
    runner = CliRunner()
    refresh = runner.invoke(app, ["discovery", "refresh"])
    assert refresh.exit_code == 1
    assert "partial" in refresh.stdout
    assert "다운로드 failed" in refresh.stdout
    assert first.run_id in refresh.stdout
    for command in (["list"], ["show", "005930"]):
        result = runner.invoke(app, ["discovery", *command])
        assert result.exit_code == 1
        assert "최근 수집이 정상이 아닙니다" in result.stdout
        assert "DOWNLOAD_HTTP" in result.stdout
        assert first.run_id in result.stdout
        assert first.collection_completed_at.isoformat() in result.stdout
        assert "005930" in result.stdout


def test_storage_error_exit_and_no_raw_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = DiscoveryService(
        SqliteDiscoveryRepository(tmp_path / "d" / "data.sqlite3"), provider()
    )

    def fail() -> None:
        raise DiscoveryStorageError()

    monkeypatch.setattr(service, "refresh", fail)
    monkeypatch.setattr(discovery_cli, "build_service", lambda path: service)
    result = CliRunner().invoke(app, ["discovery", "refresh"])
    assert result.exit_code == 66
    assert "후보 저장소 오류" in result.stderr
    assert "Traceback" not in result.output


def test_interrupted_attempt_is_reported_in_offline_query(tmp_path: Path) -> None:
    repository = SqliteDiscoveryRepository(tmp_path / "d" / "data.sqlite3")
    first = DiscoveryService(repository, provider()).refresh()
    repository.begin("interrupted", first.collection_completed_at)
    result = CliRunner().invoke(app, ["discovery", "list", "--db", str(repository.path)])
    assert result.exit_code == 1
    assert "interrupted" in result.stdout
    assert "in_progress" in result.stdout
    assert first.run_id in result.stdout


def test_help_exposes_only_authorized_commands() -> None:
    result = CliRunner().invoke(app, ["discovery", "--help"])
    assert result.exit_code == 0
    assert all(command in result.stdout for command in ("refresh", "list", "show"))
    assert all(
        command not in result.stdout for command in ("order", "optimize", "rank", "--account")
    )
