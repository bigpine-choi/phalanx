from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from phalanx.domain import (
    AlignedReturnMatrix,
    HistoricalUniverseAnalysis,
    KoreanStock,
    StockMarket,
)
from phalanx.portfolio import reporting
from phalanx.portfolio.errors import HistoricalReportStockOrderError
from phalanx.portfolio.performance import analyze_historical_universe
from phalanx.portfolio.reporting import render_historical_report_html

ROOT = Path(__file__).resolve().parents[1]


def _analysis() -> HistoricalUniverseAnalysis:
    matrix = AlignedReturnMatrix(
        stock_codes=("005930", "000660"),
        dates=(date(2026, 1, 2), date(2026, 1, 3), date(2026, 2, 2)),
        values=(
            (Decimal("0.1"), Decimal("0.05")),
            (Decimal("0.1"), Decimal("0.05")),
            (Decimal("0.1"), Decimal("0.05")),
        ),
    )
    return analyze_historical_universe(matrix)


def _visual_analysis() -> HistoricalUniverseAnalysis:
    matrix = AlignedReturnMatrix(
        stock_codes=("005930", "000660"),
        dates=(date(2025, 12, 30), date(2025, 12, 31), date(2026, 1, 2)),
        values=(
            (Decimal("0.10"), Decimal("-0.05")),
            (Decimal("-0.20"), Decimal("0.10")),
            (Decimal("0.05"), Decimal("0.02")),
        ),
    )
    return analyze_historical_universe(matrix)


def test_renders_self_contained_html_with_warnings_na_and_escaped_names() -> None:
    stocks = (
        KoreanStock("005930", "<script>alert('x')</script>", StockMarket.KOSPI),
        KoreanStock("000660", "SK하이닉스", StockMarket.KOSPI),
    )

    html = render_historical_report_html(_analysis(), stocks)

    assert html.startswith("<!doctype html>")
    assert "plotly.js" in html.lower()
    assert "https://cdn.plot.ly" not in html.lower()
    assert "https://cdn." not in html.lower()
    assert '<script src="' not in html.lower()
    for warning in (
        "실제 계좌 성과 아님",
        "Phalanx 전략 백테스트 아님",
        "수수료·세금·슬리피지 미반영",
        "KIS READ ONLY · 주문 미전송",
        "생존편향 가능성",
        "KOSPI 성과를 만들거나 추정하지 않음",
    ):
        assert warning in html
    assert "N/A" in html
    assert "<script>alert('x')</script>" not in html
    assert "&lt;script&gt;alert(&#x27;x&#x27;)&lt;/script&gt;" in html
    assert "동일가중 매수후보유 기준선" in html
    assert "월별 복리수익률" in html
    assert "종목 간 일별 수익률 상관계수" in html


def test_rejects_stock_name_order_that_does_not_match_matrix_columns() -> None:
    reversed_stocks = (
        KoreanStock("000660", "SK하이닉스", StockMarket.KOSPI),
        KoreanStock("005930", "삼성전자", StockMarket.KOSPI),
    )

    with pytest.raises(HistoricalReportStockOrderError, match="순서"):
        render_historical_report_html(_analysis(), reversed_stocks)


def test_decimal_to_float_conversion_exists_only_at_portfolio_rendering_boundary() -> None:
    core_sources = (
        ROOT / "src" / "phalanx" / "domain" / "performance.py",
        ROOT / "src" / "phalanx" / "portfolio" / "performance.py",
    )
    renderer = ROOT / "src" / "phalanx" / "portfolio" / "reporting.py"

    assert all("float(" not in path.read_text(encoding="utf-8") for path in core_sources)
    assert "return float(value)" in renderer.read_text(encoding="utf-8")
    assert (
        "plotly" not in "\n".join(path.read_text(encoding="utf-8") for path in core_sources).lower()
    )


def test_growth_chart_places_vertical_legend_on_right_with_sufficient_space() -> None:
    labels = (
        "005930 아주 긴 한국어 종목명 삼성전자 우선주",
        "000660 아주 긴 한국어 종목명 SK하이닉스",
    )

    figure = reporting._growth_figure(_visual_analysis(), labels)

    assert figure.layout.legend.orientation == "v"
    assert figure.layout.legend.x is not None and figure.layout.legend.x > 1
    assert figure.layout.legend.xanchor == "left"
    assert figure.layout.legend.y == 1
    assert figure.layout.legend.yanchor == "top"
    assert figure.layout.margin.r is not None and figure.layout.margin.r >= 320
    assert figure.layout.margin.b is not None and figure.layout.margin.b >= 80
    assert figure.layout.height is not None and figure.layout.height >= 650
    assert figure.layout.xaxis.title.standoff is not None
    assert figure.layout.xaxis.title.standoff >= 25
    baseline = figure.data[-1]
    assert baseline.name == "동일가중 매수후보유 기준선"
    assert baseline.line.color == "#111827"
    assert baseline.line.width == 4
    assert baseline.line.dash == "dash"


def test_monthly_heatmap_uses_ascending_years_and_dynamic_symmetric_color_range() -> None:
    analysis = _visual_analysis()

    figure = reporting._monthly_heatmap(analysis)

    heatmap = figure.data[0]
    expected_bound = float(max(abs(monthly.value) for monthly in analysis.monthly_baseline_returns))
    assert tuple(heatmap.y) == ("2025", "2026")
    assert figure.layout.yaxis.autorange == "reversed"
    assert tuple(figure.layout.yaxis.categoryarray) == ("2025", "2026")
    assert heatmap.zmin == pytest.approx(-expected_bound)
    assert heatmap.zmax == pytest.approx(expected_bound)
    assert heatmap.zmid == 0
    assert heatmap.zmax != pytest.approx(0.3)
    assert heatmap.hoverongaps is False
    assert any(value is None for row in heatmap.z for value in row)
    assert any(value == "N/A" for row in heatmap.text for value in row)
    assert figure.layout.plot_bgcolor == "#e5e7eb"


def test_monthly_heatmap_uses_nonzero_symmetric_range_when_all_returns_are_zero() -> None:
    matrix = AlignedReturnMatrix(
        stock_codes=("005930",),
        dates=(date(2025, 12, 31), date(2026, 1, 2)),
        values=((Decimal(0),), (Decimal(0),)),
    )

    heatmap = reporting._monthly_heatmap(analyze_historical_universe(matrix)).data[0]

    assert heatmap.zmin is not None and heatmap.zmin < 0
    assert heatmap.zmax is not None and heatmap.zmax > 0
    assert heatmap.zmin == -heatmap.zmax


def test_correlation_heatmap_axes_share_registration_order_with_top_left_diagonal() -> None:
    analysis = _visual_analysis()
    labels = ("005930 삼성전자", "000660 SK하이닉스")

    figure = reporting._correlation_heatmap(analysis, labels)

    heatmap = figure.data[0]
    assert tuple(heatmap.x) == labels
    assert tuple(heatmap.y) == labels
    assert tuple(figure.layout.xaxis.categoryarray) == labels
    assert tuple(figure.layout.yaxis.categoryarray) == labels
    assert figure.layout.yaxis.autorange == "reversed"
    assert heatmap.z[0][0] == pytest.approx(1)
    assert heatmap.z[1][1] == pytest.approx(1)
