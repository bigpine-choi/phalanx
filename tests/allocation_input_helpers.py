"""Synthetic SQLite -> real features -> real selection inputs shared with the demo."""

from datetime import date, timedelta
from pathlib import Path

from feature_helpers import NOW, bars, history

from phalanx.domain.candidate_selection import SelectionMetric, SelectionPolicy
from phalanx.domain.price_history import (
    HistoryResult,
    HistoryView,
    SymbolHistory,
    SymbolStatus,
    price_data_hash,
)
from phalanx.market_data.features.service import PriceFeatureService
from phalanx.market_data.history.repository import SqliteHistoryRepository
from phalanx.selection.service import CandidateSelectionService

AS_OF = date(2026, 8, 20)
CODES = ("005930", "000001")


def make_view(*, counts=(505, 505), codes=CODES, missing=None, future=0, failed=False):
    series = []
    for ordinal, (code, count) in enumerate(zip(codes, counts, strict=True)):
        start = AS_OF - timedelta(days=count - 1)
        values = [str(10000 + (len(codes) - ordinal) * i) for i in range(count + future)]
        series.append(bars(code, values, start=start))
    if missing:
        series = [
            tuple(b for b in item if b.trade_date not in missing.get(code, ()))
            for code, item in zip(codes, series, strict=True)
        ]
    return view_from_series(tuple(series), codes=codes, failed=failed)


def view_from_series(series, *, codes=CODES, failed=False):
    if failed:
        codes = (*codes, "000099")
    base = history(tuple(SymbolStatus.FAILED for _ in codes), codes=codes)
    dates = [b.trade_date for item in series for b in item]
    job = base.job.model_copy(
        update={
            "start": min([AS_OF, *dates]),
            "end": max([AS_OF, *dates]),
        }
    )
    states = tuple(
        SymbolHistory(
            ordinal=index,
            status=SymbolStatus.COMPLETED if item else SymbolStatus.EMPTY,
            result=HistoryResult(
                bars=item,
                row_count=len(item),
                first_trade_date=item[0].trade_date if item else None,
                last_trade_date=item[-1].trade_date if item else None,
                sha256=price_data_hash(item),
            ),
        )
        for index, item in enumerate(series)
    )
    if failed:
        states = (*states, base.symbols[-1])
    return HistoryView(job=job, symbols=states)


def create_inputs(directory: Path, view=None, *, top=2):
    view = make_view() if view is None else view
    repository = SqliteHistoryRepository(directory / "history" / "history.sqlite3")
    repository.create(view)
    features = PriceFeatureService(repository, clock=lambda: NOW).calculate(
        view.job.job_id,
        as_of=AS_OF,
        all_targets=True,
    )
    feature_path = directory / "features.json"
    PriceFeatureService.export(features, feature_path)
    selection = CandidateSelectionService(clock=lambda: NOW).select(
        feature_path,
        SelectionPolicy(metric=SelectionMetric.RETURN_60, top=top, max_age_days=7),
    )
    selection_path = directory / "selection.json"
    CandidateSelectionService.export(selection, selection_path)
    return repository, selection_path, selection, view
