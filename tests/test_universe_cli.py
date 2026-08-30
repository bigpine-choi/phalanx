from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

import phalanx.cli as cli
from phalanx.universe.repository import JsonUniverseRepository
from phalanx.universe.service import UniverseService


def _patch_service(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    path = tmp_path / "data" / "universe.json"
    monkeypatch.setattr(
        cli,
        "_build_universe_service",
        lambda: UniverseService(JsonUniverseRepository(path)),
    )
    return path


def test_all_universe_commands_share_persistent_service_and_render_status_table(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _patch_service(tmp_path, monkeypatch)
    runner = CliRunner()

    empty = runner.invoke(cli.app, ["universe", "list"], color=False)
    first_add = runner.invoke(
        cli.app,
        [
            "universe",
            "add",
            "005930",
            "삼성전자",
            "--market",
            "KOSPI",
            "--note",
            "반도체 대형주",
        ],
        color=False,
    )
    second_add = runner.invoke(
        cli.app,
        ["universe", "add", "035900", "JYP Ent.", "-m", "KOSDAQ"],
        color=False,
    )
    disabled = runner.invoke(cli.app, ["universe", "disable", "005930"], color=False)
    listed = runner.invoke(cli.app, ["universe", "list"], color=False)

    assert empty.exit_code == 0
    assert "비어 있습니다" in empty.stdout
    assert first_add.exit_code == 0
    assert "등록됨: 005930 삼성전자 (KOSPI) · 활성" in first_add.stdout
    assert second_add.exit_code == 0
    assert disabled.exit_code == 0
    assert "비활성화됨: 005930 삼성전자" in disabled.stdout
    assert listed.exit_code == 0
    for expected in (
        "투자 후보 유니버스",
        "상태",
        "종목코드",
        "비활성",
        "005930",
        "삼성전자",
        "KOSPI",
        "반도체 대형주",
        "활성",
        "035900",
        "JYP Ent.",
        "KOSDAQ",
    ):
        assert expected in listed.stdout
    assert path.is_file()

    enabled = runner.invoke(cli.app, ["universe", "enable", "005930"], color=False)
    removed = runner.invoke(cli.app, ["universe", "remove", "035900"], color=False)
    final_list = runner.invoke(cli.app, ["universe", "list"], color=False)

    assert enabled.exit_code == 0
    assert "활성화됨: 005930 삼성전자" in enabled.stdout
    assert removed.exit_code == 0
    assert "삭제됨: 035900 JYP Ent." in removed.stdout
    assert "035900" not in final_list.stdout
    assert "005930" in final_list.stdout


@pytest.mark.parametrize(
    ("arguments", "expected_message"),
    (
        (
            ["universe", "add", "5930", "삼성전자", "--market", "KOSPI"],
            "종목코드는 공백 없는 6자리 숫자",
        ),
        (
            ["universe", "add", "005930", "삼성전자", "--market", "KONEX"],
            "지원하지 않는 시장 'KONEX'",
        ),
        (
            ["universe", "enable", "000660"],
            "종목코드 000660는 유니버스에 등록되어 있지 않습니다",
        ),
        (
            ["universe", "disable", "000660"],
            "종목코드 000660는 유니버스에 등록되어 있지 않습니다",
        ),
        (
            ["universe", "remove", "000660"],
            "종목코드 000660는 유니버스에 등록되어 있지 않습니다",
        ),
    ),
)
def test_cli_prints_clear_domain_errors_with_stable_exit_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    arguments: list[str],
    expected_message: str,
) -> None:
    _patch_service(tmp_path, monkeypatch)

    result = CliRunner().invoke(cli.app, arguments, color=False)

    assert result.exit_code == cli.ExitCode.UNIVERSE
    assert result.stdout == ""
    assert "유니버스 오류" in result.stderr
    assert expected_message in result.stderr
    assert "Traceback" not in result.stderr


def test_cli_reports_duplicate_stock_without_modifying_original(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _patch_service(tmp_path, monkeypatch)
    runner = CliRunner()
    first = runner.invoke(
        cli.app,
        ["universe", "add", "005930", "삼성전자", "--market", "KOSPI"],
        color=False,
    )
    original = path.read_bytes()

    duplicate = runner.invoke(
        cli.app,
        ["universe", "add", "005930", "삼성전자", "--market", "KOSPI"],
        color=False,
    )

    assert first.exit_code == 0
    assert duplicate.exit_code == cli.ExitCode.UNIVERSE
    assert "이미 유니버스에 등록" in duplicate.stderr
    assert path.read_bytes() == original


def test_universe_help_exposes_only_local_management_commands() -> None:
    result = CliRunner().invoke(cli.app, ["universe", "--help"], color=False)

    assert result.exit_code == 0
    for command in ("list", "add", "enable", "disable", "remove"):
        assert command in result.stdout
    for forbidden in ("order", "quote", "optimize", "--universe-path"):
        assert forbidden not in result.stdout
