"""Korean, secret-safe CLI for read-only account and market-data workflows."""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, localcontext
from enum import IntEnum
from pathlib import Path
from statistics import median
from typing import Annotated
from zoneinfo import ZoneInfo

import typer
from rich.console import Console
from rich.table import Table

from phalanx.account_overview import AccountOverviewError, calculate_asset_reconciliation
from phalanx.account_overview_application import (
    AccountOverviewResult,
    OverviewProgress,
    run_production_account_overview,
)
from phalanx.account_performance import (
    AccountPerformanceError,
    account_performance_decimal_context,
)
from phalanx.application import (
    AccountPerformanceResult,
    AccountSnapshotResult,
    run_account_performance,
    run_production_snapshot,
)
from phalanx.config import ConfigError
from phalanx.domain import (
    CONSTRAINED_ERC_POLICY_ORDER,
    SCENARIO_KIND_ORDER,
    VOLATILITY_OVERLAY_SCENARIO_POLICY_IDS,
    AccountSnapshot,
    AccountSummary,
    AlignedReturnMatrix,
    AllocationPolicyOutcomeStatus,
    AllocationTrialStatus,
    ConstrainedErcBoundFlag,
    ConstrainedErcOutcomeStatus,
    ConstrainedErcResearchStatus,
    CovarianceScenario,
    DailyBar,
    DownsideStressMetadata,
    IewmaMetadata,
    LedoitWolfMetadata,
    PsdDiagnostics,
    RiskModelResearchStatus,
    VolatilityOverlayOutcomeStatus,
    VolatilityOverlayResearchStatus,
    canonicalize_annual_cash_yield,
    canonicalize_target_annual_volatility,
)
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
    ValuationPriceResult,
    run_production_daily_market_data,
    run_production_universe_market_data,
    run_production_valuation_prices,
)
from phalanx.market_data.errors import (
    CurrentPriceObservationReadError,
    InvalidMarketDataRangeError,
    MarketDataError,
    ValuationPriceBundleCoherenceError,
)
from phalanx.market_data.service import StockDailyBars
from phalanx.market_data.validation import validate_daily_date_range
from phalanx.portfolio.application import (
    AllocationResearchApplicationResult,
    ConstrainedErcResearchApplicationResult,
    HistoricalReportResult,
    RiskModelResearchApplicationResult,
    VolatilityOverlayResearchApplicationResult,
    run_production_aligned_returns,
    run_production_allocation_research,
    run_production_constrained_erc_research,
    run_production_historical_report,
    run_production_risk_model_research,
    run_production_volatility_overlay_research,
)
from phalanx.portfolio.constrained_erc_trial_registry import (
    safe_constrained_erc_failure_display,
)
from phalanx.portfolio.errors import (
    AllocationTrialStorageError,
    ConstrainedErcTrialStorageError,
    HistoricalReportError,
    InvalidVolatilityOverlayDomainError,
    PortfolioAnalysisError,
    RiskModelTrialStorageError,
    VolatilityOverlayTrialStorageError,
)
from phalanx.portfolio.private_json_storage import (
    PrivateJsonAlreadyExistsError,
    PrivateJsonStorageError,
)
from phalanx.portfolio.volatility_overlay_trial_registry import (
    safe_volatility_overlay_failure_display,
)
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
    ACCOUNT_PERFORMANCE = 65
    ACCOUNT_OVERVIEW = 65
    HISTORICAL_REPORT = 66
    PORTFOLIO_STORAGE = 66
    ACCOUNT_PERFORMANCE_STORAGE = 66
    MARKET_DATA_STORAGE = 66
    ACCOUNT_OVERVIEW_STORAGE = 66
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
    help="KIS 국내주식 READ ONLY 일별 수정주가·현재가 조회",
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


def _format_observation_time(value: datetime) -> str:
    pattern = "%Y-%m-%d %H:%M:%S.%f KST" if value.microsecond else "%Y-%m-%d %H:%M:%S KST"
    return value.astimezone(KOREA_TIMEZONE).strftime(pattern)


def render_account_performance(result: AccountPerformanceResult, console: Console) -> None:
    """Display the entire account's observation-based estimate and ledger provenance."""

    performance = result.performance
    console.print("실계좌 전체 기간 성과", style="bold green")
    overview = Table(show_header=False, box=None, pad_edge=False)
    overview.add_column("항목", style="bold")
    overview.add_column("값", justify="right")
    overview.add_row("시작 관측시각", _format_observation_time(performance.start_observed_at))
    overview.add_row("종료 관측시각", _format_observation_time(performance.end_observed_at))
    with localcontext(account_performance_decimal_context()):
        for label, amount in (
            ("기초 순자산", performance.beginning_net_assets),
            ("기말 순자산", performance.ending_net_assets),
            ("총입금", performance.total_deposits),
            ("총출금", performance.total_withdrawals),
            ("순입출금", performance.net_cash_flow),
            ("기간 운용손익", performance.profit_loss),
            ("평균투하자본", performance.average_invested_capital),
        ):
            overview.add_row(label, f"{amount:,.2f} 원")
        if performance.estimated_return is None:
            return_display = "미산출: " + "; ".join(performance.return_unavailable_reasons)
        else:
            return_display = f"{performance.estimated_return * Decimal('100'):,.6f}%"
    overview.add_row("기간 추정 수익률 (Modified Dietz)", return_display)
    console.print(overview)
    console.print("사용자 제공 외부 입출금 원장을 사용했습니다.")
    console.print("조회 완료시각을 계산용 관측시각으로 사용한 추정입니다.")
    console.print("관측시각은 실제 거래소 평가시각이나 확정 종가시각을 뜻하지 않습니다.")
    if result.saved_path is not None:
        console.print("저장 경로:", result.saved_path)


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


def _parse_positive_decimal_option(value: str | Decimal) -> Decimal:
    """Parse and canonicalize a bounded target without a binary-float hop."""

    parsed = _parse_finite_decimal_option(value)
    try:
        return canonicalize_target_annual_volatility(parsed)
    except InvalidVolatilityOverlayDomainError:
        raise typer.BadParameter(
            "0보다 크고 1 이하이며 소수점 이하 최대 12자리인 Decimal 비율이어야 합니다."
        ) from None


def _parse_cash_yield_option(value: str | Decimal) -> Decimal:
    """Parse and canonicalize a bounded nonnegative annual cash yield."""

    parsed = _parse_finite_decimal_option(value)
    try:
        return canonicalize_annual_cash_yield(parsed)
    except InvalidVolatilityOverlayDomainError:
        raise typer.BadParameter(
            "0 이상 1 이하이며 소수점 이하 최대 12자리인 Decimal 비율이어야 합니다."
        ) from None


def _parse_finite_decimal_option(value: str | Decimal) -> Decimal:
    if type(value) is Decimal:
        if not value.is_finite():
            raise typer.BadParameter("유한한 Decimal 비율이어야 합니다.")
        return value
    if not isinstance(value, str) or value != value.strip() or not value:
        raise typer.BadParameter("공백 없는 유한한 Decimal 비율이어야 합니다.")
    try:
        parsed = Decimal(value)
    except InvalidOperation:
        raise typer.BadParameter("유한한 Decimal 비율이어야 합니다.") from None
    if not parsed.is_finite():
        raise typer.BadParameter("유한한 Decimal 비율이어야 합니다.")
    return parsed


def _calculate_asset_reconciliation(summary: AccountSummary) -> tuple[Decimal, Decimal]:
    """Compatibility wrapper around the shared, UI-independent calculation."""

    return calculate_asset_reconciliation(summary)


def render_account_overview(result: AccountOverviewResult, console: Console) -> None:
    overview = result.overview
    snapshot = overview.snapshot
    totals = overview.totals
    console.print("계좌·시세 통합 현황 · READ ONLY", style="bold green")
    summary = Table(show_header=False, box=None, pad_edge=False)
    summary.add_column("항목")
    summary.add_column("값", justify="right")
    for label, value in (
        ("계좌번호", snapshot.account_number_masked),
        ("계좌 조회 완료", _format_observation_time(snapshot.query_completed_at)),
        ("전체 관측 완료", _format_observation_time(overview.observation_completed_at)),
        ("증권사 순자산", _format_money(snapshot.summary.net_assets)),
        ("예수금 총액", _format_money(snapshot.summary.deposit_total)),
        ("주문가능현금", "미제공"),
        ("증권사 주식평가액 (요약)", _format_money(snapshot.summary.securities_evaluation_amount)),
        ("증권사 보유행 평가액 합계", _format_money(totals.broker_positions_evaluation_amount)),
        (
            "조회 현재가 기준 보유주식 평가액",
            _format_money(totals.observed_positions_evaluation_amount),
        ),
        ("평가기준 간 차이 (손익 아님)", _format_money(totals.observed_minus_broker_positions)),
    ):
        summary.add_row(label, value)
    console.print(summary)
    if overview.positions:
        table = Table(title="보유주식 · 조회 현재가 기준")
        for label in (
            "종목코드",
            "종목명",
            "보유수량",
            "증권사 평가액",
            "조회 현재가",
            "시세 평가액",
            "주식 내 비중",
        ):
            table.add_column(label, justify="left" if label in {"종목코드", "종목명"} else "right")
        for position in overview.positions:
            table.add_row(
                position.stock_code,
                position.product_name,
                _format_decimal(position.holding_quantity),
                _format_money(position.broker_evaluation_amount),
                _format_money(position.observed_price),
                _format_money(position.observed_evaluation_amount),
                f"{position.observed_stock_weight:.2%}",
            )
        console.print(table)
    else:
        console.print("보유주식이 없어 현재가 조회를 생략했습니다.")
    if totals.broker_summary_minus_positions:
        console.print(
            "확인 필요: 증권사 주식 요약과 보유행 합계에 차이가 있습니다:",
            _format_money(totals.broker_summary_minus_positions),
        )
    console.print(
        "비중은 조회 현재가 기준 보유주식 평가액 합계 대비 비중입니다. 현금은 포함하지 않습니다."
    )
    console.print(
        "시세 평가는 계좌 조회 당시 보유수량을 사용하며 증권사 순자산을 변경하지 않습니다."
    )
    console.print(
        "관측시각은 요청·응답 시각입니다. 실제 체결시각·확정 종가·체결 가능성을 뜻하지 않습니다."
    )
    console.print("저장 경로:", result.saved_path)


def render_overview_progress(progress: OverviewProgress, console: Console) -> None:
    if progress.stage == "balance":
        console.print("계좌 조회 중 · READ ONLY")
    elif progress.stage == "prices":
        console.print(f"보유종목 {progress.stock_count}개의 KRX 현재가 조회 중")
    else:
        console.print("완성된 통합 현황 저장 중")


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


def render_valuation_prices(result: ValuationPriceResult, console: Console) -> None:
    """Render exact prices and local observation bounds in requested order."""

    table = Table(title="KRX 현재가 묶음 · READ ONLY")
    table.add_column("종목코드")
    table.add_column("가격 (KRW)", justify="right")
    table.add_column("시장")
    table.add_column("요청 관측시각 (KST)", overflow="fold")
    table.add_column("응답 관측시각 (KST)", overflow="fold")
    for observation in result.bundle.observations:
        table.add_row(
            observation.stock_code,
            _format_decimal(observation.current_price),
            observation.market.value,
            _format_observation_time(observation.request_started_at),
            _format_observation_time(observation.received_at),
        )
    console.print(table)
    console.print(f"수집 허용시간: {result.max_acquisition_span_seconds}초")
    console.print("관측시각은 클라이언트의 요청 시작·응답 수신시각이며 실제 체결시각이 아닙니다.")
    if result.saved_path is not None:
        console.print("저장 경로:", result.saved_path)


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


def render_historical_report_start(
    start: str,
    end: str,
    output_path: Path,
    console: Console,
) -> None:
    """Announce the report request before credentials or network work begins."""

    console.print("과거 유니버스 성과 리포트 생성 시작 · KIS READ ONLY", style="bold green")
    console.print("조회 대상: 활성 유니버스")
    console.print(f"시작일: {start}")
    console.print(f"종료일: {end}")
    console.print(f"저장 대상: {output_path}")


def render_historical_report_result(
    result: HistoricalReportResult,
    console: Console,
) -> None:
    """Render only completed analysis metadata and the persisted report path."""

    analysis = result.analysis
    metrics = analysis.baseline_metrics
    overview = Table(title="과거 유니버스 성과 리포트 · READ ONLY")
    overview.add_column("항목", style="bold")
    overview.add_column("값")
    overview.add_row("분석 시작일", analysis.dates[0].isoformat())
    overview.add_row("분석 종료일", analysis.dates[-1].isoformat())
    overview.add_row("종목 수", f"{len(analysis.stock_codes)}개")
    overview.add_row("수익률 관측치 수", f"{len(analysis.dates)}개")
    overview.add_row("기준선 총수익률", format(metrics.total_return, ".2%"))
    overview.add_row("기준선 연환산수익률", format(metrics.annualized_return, ".2%"))
    overview.add_row("기준선 연환산변동성", format(metrics.annualized_volatility, ".2%"))
    overview.add_row(
        "기준선 Sharpe",
        "N/A" if metrics.sharpe_ratio is None else format(metrics.sharpe_ratio, ".4f"),
    )
    overview.add_row("저장 경로", str(result.saved_path))
    console.print(overview)
    console.print("동일가중 기준선은 실제 계좌 성과나 Phalanx 전략 성과가 아닙니다.")
    console.print("KIS READ ONLY · 주문 미전송")


def render_allocation_research_start(
    start: str,
    end: str,
    output_dir: Path,
    console: Console,
) -> None:
    """Announce allocation research before credentials or network work begins."""

    console.print("자산배분 연구 시작 · KIS READ ONLY", style="bold green")
    console.print("조회 대상: 활성 유니버스")
    console.print(f"시작일: {start}")
    console.print(f"종료일: {end}")
    console.print(f"출력 디렉터리: {output_dir}")
    console.print("현재 유니버스 조건부 allocation-only 연구")


def render_allocation_research_result(
    result: AllocationResearchApplicationResult,
    console: Console,
) -> None:
    """Render comparable policy summaries and the persisted trial path."""

    console.print("자산배분 정책 비교 · allocation-only · READ ONLY", style="bold")
    for outcome in result.trial.policy_outcomes:
        table = Table(title=outcome.policy_id)
        table.add_column("항목", style="bold")
        table.add_column("값", justify="right")
        if outcome.status is AllocationPolicyOutcomeStatus.SUCCEEDED and outcome.result is not None:
            policy_result = outcome.result
            table.add_row("상태", "성공")
            table.add_row(
                "실제 평가기간",
                f"{policy_result.dates[0].isoformat()}~{policy_result.dates[-1].isoformat()}",
            )
            table.add_row("리밸런싱", f"{len(policy_result.rebalances)}회")
            table.add_row("총수익률", format(policy_result.total_return, ".2%"))
            table.add_row("연환산수익률", format(policy_result.annualized_return, ".2%"))
            table.add_row("연환산변동성", format(policy_result.annualized_volatility, ".2%"))
            table.add_row("최대 Drawdown", format(policy_result.max_drawdown, ".2%"))
            table.add_row(
                "매수 gross turnover",
                format(policy_result.buy_gross_turnover, ".2%"),
            )
            table.add_row(
                "매도 gross turnover",
                format(policy_result.sell_gross_turnover, ".2%"),
            )
            table.add_row("누적 비용률", format(policy_result.cumulative_cost_rate, ".2%"))
        else:
            table.add_row("상태", "실패")
            table.add_row("실제 평가기간", "-")
            table.add_row("리밸런싱", "-")
            table.add_row("총수익률", "-")
            table.add_row("연환산수익률", "-")
            table.add_row("연환산변동성", "-")
            table.add_row("최대 Drawdown", "-")
            table.add_row("매수 gross turnover", "-")
            table.add_row("매도 gross turnover", "-")
            table.add_row("누적 비용률", "-")
        console.print(table)
    console.print(f"trial 상태: {result.trial.status.value}")
    console.print(f"trial JSON 저장 경로: {result.saved_path}")
    console.print("현재 유니버스 조건부 allocation-only 연구")
    console.print("KIS READ ONLY · 주문 미전송")


def render_risk_model_research_start(
    start: str,
    end: str,
    output_dir: Path,
    console: Console,
) -> None:
    """Announce risk-model research before credentials or network work begins."""

    console.print("동적 위험모형 연구 시작 · KIS READ ONLY", style="bold green")
    console.print("조회 대상: 활성 유니버스")
    console.print(f"시작일: {start}")
    console.print(f"종료일: {end}")
    console.print(f"출력 디렉터리: {output_dir}")


def render_constrained_erc_research_start(
    start: str,
    end: str,
    output_dir: Path,
    console: Console,
) -> None:
    """Announce the read-only request before credentials or network work."""

    console.print("Constrained ERC 연구 시작 · KIS READ ONLY", style="bold green")
    console.print("조회 대상: 활성 유니버스")
    console.print(f"시작일: {start}")
    console.print(f"종료일: {end}")
    console.print(f"출력 디렉터리: {output_dir}")
    console.print("current-universe conditional allocation-only")
    console.print("주문 미전송")


def render_constrained_erc_research_result(
    result: ConstrainedErcResearchApplicationResult,
    console: Console,
) -> None:
    """Render seven policy outcomes in preregistered order without a winner."""

    outcomes_by_id = {outcome.policy_id: outcome for outcome in result.trial.policy_outcomes}
    console.print("Constrained ERC 독립 scenario 및 control 비교 · READ ONLY", style="bold")
    if result.trial.common_failure is not None:
        common_code, common_reason = safe_constrained_erc_failure_display(
            result.trial.common_failure.failure
        )
        console.print(f"공통 실패 단계: {result.trial.common_failure.stage.value}")
        console.print(f"공통 실패 코드: {common_code}")
        console.print(f"공통 실패 사유: {common_reason}")
    for policy_id in CONSTRAINED_ERC_POLICY_ORDER:
        outcome = outcomes_by_id[policy_id]
        table = Table(title=policy_id)
        table.add_column("항목", style="bold")
        table.add_column("값", justify="right")
        if outcome.status is ConstrainedErcOutcomeStatus.SUCCEEDED and outcome.result is not None:
            policy_result = outcome.result
            target_weights = tuple(
                weight
                for record in policy_result.rebalances
                for weight in record.target.target_weights
            )
            drift_cap_days = sum(
                any(weight > Decimal("0.20") for weight in weights)
                for weights in policy_result.realized_weights
            )
            dispersions = tuple(
                target.diagnostics_after_reconciliation.free_asset_rc_dispersion
                for target in outcome.erc_targets
                if target.diagnostics_after_reconciliation.free_asset_rc_dispersion is not None
            )
            table.add_row("상태", "성공")
            table.add_row(
                "실제 평가기간",
                f"{policy_result.dates[0].isoformat()}~{policy_result.dates[-1].isoformat()}",
            )
            table.add_row("리밸런싱 횟수", f"{len(policy_result.rebalances)}회")
            table.add_row("총수익률", format(policy_result.total_return, ".2%"))
            table.add_row("연환산수익률", format(policy_result.annualized_return, ".2%"))
            table.add_row("연환산변동성", format(policy_result.annualized_volatility, ".2%"))
            table.add_row("최대 Drawdown", format(policy_result.max_drawdown, ".2%"))
            table.add_row("매수 gross turnover", format(policy_result.buy_gross_turnover, ".2%"))
            table.add_row("매도 gross turnover", format(policy_result.sell_gross_turnover, ".2%"))
            table.add_row("누적 비용률", format(policy_result.cumulative_cost_rate, ".2%"))
            table.add_row("최대 목표비중", format(max(target_weights), ".2%"))
            if outcome.erc_targets:
                cap_hit_count = sum(
                    ConstrainedErcBoundFlag.UPPER
                    in target.diagnostics_after_reconciliation.bound_flags
                    for target in outcome.erc_targets
                )
                table.add_row("target cap 도달 snapshot 수", f"{cap_hit_count}개")
                table.add_row(
                    "median free-asset RC dispersion",
                    "N/A" if not dispersions else format(median(dispersions), ".6g"),
                )
                table.add_row(
                    "max free-asset RC dispersion",
                    "N/A" if not dispersions else format(max(dispersions), ".6g"),
                )
                table.add_row(
                    "maximum normalized KKT residual",
                    format(
                        max(
                            target.diagnostics_after_reconciliation.normalized_max_kkt_residual
                            for target in outcome.erc_targets
                        ),
                        ".6g",
                    ),
                )
            else:
                table.add_row("target cap 도달 snapshot 수", "N/A")
                table.add_row("median free-asset RC dispersion", "N/A")
                table.add_row("max free-asset RC dispersion", "N/A")
                table.add_row("maximum normalized KKT residual", "N/A")
            table.add_row("realized drift cap 초과 일수", f"{drift_cap_days}일")
            target_cash = Decimal(1) - policy_result.rebalances[0].target.target_equity_weight
            table.add_row("목표 현금비중", format(target_cash, ".2%"))
        else:
            table.add_row("상태", "실패")
            if outcome.failure is None:
                failure_code, failure_reason = "N/A", "N/A"
            else:
                failure_code, failure_reason = safe_constrained_erc_failure_display(outcome.failure)
            table.add_row("실패 코드", failure_code)
            table.add_row("실패 사유", failure_reason)
            for label in (
                "실제 평가기간",
                "리밸런싱 횟수",
                "총수익률",
                "연환산수익률",
                "연환산변동성",
                "최대 Drawdown",
                "매수 gross turnover",
                "매도 gross turnover",
                "누적 비용률",
                "최대 목표비중",
                "target cap 도달 snapshot 수",
                "realized drift cap 초과 일수",
                "median free-asset RC dispersion",
                "max free-asset RC dispersion",
                "maximum normalized KKT residual",
                "목표 현금비중",
            ):
                table.add_row(label, "N/A")
        console.print(table)
    console.print(f"trial 상태: {result.trial.status.value}")
    console.print(f"trial JSON 저장 경로: {result.saved_path}")
    console.print("current-universe conditional allocation-only")
    console.print("KIS READ ONLY · 주문 미전송")


def render_volatility_overlay_research_start(
    start: str,
    end: str,
    output_dir: Path,
    target_annual_volatility: Decimal,
    annual_cash_yield: Decimal,
    console: Console,
) -> None:
    """Announce immutable overlay inputs before credentials or network work."""

    console.print("변동성 목표 overlay 연구 시작 · KIS READ ONLY", style="bold green")
    console.print("조회 대상: 활성 유니버스")
    console.print(f"시작일: {start}")
    console.print(f"종료일: {end}")
    console.print(f"목표 연환산변동성: {format(target_annual_volatility, '.2%')}")
    console.print(f"연 현금수익률: {format(annual_cash_yield, '.2%')}")
    console.print(f"출력 디렉터리: {output_dir}")
    console.print("네 covariance scenario 독립 overlay")
    console.print("주문 미전송")


def render_volatility_overlay_research_result(
    result: VolatilityOverlayResearchApplicationResult,
    console: Console,
) -> None:
    """Render four overlay outcomes in their preregistered scenario order."""

    trial = result.trial
    outcomes_by_id = {outcome.policy_id: outcome for outcome in trial.policy_outcomes}
    console.print("변동성 목표 및 현금 residual overlay · READ ONLY", style="bold")
    for policy_id in VOLATILITY_OVERLAY_SCENARIO_POLICY_IDS:
        outcome = outcomes_by_id[policy_id]
        table = Table(title=policy_id)
        table.add_column("항목", style="bold")
        table.add_column("값", justify="right")
        if (
            outcome.status is VolatilityOverlayOutcomeStatus.SUCCEEDED
            and outcome.result is not None
        ):
            policy_result = outcome.result
            latest_target = outcome.overlay_targets[-1] if outcome.overlay_targets else None
            table.add_row("상태", "성공")
            table.add_row(
                "실제 평가기간",
                f"{policy_result.dates[0].isoformat()}~{policy_result.dates[-1].isoformat()}",
            )
            table.add_row("리밸런싱 횟수", f"{len(policy_result.rebalances)}회")
            table.add_row("총수익률", format(policy_result.total_return, ".2%"))
            table.add_row("연환산수익률", format(policy_result.annualized_return, ".2%"))
            table.add_row("연환산변동성", format(policy_result.annualized_volatility, ".2%"))
            table.add_row("최대 Drawdown", format(policy_result.max_drawdown, ".2%"))
            table.add_row("매수 gross turnover", format(policy_result.buy_gross_turnover, ".2%"))
            table.add_row("매도 gross turnover", format(policy_result.sell_gross_turnover, ".2%"))
            table.add_row("누적 비용률", format(policy_result.cumulative_cost_rate, ".2%"))
            if latest_target is None:
                table.add_row("마지막 forecast 연환산변동성", "N/A")
                table.add_row("마지막 risky scalar", "N/A")
                table.add_row("마지막 목표 주식비중", "N/A")
                table.add_row("마지막 현금 residual", "N/A")
            else:
                table.add_row(
                    "마지막 forecast 연환산변동성",
                    format(latest_target.forecast_annual_volatility, ".2%"),
                )
                table.add_row("마지막 risky scalar", format(latest_target.scalar, ".4f"))
                table.add_row(
                    "마지막 목표 주식비중",
                    format(latest_target.target_equity_weight, ".2%"),
                )
                table.add_row(
                    "마지막 현금 residual",
                    format(latest_target.cash_residual, ".2%"),
                )
        else:
            table.add_row("상태", "실패")
            if outcome.failure is None:
                failure_code, failure_reason = "N/A", "N/A"
            else:
                failure_code, failure_reason = safe_volatility_overlay_failure_display(
                    outcome.failure
                )
            table.add_row("실패 코드", failure_code)
            table.add_row(
                "실패 사유",
                failure_reason,
            )
            console.print(failure_reason)
            for label in (
                "실제 평가기간",
                "리밸런싱 횟수",
                "총수익률",
                "연환산수익률",
                "연환산변동성",
                "최대 Drawdown",
                "매수 gross turnover",
                "매도 gross turnover",
                "누적 비용률",
                "마지막 forecast 연환산변동성",
                "마지막 risky scalar",
                "마지막 목표 주식비중",
                "마지막 현금 residual",
            ):
                table.add_row(label, "N/A")
        console.print(table)
    console.print(
        f"입력 목표 연환산변동성: {format(trial.overlay_config.target_annual_volatility, '.2%')}"
    )
    console.print(f"연 현금수익률: {format(trial.overlay_config.annual_cash_yield, '.2%')}")
    console.print(f"trial 상태: {trial.status.value}")
    console.print(f"trial JSON 저장 경로: {result.saved_path}")
    console.print("current-universe conditional allocation-only")
    console.print("KIS READ ONLY · 주문 미전송")


def render_risk_model_research_result(
    result: RiskModelResearchApplicationResult,
    console: Console,
) -> None:
    """Render completed scenario diagnostics and the persisted trial path."""

    trial = result.trial
    if trial.status is RiskModelResearchStatus.SUCCEEDED:
        research = trial.result
        if research is None or not research.snapshots:
            raise RuntimeError("successful risk-model trial has no snapshots")
        console.print("동적 위험모형 독립 scenario · READ ONLY", style="bold")
        for kind in SCENARIO_KIND_ORDER:
            scenarios = tuple(snapshot.get_scenario(kind) for snapshot in research.snapshots)
            _render_risk_model_scenario(
                scenarios,
                research.snapshots[0].as_of_date,
                research.snapshots[-1].as_of_date,
                console,
            )

    console.print(f"trial 상태: {trial.status.value}")
    console.print(f"trial JSON 저장 경로: {result.saved_path}")
    console.print("현재 유니버스 조건부 위험모형 연구")
    console.print("KIS READ ONLY · 주문 미전송")


def _render_risk_model_scenario(
    scenarios: tuple[CovarianceScenario, ...],
    first_as_of: date,
    last_as_of: date,
    console: Console,
) -> None:
    last = scenarios[-1]
    volatilities = last.annualized_volatilities
    diagnostics_by_snapshot = tuple(_risk_scenario_diagnostics(scenario) for scenario in scenarios)
    repair_count = sum(
        any(diagnostics.repaired for diagnostics in snapshot_diagnostics)
        for snapshot_diagnostics in diagnostics_by_snapshot
    )
    maximum_relative_repair = max(
        diagnostics.relative_repair_norm
        for snapshot_diagnostics in diagnostics_by_snapshot
        for diagnostics in snapshot_diagnostics
    )

    table = Table(title=last.kind.value)
    table.add_column("항목", style="bold")
    table.add_column("값", justify="right")
    table.add_row("snapshot 수", f"{len(scenarios)}개")
    table.add_row("최초 as-of", first_as_of.isoformat())
    table.add_row("최종 as-of", last_as_of.isoformat())
    table.add_row("estimator 또는 반감기", _risk_scenario_estimator(last))
    table.add_row(
        "마지막 연환산 변동성 min / median / max",
        " / ".join(
            format(value, ".2%")
            for value in (min(volatilities), median(volatilities), max(volatilities))
        ),
    )
    table.add_row(
        "마지막 평균 비대각 상관계수",
        _format_average_off_diagonal_correlation(last),
    )
    table.add_row(
        "마지막 최소 고윳값",
        format(last.psd_diagnostics.minimum_eigenvalue_after, ".6g"),
    )
    table.add_row(
        "마지막 condition number",
        "N/A"
        if last.psd_diagnostics.condition_number is None
        else format(last.psd_diagnostics.condition_number, ".6g"),
    )
    table.add_row("PSD 보정 snapshot 수", f"{repair_count}개")
    table.add_row("최대 상대 PSD 보정", format(maximum_relative_repair, ".6g"))
    table.add_row("scenario metadata", _risk_scenario_metadata(last))
    console.print(table)


def _risk_scenario_diagnostics(
    scenario: CovarianceScenario,
) -> tuple[PsdDiagnostics, ...]:
    diagnostics: tuple[PsdDiagnostics, ...] = (scenario.psd_diagnostics,)
    if isinstance(scenario.metadata, IewmaMetadata):
        diagnostics = (*diagnostics, scenario.metadata.correlation_psd_diagnostics)
    return diagnostics


def _risk_scenario_estimator(scenario: CovarianceScenario) -> str:
    metadata = scenario.metadata
    if isinstance(metadata, IewmaMetadata):
        return (
            f"변동성 HL {metadata.volatility_half_life} · "
            f"상관관계 HL {metadata.correlation_half_life}"
        )
    return metadata.estimator


def _risk_scenario_metadata(scenario: CovarianceScenario) -> str:
    metadata = scenario.metadata
    if isinstance(metadata, LedoitWolfMetadata):
        return f"shrinkage {metadata.shrinkage:.6f}"
    if isinstance(metadata, DownsideStressMetadata):
        return f"하방 선택 {metadata.selected_count}개 · shrinkage {metadata.shrinkage:.6f}"
    return (
        f"변동성 HL {metadata.volatility_half_life} · "
        f"상관관계 HL {metadata.correlation_half_life} · "
        f"변동성 ESS {metadata.volatility_effective_sample_size:.2f} · "
        f"상관관계 ESS {metadata.correlation_effective_sample_size:.2f}"
    )


def _format_average_off_diagonal_correlation(
    scenario: CovarianceScenario,
) -> str:
    values = tuple(
        value
        for row_index, row in enumerate(scenario.correlation_matrix)
        for column_index, value in enumerate(row)
        if row_index != column_index
    )
    if not values:
        return "N/A"
    return format(sum(values) / len(values), ".6f")


def _universe_error(error: UniverseError) -> None:
    _console(stderr=True).print(f"유니버스 오류: {error}")
    raise typer.Exit(ExitCode.UNIVERSE)


def run_cli_account_overview(
    runner: Callable[[], AccountOverviewResult],
    *,
    console: Console | None = None,
    error_console: Console | None = None,
) -> int:
    output = _console() if console is None else console
    errors = _console(stderr=True) if error_console is None else error_console
    try:
        result = runner()
        render_account_overview(result, output)
        return int(ExitCode.SUCCESS)
    except ConfigError:
        errors.print("설정 오류: 계좌 연결정보와 자격증명 파일의 접근 권한을 확인해 주세요.")
        return int(ExitCode.CONFIGURATION)
    except (KisAuthError, KisBalanceAuthenticationError, KisMarketDataAuthenticationError):
        errors.print("인증 오류: 계좌 연결정보를 확인한 뒤 다시 조회해 주세요.")
        return int(ExitCode.AUTHENTICATION)
    except (KisBalanceClientError, KisBalanceParsingError):
        errors.print("계좌 조회 오류: 통합 현황을 만들지 못했습니다. 잠시 후 다시 조회해 주세요.")
        return int(ExitCode.BALANCE_QUERY)
    except (MarketDataError, KisMarketDataClientError, KisMarketDataParsingError):
        errors.print(
            "시세 조회 오류: 모든 보유종목의 현재가를 확인하지 못했습니다. 다시 조회해 주세요."
        )
        return int(ExitCode.MARKET_DATA)
    except AccountOverviewError as error:
        errors.print("통합 현황 오류:", str(error))
        return int(ExitCode.ACCOUNT_OVERVIEW)
    except PrivateJsonStorageError:
        errors.print(
            "저장 오류: 통합 현황을 보관하지 못했습니다. 저장 공간과 접근 권한을 확인해 주세요."
        )
        return int(ExitCode.ACCOUNT_OVERVIEW_STORAGE)
    except KeyboardInterrupt:
        errors.print("중단됨: 계좌·시세 통합 조회를 종료했습니다.")
        return int(ExitCode.INTERRUPTED)
    except Exception:
        errors.print("예기치 않은 오류로 통합 현황을 완료하지 못했습니다.")
        return int(ExitCode.UNEXPECTED)


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


def run_cli_account_performance(
    runner: Callable[[], AccountPerformanceResult],
    *,
    console: Console | None = None,
    error_console: Console | None = None,
) -> int:
    """Run offline account performance with stable, secret-safe failures."""

    output = _console() if console is None else console
    errors = _console(stderr=True) if error_console is None else error_console
    try:
        result = runner()
        render_account_performance(result, output)
        return int(ExitCode.SUCCESS)
    except AccountPerformanceError as error:
        errors.print(f"실계좌 기간 성과 입력·계산 오류: {error}")
        return int(ExitCode.ACCOUNT_PERFORMANCE)
    except PrivateJsonAlreadyExistsError:
        errors.print("저장 오류: 결과 JSON 파일이 이미 존재합니다. 다른 출력 경로를 지정해 주세요.")
        return int(ExitCode.ACCOUNT_PERFORMANCE_STORAGE)
    except PrivateJsonStorageError:
        errors.print("저장 오류: 실계좌 기간 성과 JSON을 안전하게 저장하지 못했습니다.")
        return int(ExitCode.ACCOUNT_PERFORMANCE_STORAGE)
    except KeyboardInterrupt:
        errors.print("중단됨: 실계좌 기간 성과 계산을 안전하게 종료했습니다.")
        return int(ExitCode.INTERRUPTED)
    except Exception:
        errors.print("예기치 않은 오류로 실계좌 기간 성과 계산을 완료하지 못했습니다.")
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


def run_cli_valuation_prices(
    runner: Callable[[], ValuationPriceResult],
    *,
    console: Console | None = None,
    error_console: Console | None = None,
) -> int:
    """Report complete current-price reads and write-once storage with safe failures."""

    output = _console() if console is None else console
    errors = _console(stderr=True) if error_console is None else error_console
    try:
        result = runner()
        render_valuation_prices(result, output)
        return int(ExitCode.SUCCESS)
    except ConfigError:
        errors.print("설정 오류: 외부 KIS 자격증명 파일과 0700/0600 권한을 확인해 주세요.")
        return int(ExitCode.CONFIGURATION)
    except (KisMarketDataAuthenticationError, KisAuthError):
        errors.print("인증 오류: KIS 접근토큰을 안전하게 발급하거나 재사용하지 못했습니다.")
        return int(ExitCode.AUTHENTICATION)
    except CurrentPriceObservationReadError as error:
        errors.print(
            f"현재가 조회 오류: {error.stock_code} 조회에 실패하여 묶음을 생성하지 못했습니다."
        )
        return int(ExitCode.MARKET_DATA)
    except ValuationPriceBundleCoherenceError:
        errors.print(
            "현재가 조회 오류: 조회 결과의 일관성 또는 수집 허용시간을 만족하지 못했습니다."
        )
        return int(ExitCode.MARKET_DATA)
    except (MarketDataError, KisMarketDataClientError, KisMarketDataParsingError) as error:
        errors.print(f"현재가 조회 오류: {error}")
        return int(ExitCode.MARKET_DATA)
    except PrivateJsonAlreadyExistsError:
        errors.print("저장 오류: 결과 JSON 파일이 이미 존재합니다. 다른 출력 경로를 지정해 주세요.")
        return int(ExitCode.MARKET_DATA_STORAGE)
    except PrivateJsonStorageError:
        errors.print("저장 오류: 현재가 묶음 JSON을 안전하게 저장하지 못했습니다.")
        return int(ExitCode.MARKET_DATA_STORAGE)
    except KeyboardInterrupt:
        errors.print("중단됨: 현재가 묶음 조회를 안전하게 종료했습니다.")
        return int(ExitCode.INTERRUPTED)
    except Exception:
        errors.print("예기치 않은 오류로 현재가 묶음 조회를 완료하지 못했습니다.")
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


def run_cli_historical_report(
    runner: Callable[[], HistoricalReportResult],
    *,
    console: Console | None = None,
    error_console: Console | None = None,
) -> int:
    """Run one historical HTML report with stable, secret-safe failures."""

    output = _console() if console is None else console
    errors = _console(stderr=True) if error_console is None else error_console
    try:
        result = runner()
        render_historical_report_result(result, output)
        return int(ExitCode.SUCCESS)
    except ConfigError:
        errors.print("설정 오류: 외부 KIS 자격증명 파일과 0700/0600 권한을 확인해 주세요.")
        return int(ExitCode.CONFIGURATION)
    except (KisMarketDataAuthenticationError, KisAuthError):
        errors.print("인증 오류: KIS 접근토큰을 안전하게 발급하거나 재사용하지 못했습니다.")
        return int(ExitCode.AUTHENTICATION)
    except PortfolioAnalysisError as error:
        errors.print(f"성과 분석 오류: {error}")
        return int(ExitCode.PORTFOLIO_ANALYSIS)
    except HistoricalReportError as error:
        errors.print(f"리포트 생성·저장 오류: {error}")
        return int(ExitCode.HISTORICAL_REPORT)
    except (
        MarketDataError,
        KisMarketDataClientError,
        KisMarketDataParsingError,
        UniverseError,
    ) as error:
        errors.print(f"시세 조회 오류: {error}")
        return int(ExitCode.MARKET_DATA)
    except KeyboardInterrupt:
        errors.print("중단됨: 과거 유니버스 리포트 작업을 안전하게 종료했습니다.")
        return int(ExitCode.INTERRUPTED)
    except Exception:
        errors.print("예기치 않은 오류로 과거 유니버스 리포트를 완료하지 못했습니다.")
        return int(ExitCode.UNEXPECTED)


def run_cli_allocation_research(
    runner: Callable[[], AllocationResearchApplicationResult],
    *,
    console: Console | None = None,
    error_console: Console | None = None,
) -> int:
    """Run one persisted allocation trial with stable, secret-safe outcomes."""

    output = _console() if console is None else console
    errors = _console(stderr=True) if error_console is None else error_console
    try:
        result = runner()
        render_allocation_research_result(result, output)
        if result.trial.status is not AllocationTrialStatus.SUCCEEDED:
            errors.print("자산배분 연구 오류: 한 개 이상의 정책 계산이 실패했습니다.")
            return int(ExitCode.PORTFOLIO_ANALYSIS)
        return int(ExitCode.SUCCESS)
    except ConfigError:
        errors.print("설정 오류: 외부 KIS 자격증명 파일과 0700/0600 권한을 확인해 주세요.")
        return int(ExitCode.CONFIGURATION)
    except (KisMarketDataAuthenticationError, KisAuthError):
        errors.print("인증 오류: KIS 접근토큰을 안전하게 발급하거나 재사용하지 못했습니다.")
        return int(ExitCode.AUTHENTICATION)
    except PortfolioAnalysisError as error:
        errors.print(f"자산배분 연구 오류: {error}")
        return int(ExitCode.PORTFOLIO_ANALYSIS)
    except AllocationTrialStorageError:
        errors.print("연구 trial 저장 오류: JSON을 안전하게 저장하지 못했습니다.")
        return int(ExitCode.PORTFOLIO_STORAGE)
    except (
        MarketDataError,
        KisMarketDataClientError,
        KisMarketDataParsingError,
        UniverseError,
    ) as error:
        errors.print(f"시세 조회 오류: {error}")
        return int(ExitCode.MARKET_DATA)
    except KeyboardInterrupt:
        errors.print("중단됨: 자산배분 연구를 안전하게 종료했습니다.")
        return int(ExitCode.INTERRUPTED)
    except Exception:
        errors.print("예기치 않은 오류로 자산배분 연구를 완료하지 못했습니다.")
        return int(ExitCode.UNEXPECTED)


def run_cli_risk_model_research(
    runner: Callable[[], RiskModelResearchApplicationResult],
    *,
    console: Console | None = None,
    error_console: Console | None = None,
) -> int:
    """Run one persisted dynamic-risk-model trial with secret-safe outcomes."""

    output = _console() if console is None else console
    errors = _console(stderr=True) if error_console is None else error_console
    try:
        result = runner()
        render_risk_model_research_result(result, output)
        if result.trial.status is not RiskModelResearchStatus.SUCCEEDED:
            errors.print("동적 위험모형 연구 오류: 한 개 이상의 snapshot 계산이 실패했습니다.")
            return int(ExitCode.PORTFOLIO_ANALYSIS)
        return int(ExitCode.SUCCESS)
    except ConfigError:
        errors.print("설정 오류: 외부 KIS 자격증명 파일과 0700/0600 권한을 확인해 주세요.")
        return int(ExitCode.CONFIGURATION)
    except (KisMarketDataAuthenticationError, KisAuthError):
        errors.print("인증 오류: KIS 접근토큰을 안전하게 발급하거나 재사용하지 못했습니다.")
        return int(ExitCode.AUTHENTICATION)
    except PortfolioAnalysisError:
        errors.print("동적 위험모형 연구 오류: 분석·수치 품질 검사를 완료하지 못했습니다.")
        return int(ExitCode.PORTFOLIO_ANALYSIS)
    except RiskModelTrialStorageError:
        errors.print("위험모형 trial 저장 오류: JSON을 안전하게 저장하지 못했습니다.")
        return int(ExitCode.PORTFOLIO_STORAGE)
    except (
        MarketDataError,
        KisMarketDataClientError,
        KisMarketDataParsingError,
        UniverseError,
    ) as error:
        errors.print(f"시세 조회 오류: {error}")
        return int(ExitCode.MARKET_DATA)
    except KeyboardInterrupt:
        errors.print("중단됨: 동적 위험모형 연구를 안전하게 종료했습니다.")
        return int(ExitCode.INTERRUPTED)
    except Exception:
        errors.print("예기치 않은 오류로 동적 위험모형 연구를 완료하지 못했습니다.")
        return int(ExitCode.UNEXPECTED)


def run_cli_constrained_erc_research(
    runner: Callable[[], ConstrainedErcResearchApplicationResult],
    *,
    console: Console | None = None,
    error_console: Console | None = None,
) -> int:
    """Run one persisted constrained-ERC trial with secret-safe outcomes."""

    output = _console() if console is None else console
    errors = _console(stderr=True) if error_console is None else error_console
    try:
        result = runner()
        render_constrained_erc_research_result(result, output)
        if result.trial.status is not ConstrainedErcResearchStatus.SUCCEEDED:
            errors.print("Constrained ERC 연구 오류: 한 개 이상의 정책 계산이 실패했습니다.")
            return int(ExitCode.PORTFOLIO_ANALYSIS)
        return int(ExitCode.SUCCESS)
    except ConfigError:
        errors.print("설정 오류: 외부 KIS 자격증명 파일과 0700/0600 권한을 확인해 주세요.")
        return int(ExitCode.CONFIGURATION)
    except (KisMarketDataAuthenticationError, KisAuthError):
        errors.print("인증 오류: KIS 접근토큰을 안전하게 발급하거나 재사용하지 못했습니다.")
        return int(ExitCode.AUTHENTICATION)
    except PortfolioAnalysisError:
        errors.print("Constrained ERC 연구 오류: 분석·수치 품질 검사를 완료하지 못했습니다.")
        return int(ExitCode.PORTFOLIO_ANALYSIS)
    except ConstrainedErcTrialStorageError:
        errors.print("Constrained ERC trial 저장 오류: JSON을 안전하게 저장하지 못했습니다.")
        return int(ExitCode.PORTFOLIO_STORAGE)
    except (
        MarketDataError,
        KisMarketDataClientError,
        KisMarketDataParsingError,
        UniverseError,
    ) as error:
        errors.print(f"시세 조회 오류: {error}")
        return int(ExitCode.MARKET_DATA)
    except KeyboardInterrupt:
        errors.print("중단됨: Constrained ERC 연구를 안전하게 종료했습니다.")
        return int(ExitCode.INTERRUPTED)
    except Exception:
        errors.print("예기치 않은 오류로 Constrained ERC 연구를 완료하지 못했습니다.")
        return int(ExitCode.UNEXPECTED)


def run_cli_volatility_overlay_research(
    runner: Callable[[], VolatilityOverlayResearchApplicationResult],
    *,
    console: Console | None = None,
    error_console: Console | None = None,
) -> int:
    """Run one persisted volatility-overlay trial with secret-safe outcomes."""

    output = _console() if console is None else console
    errors = _console(stderr=True) if error_console is None else error_console
    try:
        result = runner()
        render_volatility_overlay_research_result(result, output)
        if result.trial.status is not VolatilityOverlayResearchStatus.SUCCEEDED:
            errors.print(
                "변동성 목표 overlay 연구 오류: 한 개 이상의 scenario 계산이 실패했습니다."
            )
            return int(ExitCode.PORTFOLIO_ANALYSIS)
        return int(ExitCode.SUCCESS)
    except ConfigError:
        errors.print("설정 오류: 외부 KIS 자격증명 파일과 0700/0600 권한을 확인해 주세요.")
        return int(ExitCode.CONFIGURATION)
    except (KisMarketDataAuthenticationError, KisAuthError):
        errors.print("인증 오류: KIS 접근토큰을 안전하게 발급하거나 재사용하지 못했습니다.")
        return int(ExitCode.AUTHENTICATION)
    except PortfolioAnalysisError:
        errors.print("변동성 목표 overlay 연구 오류: 분석·수치 품질 검사를 완료하지 못했습니다.")
        return int(ExitCode.PORTFOLIO_ANALYSIS)
    except VolatilityOverlayTrialStorageError:
        errors.print("변동성 목표 overlay trial 저장 오류: JSON을 안전하게 저장하지 못했습니다.")
        return int(ExitCode.PORTFOLIO_STORAGE)
    except (
        MarketDataError,
        KisMarketDataClientError,
        KisMarketDataParsingError,
        UniverseError,
    ) as error:
        errors.print(f"시세 조회 오류: {error}")
        return int(ExitCode.MARKET_DATA)
    except KeyboardInterrupt:
        errors.print("중단됨: 변동성 목표 overlay 연구를 안전하게 종료했습니다.")
        return int(ExitCode.INTERRUPTED)
    except Exception:
        errors.print("예기치 않은 오류로 변동성 목표 overlay 연구를 완료하지 못했습니다.")
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


def _exit_after_historical_report(
    runner: Callable[[], HistoricalReportResult],
    *,
    console: Console | None = None,
) -> None:
    exit_code = run_cli_historical_report(runner, console=console)
    if exit_code != ExitCode.SUCCESS:
        raise typer.Exit(exit_code)


def _exit_after_allocation_research(
    runner: Callable[[], AllocationResearchApplicationResult],
    *,
    console: Console | None = None,
) -> None:
    exit_code = run_cli_allocation_research(runner, console=console)
    if exit_code != ExitCode.SUCCESS:
        raise typer.Exit(exit_code)


def _exit_after_risk_model_research(
    runner: Callable[[], RiskModelResearchApplicationResult],
    *,
    console: Console | None = None,
) -> None:
    exit_code = run_cli_risk_model_research(runner, console=console)
    if exit_code != ExitCode.SUCCESS:
        raise typer.Exit(exit_code)


def _exit_after_constrained_erc_research(
    runner: Callable[[], ConstrainedErcResearchApplicationResult],
    *,
    console: Console | None = None,
) -> None:
    exit_code = run_cli_constrained_erc_research(runner, console=console)
    if exit_code != ExitCode.SUCCESS:
        raise typer.Exit(exit_code)


def _exit_after_volatility_overlay_research(
    runner: Callable[[], VolatilityOverlayResearchApplicationResult],
    *,
    console: Console | None = None,
) -> None:
    exit_code = run_cli_volatility_overlay_research(runner, console=console)
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


@account_app.command("overview")
def account_overview(
    max_observation_span_seconds: Annotated[
        int,
        typer.Option(
            "--max-observation-span-seconds", min=1, help="계좌·시세 전체 관측 허용시간 (초)"
        ),
    ] = 60,
) -> None:
    """계좌와 보유종목 현재가를 함께 조회하고 통합 현황을 자동 저장합니다."""

    output = _console()
    exit_code = run_cli_account_overview(
        lambda: run_production_account_overview(
            max_observation_span_seconds=max_observation_span_seconds,
            progress_callback=lambda progress: render_overview_progress(progress, output),
            rate_limit_callback=lambda notification: render_rate_limit_notification(
                notification, output
            ),
        ),
        console=output,
    )
    if exit_code != ExitCode.SUCCESS:
        raise typer.Exit(exit_code)


@account_app.command("performance")
def account_performance(
    start_snapshot: Annotated[
        Path,
        typer.Option("--start-snapshot", help="시작 AccountSnapshot JSON 파일"),
    ],
    end_snapshot: Annotated[
        Path,
        typer.Option("--end-snapshot", help="종료 AccountSnapshot JSON 파일"),
    ],
    cash_flows: Annotated[
        Path,
        typer.Option("--cash-flows", help="기간과 사용자 확인 선언을 포함한 외부 입출금 JSON"),
    ],
    output: Annotated[
        Path | None,
        typer.Option("--output", help="결과 JSON 경로 · 덮어쓰기 금지"),
    ] = None,
) -> None:
    """저장된 스냅샷 두 개와 원장으로 실계좌 전체 기간 성과를 오프라인 계산합니다."""

    exit_code = run_cli_account_performance(
        lambda: run_account_performance(
            start_snapshot,
            end_snapshot,
            cash_flows,
            output_path=output,
        )
    )
    if exit_code != ExitCode.SUCCESS:
        raise typer.Exit(exit_code)


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


@market_data_app.command("valuation-prices")
def market_data_valuation_prices(
    stock_codes: Annotated[
        list[str], typer.Option("--stock-code", help="조회할 6자리 종목코드 · 반복 지정, 순서 보존")
    ],
    max_acquisition_span_seconds: Annotated[
        int,
        typer.Option("--max-acquisition-span-seconds", min=1, help="수집 허용시간 (양의 정수 초)"),
    ] = 60,
    output_path: Annotated[
        Path | None, typer.Option("--output", help="새 결과 JSON 경로 · 덮어쓰기 금지")
    ] = None,
) -> None:
    """지정한 종목의 KRX 현재가 묶음을 조회하고 선택적으로 저장합니다."""

    output = _console()
    output.print("KIS 현재가 묶음 조회 시작 · READ ONLY", style="bold green")
    exit_code = run_cli_valuation_prices(
        lambda: run_production_valuation_prices(
            tuple(stock_codes),
            max_acquisition_span_seconds=max_acquisition_span_seconds,
            output_path=output_path,
            rate_limit_callback=lambda notification: render_rate_limit_notification(
                notification, output
            ),
        ),
        console=output,
    )
    if exit_code != ExitCode.SUCCESS:
        raise typer.Exit(exit_code)


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


@portfolio_app.command("historical-report")
def portfolio_historical_report(
    start: Annotated[str, typer.Option("--start", help="조회 시작일 YYYY-MM-DD")],
    end: Annotated[str, typer.Option("--end", help="조회 종료일 YYYY-MM-DD")],
    output_path: Annotated[
        Path,
        typer.Option("--output", help="새로 생성할 self-contained HTML 파일 경로"),
    ],
) -> None:
    """활성 유니버스의 동일가중 매수후보유 HTML 리포트를 생성합니다."""

    output = _console()
    render_historical_report_start(start, end, output_path, output)
    _exit_after_historical_report(
        lambda: run_production_historical_report(
            *_parse_cli_date_range(start, end),
            output_path,
            rate_limit_callback=lambda notification: render_rate_limit_notification(
                notification,
                output,
            ),
        ),
        console=output,
    )


@portfolio_app.command("allocation-research")
def portfolio_allocation_research(
    start: Annotated[str, typer.Option("--start", help="조회 시작일 YYYY-MM-DD")],
    end: Annotated[str, typer.Option("--end", help="조회 종료일 YYYY-MM-DD")],
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help="고유 allocation trial JSON 출력 디렉터리"),
    ],
) -> None:
    """현재 활성 유니버스의 조건부 allocation-only 연구를 실행합니다."""

    output = _console()
    render_allocation_research_start(start, end, output_dir, output)
    _exit_after_allocation_research(
        lambda: run_production_allocation_research(
            *_parse_cli_date_range(start, end),
            output_dir,
            rate_limit_callback=lambda notification: render_rate_limit_notification(
                notification,
                output,
            ),
        ),
        console=output,
    )


@portfolio_app.command("risk-model-research")
def portfolio_risk_model_research(
    start: Annotated[str, typer.Option("--start", help="조회 시작일 YYYY-MM-DD")],
    end: Annotated[str, typer.Option("--end", help="조회 종료일 YYYY-MM-DD")],
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help="고유 위험모형 trial JSON 출력 디렉터리"),
    ],
) -> None:
    """활성 유니버스의 조건부 동적 위험모형 연구를 실행합니다."""

    output = _console()
    render_risk_model_research_start(start, end, output_dir, output)
    _exit_after_risk_model_research(
        lambda: run_production_risk_model_research(
            *_parse_cli_date_range(start, end),
            output_dir,
            rate_limit_callback=lambda notification: render_rate_limit_notification(
                notification,
                output,
            ),
        ),
        console=output,
    )


@portfolio_app.command("constrained-erc-research")
def portfolio_constrained_erc_research(
    start: Annotated[str, typer.Option("--start", help="조회 시작일 YYYY-MM-DD")],
    end: Annotated[str, typer.Option("--end", help="조회 종료일 YYYY-MM-DD")],
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help="고유 Constrained ERC trial JSON 출력 디렉터리"),
    ],
) -> None:
    """네 covariance ERC와 세 control을 동일 조건에서 비교합니다."""

    output = _console()
    render_constrained_erc_research_start(start, end, output_dir, output)
    _exit_after_constrained_erc_research(
        lambda: run_production_constrained_erc_research(
            *_parse_cli_date_range(start, end),
            output_dir,
            rate_limit_callback=lambda notification: render_rate_limit_notification(
                notification,
                output,
            ),
        ),
        console=output,
    )


@portfolio_app.command("volatility-overlay-research")
def portfolio_volatility_overlay_research(
    start: Annotated[str, typer.Option("--start", help="조회 시작일 YYYY-MM-DD")],
    end: Annotated[str, typer.Option("--end", help="조회 종료일 YYYY-MM-DD")],
    target_annual_volatility: Annotated[
        Decimal,
        typer.Option(
            "--target-annual-volatility",
            help="목표 연환산변동성 Decimal 비율",
            parser=_parse_positive_decimal_option,
            metavar="DECIMAL",
        ),
    ],
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help="고유 volatility overlay trial JSON 출력 디렉터리"),
    ],
    annual_cash_yield: Annotated[
        Decimal,
        typer.Option(
            "--annual-cash-yield",
            help="연 현금수익률 Decimal 비율 (기본값 0)",
            parser=_parse_cash_yield_option,
            metavar="DECIMAL",
        ),
    ] = Decimal("0"),
) -> None:
    """네 covariance ERC risky sleeve에 독립 변동성 overlay를 적용합니다."""

    output = _console()
    render_volatility_overlay_research_start(
        start,
        end,
        output_dir,
        target_annual_volatility,
        annual_cash_yield,
        output,
    )
    _exit_after_volatility_overlay_research(
        lambda: run_production_volatility_overlay_research(
            *_parse_cli_date_range(start, end),
            target_annual_volatility,
            annual_cash_yield,
            output_dir=output_dir,
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
    "account_overview",
    "account_performance",
    "account_snapshot",
    "app",
    "main",
    "market_data_daily",
    "market_data_universe",
    "market_data_valuation_prices",
    "portfolio_allocation_research",
    "portfolio_constrained_erc_research",
    "portfolio_historical_report",
    "portfolio_returns",
    "portfolio_risk_model_research",
    "portfolio_volatility_overlay_research",
    "render_account_overview",
    "render_account_performance",
    "render_aligned_return_matrix",
    "render_allocation_research_result",
    "render_allocation_research_start",
    "render_constrained_erc_research_result",
    "render_constrained_erc_research_start",
    "render_daily_market_data",
    "render_historical_report_result",
    "render_historical_report_start",
    "render_market_data_start",
    "render_overview_progress",
    "render_portfolio_returns_start",
    "render_rate_limit_notification",
    "render_risk_model_research_result",
    "render_risk_model_research_start",
    "render_snapshot_summary",
    "render_universe",
    "render_universe_market_data",
    "render_valuation_prices",
    "render_volatility_overlay_research_result",
    "render_volatility_overlay_research_start",
    "run_cli_account_overview",
    "run_cli_account_performance",
    "run_cli_allocation_research",
    "run_cli_constrained_erc_research",
    "run_cli_historical_report",
    "run_cli_market_data",
    "run_cli_portfolio_returns",
    "run_cli_risk_model_research",
    "run_cli_snapshot",
    "run_cli_valuation_prices",
    "run_cli_volatility_overlay_research",
    "universe_add",
    "universe_disable",
    "universe_enable",
    "universe_list",
    "universe_remove",
]
