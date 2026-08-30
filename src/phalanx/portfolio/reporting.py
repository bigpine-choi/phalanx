"""Self-contained Plotly HTML rendering at the Decimal-to-float boundary."""

from __future__ import annotations

from decimal import Decimal
from html import escape

import plotly.graph_objects as go  # type: ignore[import-untyped]
import plotly.io as pio  # type: ignore[import-untyped]

from phalanx.domain import HistoricalUniverseAnalysis, KoreanStock, PerformanceMetrics
from phalanx.portfolio.errors import (
    HistoricalReportRenderError,
    HistoricalReportStockOrderError,
)

_BASELINE_LABEL = "동일가중 매수후보유 기준선"
_ZERO_MONTHLY_RETURN_COLOR_BOUND = Decimal("0.01")


def render_historical_report_html(
    analysis: HistoricalUniverseAnalysis,
    stocks: tuple[KoreanStock, ...],
) -> str:
    """Render already-calculated analysis without performing financial calculations."""

    _validate_stock_order(analysis, stocks)
    try:
        labels = tuple(
            f"{stock.stock_code} {escape(stock.stock_name, quote=True)}" for stock in stocks
        )
        figures = (
            _growth_figure(analysis, labels),
            _drawdown_figure(analysis),
            _monthly_heatmap(analysis),
            _correlation_heatmap(analysis, labels),
        )
        figure_html = tuple(
            pio.to_html(
                figure,
                full_html=False,
                include_plotlyjs=index == 0,
                include_mathjax=False,
                config={"displaylogo": False, "responsive": True},
            )
            for index, figure in enumerate(figures)
        )
        stock_rows = "".join(
            _metrics_row(label, metrics)
            for label, metrics in zip(labels, analysis.stock_metrics, strict=True)
        )
        baseline_row = _metrics_row(_BASELINE_LABEL, analysis.baseline_metrics)
        return _html_document(
            analysis=analysis,
            stock_rows=stock_rows,
            baseline_row=baseline_row,
            figure_html=figure_html,
        )
    except HistoricalReportRenderError:
        raise
    except Exception:
        raise HistoricalReportRenderError(
            "과거 유니버스 HTML 리포트를 안전하게 렌더링하지 못했습니다."
        ) from None


def _validate_stock_order(
    analysis: HistoricalUniverseAnalysis,
    stocks: tuple[KoreanStock, ...],
) -> None:
    if not isinstance(stocks, tuple):
        raise HistoricalReportStockOrderError("리포트 종목 정보는 tuple이어야 합니다.")
    stock_codes = tuple(stock.stock_code for stock in stocks)
    if stock_codes != analysis.stock_codes:
        raise HistoricalReportStockOrderError(
            "리포트 종목코드·종목명 순서가 수익률 행렬 열 순서와 일치하지 않습니다."
        )


def _growth_figure(
    analysis: HistoricalUniverseAnalysis,
    labels: tuple[str, ...],
) -> go.Figure:
    figure = go.Figure()
    for column, label in enumerate(labels):
        figure.add_trace(
            go.Scatter(
                x=analysis.dates,
                y=[_to_float(row[column]) for row in analysis.stock_growth_factors],
                mode="lines",
                name=label,
            )
        )
    figure.add_trace(
        go.Scatter(
            x=analysis.dates,
            y=[_to_float(value) for value in analysis.baseline_growth_factors],
            mode="lines",
            name=_BASELINE_LABEL,
            line={"color": "#111827", "width": 4, "dash": "dash"},
        )
    )
    figure.update_layout(
        title="종목별 및 기준선 누적수익률 (성장계수, 초기값 1)",
        xaxis={
            "title": {"text": "수익률 기준일", "standoff": 30},
            "automargin": True,
        },
        yaxis_title="누적 성장계수",
        template="plotly_white",
        height=680,
        margin={"r": 360, "b": 100},
        legend={
            "orientation": "v",
            "x": 1.02,
            "xanchor": "left",
            "y": 1,
            "yanchor": "top",
        },
    )
    return figure


def _drawdown_figure(analysis: HistoricalUniverseAnalysis) -> go.Figure:
    figure = go.Figure(
        go.Scatter(
            x=analysis.dates,
            y=[_to_float(value) for value in analysis.baseline_drawdowns],
            mode="lines",
            fill="tozeroy",
            name="기준선 Drawdown",
            line={"color": "#dc2626"},
        )
    )
    figure.update_layout(
        title="동일가중 매수후보유 기준선 Drawdown",
        xaxis_title="수익률 기준일",
        yaxis_title="Drawdown",
        yaxis={"tickformat": ".1%"},
        template="plotly_white",
    )
    return figure


def _monthly_heatmap(analysis: HistoricalUniverseAnalysis) -> go.Figure:
    years = tuple(sorted({monthly.month.year for monthly in analysis.monthly_baseline_returns}))
    maximum_absolute_return = max(
        (abs(monthly.value) for monthly in analysis.monthly_baseline_returns),
        default=Decimal(0),
    )
    color_bound = _to_float(maximum_absolute_return or _ZERO_MONTHLY_RETURN_COLOR_BOUND)
    by_month = {
        (monthly.month.year, monthly.month.month): monthly.value
        for monthly in analysis.monthly_baseline_returns
    }
    values = [
        [_optional_float(by_month.get((year, month))) for month in range(1, 13)] for year in years
    ]
    text = [
        [_format_optional_percent(by_month.get((year, month))) for month in range(1, 13)]
        for year in years
    ]
    figure = go.Figure(
        go.Heatmap(
            x=[f"{month}월" for month in range(1, 13)],
            y=[str(year) for year in years],
            z=values,
            text=text,
            texttemplate="%{text}",
            colorscale="RdYlGn",
            zmid=0,
            zmin=-color_bound,
            zmax=color_bound,
            colorbar={"title": "월 수익률"},
            hoverongaps=False,
            hovertemplate="%{y}년 %{x}<br>%{text}<extra></extra>",
        )
    )
    figure.update_layout(
        title="동일가중 매수후보유 기준선 월별 복리수익률",
        template="plotly_white",
        plot_bgcolor="#e5e7eb",
        yaxis={
            "autorange": "reversed",
            "categoryorder": "array",
            "categoryarray": [str(year) for year in years],
        },
    )
    return figure


def _correlation_heatmap(
    analysis: HistoricalUniverseAnalysis,
    labels: tuple[str, ...],
) -> go.Figure:
    values = [[_optional_float(value) for value in row] for row in analysis.correlation_matrix]
    text = [
        [_format_optional_decimal(value) for value in row] for row in analysis.correlation_matrix
    ]
    figure = go.Figure(
        go.Heatmap(
            x=labels,
            y=labels,
            z=values,
            text=text,
            texttemplate="%{text}",
            colorscale="RdBu",
            reversescale=True,
            zmin=-1,
            zmax=1,
            colorbar={"title": "Pearson 상관계수"},
            hovertemplate="%{y} / %{x}<br>%{text}<extra></extra>",
        )
    )
    figure.update_layout(
        title="종목 간 일별 수익률 상관계수",
        template="plotly_white",
        xaxis={
            "categoryorder": "array",
            "categoryarray": list(labels),
            "automargin": True,
        },
        yaxis={
            "categoryorder": "array",
            "categoryarray": list(labels),
            "autorange": "reversed",
            "automargin": True,
        },
    )
    return figure


def _metrics_row(label: str, metrics: PerformanceMetrics) -> str:
    cells = (
        label,
        str(metrics.observation_count),
        _format_percent(metrics.total_return),
        _format_percent(metrics.annualized_return),
        _format_percent(metrics.annualized_volatility),
        _format_optional_decimal(metrics.sharpe_ratio),
        _format_optional_decimal(metrics.sortino_ratio),
        _format_percent(metrics.max_drawdown),
        _format_optional_decimal(metrics.calmar_ratio),
        _format_percent(metrics.positive_day_ratio),
        _format_percent(metrics.best_daily_return),
        _format_percent(metrics.worst_daily_return),
    )
    return "<tr>" + "".join(f"<td>{cell}</td>" for cell in cells) + "</tr>"


def _html_document(
    *,
    analysis: HistoricalUniverseAnalysis,
    stock_rows: str,
    baseline_row: str,
    figure_html: tuple[str, ...],
) -> str:
    document = f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Phalanx 과거 유니버스 성과 분석</title>
  <style>
    body {{
      font-family: system-ui, sans-serif;
      margin: 2rem auto;
      max-width: 1400px;
      padding: 0 1rem;
      color: #111827;
    }}
    h1, h2 {{ color: #111827; }}
    .warning {{ border-left: 5px solid #d97706; background: #fffbeb; padding: 1rem 1.25rem; }}
    .summary {{ display: flex; flex-wrap: wrap; gap: 1rem; margin: 1rem 0; }}
    .summary div {{ background: #f3f4f6; border-radius: .5rem; padding: .75rem 1rem; }}
    table {{ border-collapse: collapse; width: 100%; overflow-x: auto; display: block; }}
    th, td {{ border: 1px solid #d1d5db; padding: .55rem; text-align: right; white-space: nowrap; }}
    th:first-child, td:first-child {{ text-align: left; }}
    section {{ margin: 2rem 0; }}
  </style>
</head>
<body>
  <h1>Phalanx 과거 유니버스 성과 분석</h1>
  <div class="warning">
    <strong>분석 전제 및 경고</strong>
    <ul>
      <li>실제 계좌 성과 아님</li>
      <li>Phalanx 전략 백테스트 아님</li>
      <li>동일가중 기준선은 최초에 각 종목에 1/N을 배분하고 리밸런싱하지 않는 매수후보유 기준선</li>
      <li>수수료·세금·슬리피지 미반영</li>
      <li>입출금 및 실제 체결 성과 미반영</li>
      <li>현재 활성 유니버스를 과거에 적용하므로 생존편향 가능성 있음</li>
      <li>KOSPI 데이터 미포함 · KOSPI 성과를 만들거나 추정하지 않음</li>
      <li>KIS READ ONLY · 주문 미전송</li>
    </ul>
  </div>
  <div class="summary">
    <div>분석 시작일: <strong>{analysis.dates[0].isoformat()}</strong></div>
    <div>분석 종료일: <strong>{analysis.dates[-1].isoformat()}</strong></div>
    <div>수익률 관측치: <strong>{len(analysis.dates)}개</strong></div>
    <div>종목 수: <strong>{len(analysis.stock_codes)}개</strong></div>
  </div>
  <section>
    <h2>종목별 성과지표</h2>
    {_metrics_table(stock_rows)}
  </section>
  <section>
    <h2>동일가중 매수후보유 기준선 요약</h2>
    {_metrics_table(baseline_row)}
  </section>
  <section><h2>종목별 및 기준선 누적수익률</h2>{figure_html[0]}</section>
  <section><h2>기준선 Drawdown</h2>{figure_html[1]}</section>
  <section><h2>기준선 월별 복리수익률</h2>{figure_html[2]}</section>
  <section><h2>종목 간 일별 수익률 상관계수</h2>{figure_html[3]}</section>
</body>
</html>
"""
    # The bundled Plotly source contains unused map/CDN defaults. These reports
    # have no map traces, so neutralize those references for strict offline use.
    for remote_prefix in (
        "https://cdn.plot.ly",
        "https://cdn.jsdelivr.net",
        "https://basemaps.cartocdn.com",
        "https://tiles.basemaps.cartocdn.com",
    ):
        document = document.replace(remote_prefix, "plotly-local-assets")
    return document


def _metrics_table(rows: str) -> str:
    return f"""<table>
<thead><tr>
<th>대상</th><th>관측치</th><th>총수익률</th><th>연환산수익률</th>
<th>연환산변동성</th><th>Sharpe</th><th>Sortino</th><th>최대낙폭</th>
<th>Calmar</th><th>상승일 비율</th><th>최고 일간수익률</th><th>최악 일간수익률</th>
</tr></thead><tbody>{rows}</tbody></table>"""


def _format_percent(value: Decimal) -> str:
    return format(value, ".2%")


def _format_optional_percent(value: Decimal | None) -> str:
    return "N/A" if value is None else _format_percent(value)


def _format_optional_decimal(value: Decimal | None) -> str:
    return "N/A" if value is None else format(value, ".4f")


def _to_float(value: Decimal) -> float:
    return float(value)


def _optional_float(value: Decimal | None) -> float | None:
    return None if value is None else _to_float(value)


__all__ = ["render_historical_report_html"]
