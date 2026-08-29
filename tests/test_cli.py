from __future__ import annotations

import re
import runpy
import sys
from datetime import datetime, timedelta
from decimal import Decimal
from io import StringIO
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from rich.console import Console
from typer.testing import CliRunner

import phalanx.cli as cli
from phalanx.application import AccountSnapshotResult
from phalanx.config import ConfigError
from phalanx.domain import (
    AccountPosition,
    AccountSnapshot,
    AccountSummary,
    ApiPageEvidence,
    SnapshotEvidence,
)
from phalanx.kis.errors import KisAuthError, KisBalanceHttpError
from phalanx.snapshots import SnapshotStorageError

SEOUL = ZoneInfo("Asia/Seoul")
STARTED_AT = datetime(2026, 8, 29, 12, 34, 56, 123456, tzinfo=SEOUL)
COMPLETED_AT = STARTED_AT + timedelta(seconds=2)
SECRETS = (
    "synthetic-cli-app-key",
    "synthetic-cli-app-secret",
    "55667788-01",
    "synthetic-cli-access-token",
)


def _position(*, zero: bool = False) -> AccountPosition:
    return AccountPosition(
        stock_code="SYNTHCLI0" if zero else "SYNTHCLI1",
        product_name="Synthetic CLI Zero" if zero else "Synthetic CLI Equity",
        holding_quantity=Decimal("0" if zero else "12345.6789"),
        sellable_quantity=Decimal("0" if zero else "12000.1250"),
        purchase_amount=Decimal("0" if zero else "9876543210.1234"),
        evaluation_amount=Decimal("0" if zero else "9999999999.9999"),
        profit_loss=Decimal("0" if zero else "123456789.8765"),
    )


def _snapshot(
    *,
    empty: bool = False,
    include_zero: bool = True,
    summary_mismatch: bool = False,
) -> AccountSnapshot:
    pages = (
        ApiPageEvidence(
            page_number=1,
            received_at=STARTED_AT + timedelta(seconds=1),
            http_status=200,
            tr_cont="M" if summary_mismatch else "",
            ctx_area_fk100="NEXT-FK" if summary_mismatch else "",
            ctx_area_nk100="NEXT-NK" if summary_mismatch else "",
            rt_cd="0",
            msg_cd="SYNTHETIC_SUCCESS",
            msg1="synthetic success",
            response_body_sha256="a" * 64,
        ),
    )
    if summary_mismatch:
        pages += (
            ApiPageEvidence(
                page_number=2,
                received_at=COMPLETED_AT,
                http_status=200,
                tr_cont="",
                ctx_area_fk100="",
                ctx_area_nk100="",
                rt_cd="0",
                msg_cd="SYNTHETIC_SUCCESS",
                msg1="synthetic success",
                response_body_sha256="b" * 64,
            ),
        )
    return AccountSnapshot(
        account_number_masked="5566****-**",
        query_started_at=STARTED_AT,
        query_completed_at=COMPLETED_AT,
        summary=AccountSummary(
            deposit_total=Decimal("12345678901234567890.1234"),
            orderable_cash=None,
            securities_evaluation_amount=Decimal("9999999999.9999"),
            purchase_amount_total=Decimal("9876543210.1234"),
            evaluation_amount_total=Decimal("9999999999.9999"),
            profit_loss_total=Decimal("-123456789.8765"),
            total_assets=Decimal("12345678911234567890.1233"),
            net_assets=Decimal("12345678911234567890.1233"),
        ),
        positions=() if empty else (_position(),),
        zero_quantity_balances=(_position(zero=True),) if include_zero else (),
        evidence=SnapshotEvidence(
            pages=pages,
            summary_consistency_warnings=("synthetic mismatch",) if summary_mismatch else (),
        ),
    )


def _result(tmp_path: Path, **snapshot_options: bool) -> AccountSnapshotResult:
    return AccountSnapshotResult(
        snapshot=_snapshot(**snapshot_options),
        saved_path=tmp_path / "snapshots" / "synthetic-snapshot.json",
    )


def _capture_consoles() -> tuple[StringIO, StringIO, Console, Console]:
    stdout = StringIO()
    stderr = StringIO()
    return (
        stdout,
        stderr,
        Console(file=stdout, width=240, color_system=None, markup=False, highlight=False),
        Console(file=stderr, width=240, color_system=None, markup=False, highlight=False),
    )


def test_success_output_contains_normalized_summary_positions_and_saved_path(
    tmp_path: Path,
) -> None:
    result = _result(tmp_path)
    stdout, stderr, console, error_console = _capture_consoles()

    exit_code = cli.run_cli_snapshot(
        runner=lambda: result,
        console=console,
        error_console=error_console,
    )

    output = stdout.getvalue()
    assert exit_code == cli.ExitCode.SUCCESS
    assert stderr.getvalue() == ""
    for expected in (
        "한국투자증권 실전계좌 · READ ONLY",
        "5566****-**",
        STARTED_AT.isoformat(),
        COMPLETED_AT.isoformat(),
        "예수금 총액",
        "12,345,678,901,234,567,890.1234 원",
        "주문가능현금",
        "미제공",
        "주식평가액",
        "매입금액 합계",
        "평가금액 합계",
        "평가손익",
        "-123,456,789.8765 원",
        "총자산",
        "순자산",
        "SYNTHCLI1",
        "Synthetic CLI Equity",
        "12,345.6789",
        "12,000.1250",
        "0수량 잔고",
        "1건",
        "조회 페이지",
        "1페이지",
        str(result.saved_path),
    ):
        assert expected in output
    assert re.search(r"주문가능현금\s+0(?:\.0+)?", output) is None


def test_empty_account_is_a_normal_success_without_an_empty_table_error(tmp_path: Path) -> None:
    result = _result(tmp_path, empty=True, include_zero=False)
    stdout, stderr, console, error_console = _capture_consoles()

    exit_code = cli.run_cli_snapshot(
        runner=lambda: result,
        console=console,
        error_console=error_console,
    )

    assert exit_code == cli.ExitCode.SUCCESS
    assert "보유 종목: 없음" in stdout.getvalue()
    assert "0수량 잔고" in stdout.getvalue()
    assert "0건" in stdout.getvalue()
    assert stderr.getvalue() == ""


def test_summary_mismatch_prints_only_a_safe_korean_warning(tmp_path: Path) -> None:
    result = _result(tmp_path, summary_mismatch=True)
    stdout, stderr, console, error_console = _capture_consoles()

    exit_code = cli.run_cli_snapshot(
        runner=lambda: result,
        console=console,
        error_console=error_console,
    )

    output = stdout.getvalue()
    assert exit_code == cli.ExitCode.SUCCESS
    assert "2페이지" in output
    assert "경고: 페이지별 계좌 요약이 달라 마지막 페이지의 요약을 사용했습니다." in output
    assert "synthetic mismatch" not in output
    assert stderr.getvalue() == ""


@pytest.mark.parametrize(
    ("error", "expected_code", "expected_label"),
    (
        (ConfigError("secret configuration details"), cli.ExitCode.CONFIGURATION, "설정 오류"),
        (KisAuthError("secret authentication details"), cli.ExitCode.AUTHENTICATION, "인증 오류"),
        (KisBalanceHttpError("secret request URL"), cli.ExitCode.BALANCE_QUERY, "조회 오류"),
        (SnapshotStorageError("secret storage path"), cli.ExitCode.SNAPSHOT_STORAGE, "저장 오류"),
        (RuntimeError("secret unexpected details"), cli.ExitCode.UNEXPECTED, "예기치 않은 오류"),
        (KeyboardInterrupt(), cli.ExitCode.INTERRUPTED, "중단됨"),
    ),
)
def test_error_categories_have_distinct_codes_without_tracebacks_or_details(
    error: BaseException,
    expected_code: cli.ExitCode,
    expected_label: str,
) -> None:
    stdout, stderr, console, error_console = _capture_consoles()

    def fail() -> AccountSnapshotResult:
        raise error

    exit_code = cli.run_cli_snapshot(
        runner=fail,
        console=console,
        error_console=error_console,
    )

    error_output = stderr.getvalue()
    assert exit_code == expected_code
    assert stdout.getvalue() == ""
    assert expected_label in error_output
    assert "Traceback" not in error_output
    assert "secret" not in error_output


def test_unexpected_error_never_echoes_secrets_or_http_details() -> None:
    stdout, stderr, console, error_console = _capture_consoles()

    def fail() -> AccountSnapshotResult:
        raise RuntimeError(
            " ".join(SECRETS) + " https://openapi.koreainvestment.com:9443/path?CANO=55667788"
        )

    exit_code = cli.run_cli_snapshot(
        runner=fail,
        console=console,
        error_console=error_console,
    )

    combined = stdout.getvalue() + stderr.getvalue()
    assert exit_code == cli.ExitCode.UNEXPECTED
    for secret in (*SECRETS, "55667788", "openapi.koreainvestment.com"):
        assert secret not in combined
    assert "Traceback" not in combined


def test_account_snapshot_command_and_root_default_share_the_same_runner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _result(tmp_path)
    calls = 0

    def run() -> AccountSnapshotResult:
        nonlocal calls
        calls += 1
        return result

    monkeypatch.setattr(cli, "run_production_snapshot", run)
    runner = CliRunner()

    explicit = runner.invoke(cli.app, ["account", "snapshot"], color=False)
    direct = runner.invoke(cli.app, [], color=False)

    assert explicit.exit_code == 0
    assert direct.exit_code == 0
    assert "한국투자증권 실전계좌 · READ ONLY" in explicit.stdout
    assert "한국투자증권 실전계좌 · READ ONLY" in direct.stdout
    assert calls == 2


def test_python_module_entry_point_runs_the_same_snapshot_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = _result(tmp_path)
    monkeypatch.setattr(cli, "run_production_snapshot", lambda: result)
    monkeypatch.setattr(sys, "argv", ["phalanx", "account", "snapshot"])
    module_path = Path(cli.__file__).with_name("__main__.py")

    with pytest.raises(SystemExit) as captured:
        runpy.run_path(str(module_path), run_name="__main__")

    streams = capsys.readouterr()
    assert captured.value.code == 0
    assert "한국투자증권 실전계좌 · READ ONLY" in streams.out
    assert streams.err == ""


def test_cli_exposes_no_environment_demo_or_path_injection_options() -> None:
    runner = CliRunner()
    root_help = runner.invoke(cli.app, ["--help"], color=False)
    command_help = runner.invoke(cli.app, ["account", "snapshot", "--help"], color=False)
    combined = root_help.stdout + command_help.stdout

    assert root_help.exit_code == 0
    assert command_help.exit_code == 0
    for forbidden in ("--environment", "--paper", "--demo", "--real", "--snapshot-directory"):
        assert forbidden not in combined
