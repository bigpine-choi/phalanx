"""Korean, secret-safe CLI for the read-only account snapshot workflow."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from enum import IntEnum
from typing import Annotated
from zoneinfo import ZoneInfo

import typer
from rich.console import Console
from rich.table import Table

from phalanx.application import AccountSnapshotResult, run_production_snapshot
from phalanx.config import ConfigError
from phalanx.domain import AccountSnapshot, AccountSummary
from phalanx.kis.errors import (
    KisAuthError,
    KisBalanceAuthenticationError,
    KisBalanceClientError,
    KisBalanceParsingError,
)
from phalanx.snapshots import SnapshotStorageError
from phalanx.universe.errors import UniverseError
from phalanx.universe.repository import JsonUniverseRepository
from phalanx.universe.service import UniverseService

KOREA_TIMEZONE = ZoneInfo("Asia/Seoul")


class ExitCode(IntEnum):
    """Stable process outcomes for the snapshot command."""

    SUCCESS = 0
    CONFIGURATION = 10
    AUTHENTICATION = 20
    BALANCE_QUERY = 30
    SNAPSHOT_STORAGE = 40
    UNIVERSE = 50
    UNEXPECTED = 70
    INTERRUPTED = 130


app = typer.Typer(
    add_completion=False,
    help="한국투자증권 read-only 계좌 스냅샷과 로컬 투자 후보 관리",
    invoke_without_command=True,
    no_args_is_help=False,
    pretty_exceptions_enable=False,
)
account_app = typer.Typer(
    add_completion=False,
    help="실전계좌 read-only 작업",
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)
universe_app = typer.Typer(
    add_completion=False,
    help="사람이 관리하는 로컬 투자 후보 유니버스",
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)
app.add_typer(account_app, name="account")
app.add_typer(universe_app, name="universe")


def _console(*, stderr: bool = False) -> Console:
    return Console(stderr=stderr, markup=False, highlight=False)


def _format_decimal(value: Decimal) -> str:
    return format(value, ",f")


def _format_money(value: Decimal) -> str:
    return f"{_format_decimal(value)} 원"


def _format_korean_time(value: datetime) -> str:
    return value.astimezone(KOREA_TIMEZONE).strftime("%Y-%m-%d %H:%M:%S KST")


def _calculate_asset_reconciliation(summary: AccountSummary) -> tuple[Decimal, Decimal]:
    """Return presentation-only reverse-derived reconciliation amounts.

    Neither value is a direct KIS field or a measure of cash availability.
    """

    other_assets_and_settlement_adjustments = (
        summary.total_assets - summary.deposit_total - summary.securities_evaluation_amount
    )
    liabilities_and_deductions = summary.total_assets - summary.net_assets
    return other_assets_and_settlement_adjustments, liabilities_and_deductions


def render_snapshot_summary(result: AccountSnapshotResult, console: Console) -> None:
    """Render only normalized domain values after persistence has succeeded."""

    snapshot = result.snapshot
    summary = snapshot.summary
    other_assets_and_settlement_adjustments, liabilities_and_deductions = (
        _calculate_asset_reconciliation(summary)
    )
    console.print("한국투자증권 실전계좌 · READ ONLY", style="bold green")

    overview = Table(show_header=False, box=None, pad_edge=False)
    overview.add_column("항목", style="bold")
    overview.add_column("값", justify="right")
    overview.add_row("계좌번호", snapshot.account_number_masked)
    overview.add_row("조회 시작", _format_korean_time(snapshot.query_started_at))
    overview.add_row("조회 완료", _format_korean_time(snapshot.query_completed_at))
    overview.add_row("예수금 총액", _format_money(summary.deposit_total))
    overview.add_row("주문가능현금", "미제공")
    overview.add_row("주식평가액", _format_money(summary.securities_evaluation_amount))
    overview.add_row("매입금액 합계", _format_money(summary.purchase_amount_total))
    overview.add_row("평가금액 합계", _format_money(summary.evaluation_amount_total))
    overview.add_row("평가손익", _format_money(summary.profit_loss_total))
    overview.add_row("총자산", _format_money(summary.total_assets))
    overview.add_row("순자산", _format_money(summary.net_assets))
    overview.add_row(
        "기타 자산·결제조정 (역산)",
        _format_money(other_assets_and_settlement_adjustments),
    )
    overview.add_row("부채 등 차감액 (역산)", _format_money(liabilities_and_deductions))
    overview.add_row("0수량 잔고", f"{len(snapshot.zero_quantity_balances)}건")
    overview.add_row("조회 페이지", f"{snapshot.page_count}페이지")
    console.print(overview)

    _render_positions(snapshot, console)
    if snapshot.summaries_differed_across_pages:
        console.print(
            "경고: 페이지별 계좌 요약이 달라 마지막 페이지의 요약을 사용했습니다.",
            style="bold yellow",
        )
    console.print(f"저장된 스냅샷: {result.saved_path}")


def _render_positions(snapshot: AccountSnapshot, console: Console) -> None:
    if not snapshot.positions:
        console.print("보유 종목: 없음")
        return

    table = Table(title="보유 종목")
    table.add_column("종목코드")
    table.add_column("종목명")
    table.add_column("보유수량", justify="right")
    table.add_column("매도가능수량", justify="right")
    table.add_column("매입금액", justify="right")
    table.add_column("평가금액", justify="right")
    table.add_column("평가손익", justify="right")
    for position in snapshot.positions:
        table.add_row(
            position.stock_code,
            position.product_name,
            _format_decimal(position.holding_quantity),
            _format_decimal(position.sellable_quantity),
            _format_money(position.purchase_amount),
            _format_money(position.evaluation_amount),
            _format_money(position.profit_loss),
        )
    console.print(table)


def _build_universe_service() -> UniverseService:
    """Build the default local universe graph without involving KIS."""

    return UniverseService(JsonUniverseRepository())


def render_universe(service: UniverseService, console: Console) -> None:
    """Render all local candidates with an explicit activation state."""

    stocks = service.list_stocks()
    if not stocks:
        console.print("투자 후보 유니버스가 비어 있습니다.")
        return

    table = Table(title="투자 후보 유니버스")
    table.add_column("상태")
    table.add_column("종목코드")
    table.add_column("종목명")
    table.add_column("시장")
    table.add_column("메모")
    for stock in stocks:
        table.add_row(
            "활성" if stock.enabled else "비활성",
            stock.stock_code,
            stock.stock_name,
            stock.market.value,
            stock.note or "-",
            style=None if stock.enabled else "dim",
        )
    console.print(table)


def _universe_error(error: UniverseError) -> None:
    _console(stderr=True).print(f"유니버스 오류: {error}")
    raise typer.Exit(ExitCode.UNIVERSE)


def run_cli_snapshot(
    *,
    runner: Callable[[], AccountSnapshotResult] | None = None,
    console: Console | None = None,
    error_console: Console | None = None,
) -> int:
    """Run once, returning a stable code without exposing exception details."""

    selected_runner = run_production_snapshot if runner is None else runner
    output = _console() if console is None else console
    errors = _console(stderr=True) if error_console is None else error_console
    try:
        result = selected_runner()
        render_snapshot_summary(result, output)
        return int(ExitCode.SUCCESS)
    except ConfigError:
        errors.print("설정 오류: 외부 KIS 자격증명 파일과 0700/0600 권한을 확인해 주세요.")
        return int(ExitCode.CONFIGURATION)
    except (KisBalanceAuthenticationError, KisAuthError):
        errors.print("인증 오류: KIS 접근토큰을 안전하게 발급하거나 재사용하지 못했습니다.")
        return int(ExitCode.AUTHENTICATION)
    except (KisBalanceClientError, KisBalanceParsingError):
        errors.print("조회 오류: KIS 실전계좌 잔고 조회를 완료하지 못했습니다.")
        return int(ExitCode.BALANCE_QUERY)
    except SnapshotStorageError:
        errors.print("저장 오류: 완성된 계좌 스냅샷을 안전하게 저장하지 못했습니다.")
        return int(ExitCode.SNAPSHOT_STORAGE)
    except KeyboardInterrupt:
        errors.print("중단됨: 계좌 스냅샷 작업을 안전하게 종료했습니다.")
        return int(ExitCode.INTERRUPTED)
    except Exception:
        errors.print("예기치 않은 오류로 계좌 스냅샷 작업을 완료하지 못했습니다.")
        return int(ExitCode.UNEXPECTED)


def _exit_after_snapshot() -> None:
    exit_code = run_cli_snapshot()
    if exit_code != ExitCode.SUCCESS:
        raise typer.Exit(exit_code)


@app.callback()
def root(ctx: typer.Context) -> None:
    """Run a snapshot directly when no explicit subcommand is provided."""

    if ctx.invoked_subcommand is None:
        _exit_after_snapshot()


@account_app.command("snapshot")
def account_snapshot() -> None:
    """실전계좌 잔고를 조회하여 불변 JSON 스냅샷으로 저장합니다."""

    _exit_after_snapshot()


@universe_app.command("list")
def universe_list() -> None:
    """등록된 투자 후보를 활성화 상태와 함께 표시합니다."""

    try:
        render_universe(_build_universe_service(), _console())
    except UniverseError as error:
        _universe_error(error)


@universe_app.command("add")
def universe_add(
    stock_code: Annotated[str, typer.Argument(help="공백 없는 6자리 종목코드")],
    stock_name: Annotated[str, typer.Argument(help="종목명")],
    market: Annotated[
        str,
        typer.Option("--market", "-m", help="시장: KOSPI 또는 KOSDAQ"),
    ],
    note: Annotated[str | None, typer.Option("--note", "-n", help="선택적 메모")] = None,
) -> None:
    """새 투자 후보를 활성 상태로 등록합니다."""

    try:
        stock = _build_universe_service().add_stock(
            stock_code,
            stock_name,
            market,
            note=note,
        )
        _console().print(
            f"등록됨: {stock.stock_code} {stock.stock_name} ({stock.market.value}) · 활성"
        )
    except UniverseError as error:
        _universe_error(error)


@universe_app.command("enable")
def universe_enable(
    stock_code: Annotated[str, typer.Argument(help="활성화할 6자리 종목코드")],
) -> None:
    """기존 투자 후보를 활성화합니다."""

    try:
        stock = _build_universe_service().enable_stock(stock_code)
        _console().print(f"활성화됨: {stock.stock_code} {stock.stock_name}")
    except UniverseError as error:
        _universe_error(error)


@universe_app.command("disable")
def universe_disable(
    stock_code: Annotated[str, typer.Argument(help="비활성화할 6자리 종목코드")],
) -> None:
    """기존 투자 후보를 비활성화합니다."""

    try:
        stock = _build_universe_service().disable_stock(stock_code)
        _console().print(f"비활성화됨: {stock.stock_code} {stock.stock_name}")
    except UniverseError as error:
        _universe_error(error)


@universe_app.command("remove")
def universe_remove(
    stock_code: Annotated[str, typer.Argument(help="삭제할 6자리 종목코드")],
) -> None:
    """기존 투자 후보를 유니버스에서 삭제합니다."""

    try:
        stock = _build_universe_service().remove_stock(stock_code)
        _console().print(f"삭제됨: {stock.stock_code} {stock.stock_name}")
    except UniverseError as error:
        _universe_error(error)


def main() -> None:
    """Console-script entry point."""

    app()


__all__ = [
    "ExitCode",
    "account_snapshot",
    "app",
    "main",
    "render_snapshot_summary",
    "render_universe",
    "run_cli_snapshot",
    "universe_add",
    "universe_disable",
    "universe_enable",
    "universe_list",
    "universe_remove",
]
