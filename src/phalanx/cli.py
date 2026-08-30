"""Korean, secret-safe CLI for read-only account and market-data workflows."""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal
from enum import IntEnum
from typing import Annotated
from zoneinfo import ZoneInfo

import typer
from rich.console import Console
from rich.table import Table

from phalanx.application import AccountSnapshotResult, run_production_snapshot
from phalanx.config import ConfigError
from phalanx.domain import AccountSnapshot, AccountSummary, AlignedReturnMatrix, DailyBar
from phalanx.kis.errors import (
    KisAuthError,
    KisBalanceAuthenticationError,
    KisBalanceClientError,
    KisBalanceParsingError,
    KisMarketDataAuthenticationError,
    KisMarketDataClientError,
    KisMarketDataParsingError,
)
from phalanx.kis.market_data_client import KisRateLimitNotification
from phalanx.market_data.application import (
    run_production_daily_market_data,
    run_production_universe_market_data,
)
from phalanx.market_data.errors import InvalidMarketDataRangeError, MarketDataError
from phalanx.market_data.service import StockDailyBars
from phalanx.market_data.validation import validate_daily_date_range
from phalanx.portfolio.application import run_production_aligned_returns
from phalanx.portfolio.errors import PortfolioAnalysisError
from phalanx.snapshots import SnapshotStorageError
from phalanx.universe.errors import UniverseError
from phalanx.universe.repository import JsonUniverseRepository
from phalanx.universe.service import UniverseService

KOREA_TIMEZONE = ZoneInfo("Asia/Seoul")
_CLI_DATE_PATTERN = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")


class ExitCode(IntEnum):
    """Stable process outcomes for all CLI workflows."""

    SUCCESS = 0
    CONFIGURATION = 10
    AUTHENTICATION = 20
    BALANCE_QUERY = 30
    SNAPSHOT_STORAGE = 40
    UNIVERSE = 50
    MARKET_DATA = 60
    PORTFOLIO_ANALYSIS = 65
    UNEXPECTED = 70
    INTERRUPTED = 130


app = typer.Typer(
    add_completion=False,
    help="한국투자증권 read-only 계좌·시세 조회와 로컬 투자 후보 관리",
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
market_data_app = typer.Typer(
    add_completion=False,
    help="KIS 국내주식 READ ONLY 일별 수정주가 조회",
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)
portfolio_app = typer.Typer(
    add_completion=False,
    help="공통 거래일 기반 READ ONLY 포트폴리오 분석",
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)
app.add_typer(account_app, name="account")
app.add_typer(universe_app, name="universe")
app.add_typer(market_data_app, name="market-data")
app.add_typer(portfolio_app, name="portfolio")


def _console(*, stderr: bool = False) -> Console:
    return Console(stderr=stderr, markup=False, highlight=False)


def _format_decimal(value: Decimal) -> str:
    return format(value, ",f")


def _format_money(value: Decimal) -> str:
    return f"{_format_decimal(value)} 원"


def _format_korean_time(value: datetime) -> str:
    return value.astimezone(KOREA_TIMEZONE).strftime("%Y-%m-%d %H:%M:%S KST")


def _parse_cli_date_range(start: str, end: str) -> tuple[date, date]:
    parsed: list[date] = []
    for option_name, value in (("--start", start), ("--end", end)):
        if _CLI_DATE_PATTERN.fullmatch(value) is None:
            raise InvalidMarketDataRangeError(
                f"{option_name}는 YYYY-MM-DD 형식의 실제 날짜여야 합니다."
            )
        try:
            parsed.append(datetime.strptime(value, "%Y-%m-%d").date())
        except ValueError:
            raise InvalidMarketDataRangeError(
                f"{option_name}는 YYYY-MM-DD 형식의 실제 날짜여야 합니다."
            ) from None
    return validate_daily_date_range(parsed[0], parsed[1])


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


def render_daily_market_data(bars: tuple[DailyBar, ...], console: Console) -> None:
    """Render a compact summary without persisting market data."""

    console.print("KIS 국내주식 일별 시세 · READ ONLY", style="bold green")
    overview = Table(show_header=False, box=None, pad_edge=False)
    overview.add_column("항목", style="bold")
    overview.add_column("값", justify="right")
    overview.add_row("조회 건수", f"{len(bars)}건")
    if bars:
        overview.add_row("최초 거래일", bars[0].trade_date.isoformat())
        overview.add_row("최종 거래일", bars[-1].trade_date.isoformat())
        overview.add_row("최초 종가", _format_decimal(bars[0].close_price))
        overview.add_row("최종 종가", _format_decimal(bars[-1].close_price))
    else:
        overview.add_row("거래일", "없음")
        overview.add_row("종가", "없음")
    console.print(overview)


def render_market_data_start(
    target: str,
    start: str,
    end: str,
    console: Console,
) -> None:
    """Render request context before any credentials or network work begins."""

    console.print("KIS 국내주식 일별 시세 조회 시작 · READ ONLY", style="bold green")
    console.print(target)
    console.print(f"시작일: {start}")
    console.print(f"종료일: {end}")


def render_rate_limit_notification(
    notification: KisRateLimitNotification,
    console: Console,
) -> None:
    """Render only the secret-free retry fields supplied by the KIS client."""

    wait_seconds = format(notification.wait_seconds, "g")
    console.print(
        f"KIS 호출 제한: {notification.stock_code} · "
        f"{wait_seconds}초 후 재시도 "
        f"({notification.attempt_number}/{notification.max_attempts})",
        style="bold yellow",
    )


def render_universe_market_data(
    results: tuple[StockDailyBars, ...],
    console: Console,
) -> None:
    """Render one row per active universe stock."""

    if not results:
        console.print("활성 투자 후보가 없습니다.")
        return

    table = Table(title="활성 유니버스 일별 시세 · READ ONLY")
    table.add_column("종목코드")
    table.add_column("종목명")
    table.add_column("조회 건수", justify="right")
    table.add_column("최초 거래일")
    table.add_column("최종 거래일")
    for result in results:
        first_date = result.bars[0].trade_date.isoformat() if result.bars else "-"
        last_date = result.bars[-1].trade_date.isoformat() if result.bars else "-"
        table.add_row(
            result.stock.stock_code,
            result.stock.stock_name,
            f"{len(result.bars)}건",
            first_date,
            last_date,
        )
    console.print(table)


def render_portfolio_returns_start(
    start: str,
    end: str,
    console: Console,
) -> None:
    """Render the analysis request before credentials or network work begins."""

    console.print("KIS 국내주식 수익률 행렬 조회 시작 · READ ONLY", style="bold green")
    console.print("조회 대상: 활성 유니버스")
    console.print(f"시작일: {start}")
    console.print(f"종료일: {end}")


def render_aligned_return_matrix(
    matrix: AlignedReturnMatrix,
    console: Console,
) -> None:
    """Render aligned-return metadata without converting its Decimal values."""

    overview = Table(title="공통 거래일 일별 단순수익률 · READ ONLY")
    overview.add_column("항목", style="bold")
    overview.add_column("값")
    overview.add_row("종목 수", f"{len(matrix.stock_codes)}개")
    overview.add_row("공통 종가 관측치 수", f"{len(matrix.dates) + 1}개")
    overview.add_row("수익률 관측치 수", f"{len(matrix.dates)}개")
    overview.add_row("최초 수익률 기준일", matrix.dates[0].isoformat())
    overview.add_row("최종 수익률 기준일", matrix.dates[-1].isoformat())
    overview.add_row("종목코드 순서", ", ".join(matrix.stock_codes))
    overview.add_row("결측치 보정", "없음 (forward fill·보간하지 않음)")
    console.print(overview)


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


def run_cli_market_data[MarketDataResult](
    runner: Callable[[], MarketDataResult],
    renderer: Callable[[MarketDataResult, Console], None],
    *,
    console: Console | None = None,
    error_console: Console | None = None,
) -> int:
    """Run one read-only market-data action with stable, secret-safe failures."""

    output = _console() if console is None else console
    errors = _console(stderr=True) if error_console is None else error_console
    try:
        result = runner()
        renderer(result, output)
        return int(ExitCode.SUCCESS)
    except ConfigError:
        errors.print("설정 오류: 외부 KIS 자격증명 파일과 0700/0600 권한을 확인해 주세요.")
        return int(ExitCode.CONFIGURATION)
    except (KisMarketDataAuthenticationError, KisAuthError):
        errors.print("인증 오류: KIS 접근토큰을 안전하게 발급하거나 재사용하지 못했습니다.")
        return int(ExitCode.AUTHENTICATION)
    except (
        MarketDataError,
        KisMarketDataClientError,
        KisMarketDataParsingError,
        UniverseError,
    ) as error:
        errors.print(f"시세 조회 오류: {error}")
        return int(ExitCode.MARKET_DATA)
    except KeyboardInterrupt:
        errors.print("중단됨: 일별 시세 조회를 안전하게 종료했습니다.")
        return int(ExitCode.INTERRUPTED)
    except Exception:
        errors.print("예기치 않은 오류로 일별 시세 조회를 완료하지 못했습니다.")
        return int(ExitCode.UNEXPECTED)


def run_cli_portfolio_returns(
    runner: Callable[[], AlignedReturnMatrix],
    *,
    console: Console | None = None,
    error_console: Console | None = None,
) -> int:
    """Run aligned-return analysis with stable, secret-safe failures."""

    output = _console() if console is None else console
    errors = _console(stderr=True) if error_console is None else error_console
    try:
        matrix = runner()
        render_aligned_return_matrix(matrix, output)
        return int(ExitCode.SUCCESS)
    except ConfigError:
        errors.print("설정 오류: 외부 KIS 자격증명 파일과 0700/0600 권한을 확인해 주세요.")
        return int(ExitCode.CONFIGURATION)
    except (KisMarketDataAuthenticationError, KisAuthError):
        errors.print("인증 오류: KIS 접근토큰을 안전하게 발급하거나 재사용하지 못했습니다.")
        return int(ExitCode.AUTHENTICATION)
    except PortfolioAnalysisError as error:
        errors.print(f"수익률 분석 오류: {error}")
        return int(ExitCode.PORTFOLIO_ANALYSIS)
    except (
        MarketDataError,
        KisMarketDataClientError,
        KisMarketDataParsingError,
        UniverseError,
    ) as error:
        errors.print(f"시세 조회 오류: {error}")
        return int(ExitCode.MARKET_DATA)
    except KeyboardInterrupt:
        errors.print("중단됨: 수익률 행렬 작업을 안전하게 종료했습니다.")
        return int(ExitCode.INTERRUPTED)
    except Exception:
        errors.print("예기치 않은 오류로 수익률 행렬 작업을 완료하지 못했습니다.")
        return int(ExitCode.UNEXPECTED)


def _exit_after_market_data[MarketDataResult](
    runner: Callable[[], MarketDataResult],
    renderer: Callable[[MarketDataResult, Console], None],
    *,
    console: Console | None = None,
) -> None:
    exit_code = run_cli_market_data(runner, renderer, console=console)
    if exit_code != ExitCode.SUCCESS:
        raise typer.Exit(exit_code)


def _exit_after_portfolio_returns(
    runner: Callable[[], AlignedReturnMatrix],
    *,
    console: Console | None = None,
) -> None:
    exit_code = run_cli_portfolio_returns(runner, console=console)
    if exit_code != ExitCode.SUCCESS:
        raise typer.Exit(exit_code)


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


@market_data_app.command("daily")
def market_data_daily(
    stock_code: Annotated[str, typer.Argument(help="공백 없는 6자리 종목코드")],
    start: Annotated[str, typer.Option("--start", help="조회 시작일 YYYY-MM-DD")],
    end: Annotated[str, typer.Option("--end", help="조회 종료일 YYYY-MM-DD")],
) -> None:
    """한 종목의 수정주가 기준 일별 OHLCV를 조회합니다."""

    output = _console()
    render_market_data_start(f"조회 종목: {stock_code}", start, end, output)
    _exit_after_market_data(
        lambda: run_production_daily_market_data(
            stock_code,
            *_parse_cli_date_range(start, end),
            rate_limit_callback=lambda notification: render_rate_limit_notification(
                notification,
                output,
            ),
        ),
        render_daily_market_data,
        console=output,
    )


@market_data_app.command("universe")
def market_data_universe(
    start: Annotated[str, typer.Option("--start", help="조회 시작일 YYYY-MM-DD")],
    end: Annotated[str, typer.Option("--end", help="조회 종료일 YYYY-MM-DD")],
) -> None:
    """활성 투자 후보의 일별 OHLCV를 순차 조회합니다."""

    output = _console()
    render_market_data_start("조회 대상: 활성 유니버스", start, end, output)
    _exit_after_market_data(
        lambda: run_production_universe_market_data(
            *_parse_cli_date_range(start, end),
            rate_limit_callback=lambda notification: render_rate_limit_notification(
                notification,
                output,
            ),
        ),
        render_universe_market_data,
        console=output,
    )


@portfolio_app.command("returns")
def portfolio_returns(
    start: Annotated[str, typer.Option("--start", help="조회 시작일 YYYY-MM-DD")],
    end: Annotated[str, typer.Option("--end", help="조회 종료일 YYYY-MM-DD")],
) -> None:
    """활성 유니버스의 공통 거래일 일별 단순수익률을 계산합니다."""

    output = _console()
    render_portfolio_returns_start(start, end, output)
    _exit_after_portfolio_returns(
        lambda: run_production_aligned_returns(
            *_parse_cli_date_range(start, end),
            rate_limit_callback=lambda notification: render_rate_limit_notification(
                notification,
                output,
            ),
        ),
        console=output,
    )


def main() -> None:
    """Console-script entry point."""

    app()


__all__ = [
    "ExitCode",
    "account_snapshot",
    "app",
    "main",
    "market_data_daily",
    "market_data_universe",
    "portfolio_returns",
    "render_aligned_return_matrix",
    "render_daily_market_data",
    "render_market_data_start",
    "render_portfolio_returns_start",
    "render_rate_limit_notification",
    "render_snapshot_summary",
    "render_universe",
    "render_universe_market_data",
    "run_cli_market_data",
    "run_cli_portfolio_returns",
    "run_cli_snapshot",
    "universe_add",
    "universe_disable",
    "universe_enable",
    "universe_list",
    "universe_remove",
]
