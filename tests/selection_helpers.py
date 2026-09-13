"""Synthetic valid feature snapshots for selection tests; no source database needed."""

from datetime import date, timedelta
from decimal import Decimal

from feature_helpers import NOW, bars, history

from phalanx.domain.candidate_selection import SelectionMetric, SelectionPolicy
from phalanx.domain.price_history import SymbolStatus
from phalanx.market_data.features.calculation import calculate_price_features

AS_OF = date(2026, 8, 20)
CODES = ("0001A0", "000001", "000003")


def features(*, codes=CODES, counts=None, ages=None, statuses=None):
    counts = counts or (253,) * len(codes)
    ages = ages or (0,) * len(codes)
    statuses = statuses or (SymbolStatus.COMPLETED,) * len(codes)
    series = []
    for code, count, age, status in zip(codes, counts, ages, statuses, strict=True):
        if status == SymbolStatus.EMPTY:
            series.append(())
        elif status != SymbolStatus.COMPLETED:
            series.append(status)
        elif count == 0:
            series.append(bars(code, ["100"], start=AS_OF + timedelta(days=1)))
        else:
            end = AS_OF - timedelta(days=age)
            series.append(bars(code, ["100"] * count, start=end - timedelta(days=count - 1)))
    view = history(tuple(series), codes=codes)
    return calculate_price_features(view.job, view.symbols, as_of=AS_OF, calculated_at=NOW)


def scores(source, values, metric=SelectionMetric.RETURN_60):
    rule = SelectionPolicy(metric=metric, top=1, max_age_days=0).rule
    symbols = []
    for symbol, value in zip(source.symbols, values, strict=True):
        symbols.append(
            symbol.model_copy(
                update={
                    "metrics": tuple(
                        item.model_copy(update={"value": Decimal(value)})
                        if (item.name, item.intervals) == (rule.name, rule.intervals)
                        else item
                        for item in symbol.metrics
                    ),
                }
            )
        )
    return source.model_copy(update={"symbols": tuple(symbols)})
