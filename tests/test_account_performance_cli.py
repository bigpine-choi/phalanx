from __future__ import annotations

from datetime import UTC, datetime
from decimal import ROUND_UP, Decimal, DefaultContext, Inexact, localcontext
from io import StringIO
from pathlib import Path

import pytest
from rich.console import Console
from typer.testing import CliRunner

import phalanx.cli as cli
from phalanx.account_performance import AccountPerformanceError
from phalanx.application import AccountPerformanceInputHashes, AccountPerformanceResult
from phalanx.domain.account_performance import AccountPerformance
from phalanx.portfolio.private_json_storage import (
    PrivateJsonAlreadyExistsError,
    PrivateJsonStorageError,
)


def _result(
    saved_path: Path | None = None,
    *,
    unavailable: bool = False,
) -> AccountPerformanceResult:
    # Presentation-only fixture: the calculation and validated input graph are tested separately.
    performance = AccountPerformance.model_construct(
        start_observed_at=datetime(2026, 1, 1, 14, 59, 59, 123456, tzinfo=UTC),
        end_observed_at=datetime(2026, 1, 3, 15, 0, 1, tzinfo=UTC),
        beginning_net_assets=Decimal("100"),
        ending_net_assets=Decimal("220"),
        total_deposits=Decimal("100"),
        total_withdrawals=Decimal("0"),
        net_cash_flow=Decimal("100"),
        profit_loss=Decimal("20"),
        average_invested_capital=Decimal("150"),
        estimated_return=None if unavailable else Decimal("0.1333333333333333333333333333"),
        return_unavailable_reasons=("기초 순자산이 0 이하입니다.", "평균투하자본이 0 이하입니다.")
        if unavailable
        else (),
    )
    return AccountPerformanceResult(
        performance=performance,
        input_sha256=AccountPerformanceInputHashes("a" * 64, "b" * 64, "c" * 64),
        saved_path=saved_path,
    )


def _command(output: Path | None = None) -> list[str]:
    arguments = [
        "account",
        "performance",
        "--start-snapshot",
        "synthetic-start.json",
        "--end-snapshot",
        "synthetic-end.json",
        "--cash-flows",
        "synthetic-cash-flows.json",
    ]
    if output is not None:
        arguments.extend(("--output", str(output)))
    return arguments


def test_renderer_shows_whole_account_scope_observations_and_independent_decimal_rounding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stdout = StringIO()
    console = Console(file=stdout, width=240, color_system=None, markup=False, highlight=False)
    result = _result()
    monkeypatch.setattr(DefaultContext, "Emax", 0)
    with localcontext() as ambient:
        ambient.prec = 2
        ambient.rounding = ROUND_UP
        ambient.traps[Inexact] = True
        cli.render_account_performance(result, console)

    rendered = stdout.getvalue()
    for expected in (
        "실계좌 전체 기간 성과",
        "시작 관측시각",
        "2026-01-01 23:59:59.123456 KST",
        "종료 관측시각",
        "2026-01-04 00:00:01 KST",
        "기초 순자산",
        "100.00 원",
        "기말 순자산",
        "220.00 원",
        "총입금",
        "총출금",
        "0.00 원",
        "순입출금",
        "기간 운용손익",
        "20.00 원",
        "평균투하자본",
        "150.00 원",
        "기간 추정 수익률 (Modified Dietz)",
        "13.333333%",
        "사용자 제공 외부 입출금 원장을 사용했습니다.",
        "조회 완료시각을 계산용 관측시각으로 사용한 추정입니다.",
        "관측시각은 실제 거래소 평가시각이나 확정 종가시각을 뜻하지 않습니다.",
    ):
        assert expected in rendered
    assert "저장 경로" not in rendered
    assert result.performance.estimated_return == Decimal("0.1333333333333333333333333333")


def test_renderer_shows_all_unavailable_reasons_and_still_displays_profit_loss() -> None:
    stdout = StringIO()
    console = Console(file=stdout, width=240, color_system=None, markup=False, highlight=False)

    cli.render_account_performance(_result(unavailable=True), console)

    rendered = stdout.getvalue()
    assert "미산출: 기초 순자산이 0 이하입니다.; 평균투하자본이 0 이하입니다." in rendered
    assert "기간 운용손익" in rendered
    assert "20.00 원" in rendered
    assert "%" not in rendered


@pytest.mark.parametrize("save_result", (False, True))
def test_command_passes_explicit_inputs_and_optional_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    save_result: bool,
) -> None:
    output = tmp_path / "performance.json" if save_result else None
    calls: list[tuple[Path, Path, Path, Path | None]] = []

    def runner(
        start_snapshot_path: Path,
        end_snapshot_path: Path,
        cash_flows_path: Path,
        *,
        output_path: Path | None = None,
    ) -> AccountPerformanceResult:
        calls.append((start_snapshot_path, end_snapshot_path, cash_flows_path, output_path))
        return _result(output_path)

    monkeypatch.setattr(cli, "run_account_performance", runner)

    result = CliRunner().invoke(cli.app, _command(output), color=False)

    assert result.exit_code == cli.ExitCode.SUCCESS
    assert result.stderr == ""
    assert calls == [
        (
            Path("synthetic-start.json"),
            Path("synthetic-end.json"),
            Path("synthetic-cash-flows.json"),
            output,
        )
    ]
    assert "실계좌 전체 기간 성과" in result.stdout
    if output is not None:
        assert "저장 경로:" in result.stdout
        assert output.name in result.stdout


@pytest.mark.parametrize("missing_option", ("--start-snapshot", "--end-snapshot", "--cash-flows"))
def test_command_requires_each_input_including_explicit_cash_flow_ledger(
    monkeypatch: pytest.MonkeyPatch,
    missing_option: str,
) -> None:
    def unexpected_runner(*args: object, **kwargs: object) -> AccountPerformanceResult:
        pytest.fail("Required input validation must happen before the runner")

    monkeypatch.setattr(cli, "run_account_performance", unexpected_runner)
    command = _command()
    missing_index = command.index(missing_option)
    del command[missing_index : missing_index + 2]

    result = CliRunner().invoke(cli.app, command, color=False)

    assert result.exit_code == 2
    assert missing_option in result.stderr


@pytest.mark.parametrize(
    ("error", "expected_code", "message"),
    (
        (
            AccountPerformanceError("합성 데이터: 입출금 발생시각이 조회 구간에 포함됩니다."),
            cli.ExitCode.ACCOUNT_PERFORMANCE,
            "입출금 발생시각이 조회 구간에 포함됩니다.",
        ),
        (
            PrivateJsonAlreadyExistsError("synthetic-sensitive-storage-detail"),
            cli.ExitCode.ACCOUNT_PERFORMANCE_STORAGE,
            "이미 존재합니다",
        ),
        (
            PrivateJsonStorageError("synthetic-sensitive-storage-detail"),
            cli.ExitCode.ACCOUNT_PERFORMANCE_STORAGE,
            "안전하게 저장하지 못했습니다",
        ),
        (
            KeyboardInterrupt(),
            cli.ExitCode.INTERRUPTED,
            "안전하게 종료했습니다",
        ),
        (
            RuntimeError("synthetic-sensitive-storage-detail"),
            cli.ExitCode.UNEXPECTED,
            "예기치 않은 오류",
        ),
    ),
)
def test_command_reports_safe_errors_and_stable_exit_codes(
    monkeypatch: pytest.MonkeyPatch,
    error: BaseException,
    expected_code: cli.ExitCode,
    message: str,
) -> None:
    def runner(*args: object, **kwargs: object) -> AccountPerformanceResult:
        raise error

    monkeypatch.setattr(cli, "run_account_performance", runner)

    result = CliRunner().invoke(cli.app, _command(), color=False)

    assert result.exit_code == expected_code
    assert message in " ".join(result.stderr.split())
    assert result.stdout == ""
    assert "synthetic-sensitive-storage-detail" not in result.stderr
    assert "Traceback" not in result.stderr


def test_help_describes_offline_whole_account_analysis_and_write_once_output() -> None:
    result = CliRunner().invoke(cli.app, ["account", "performance", "--help"], color=False)

    assert result.exit_code == 0
    for expected in (
        "--start-snapshot",
        "--end-snapshot",
        "--cash-flows",
        "--output",
        "실계좌 전체",
        "오프라인",
        "덮어쓰기",
        "금지",
    ):
        assert expected in result.stdout
