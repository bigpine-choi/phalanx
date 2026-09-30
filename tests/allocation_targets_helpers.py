"""Independent nondegenerate synthetic prices through real production services."""

from datetime import date, timedelta
from pathlib import Path
from random import Random

from allocation_input_helpers import view_from_series
from feature_helpers import NOW, bars

from phalanx.domain.candidate_selection import SelectionMetric, SelectionPolicy
from phalanx.domain.price_history import HistoryAttempt, HistoryView, SymbolStatus
from phalanx.market_data.features.service import PriceFeatureService
from phalanx.market_data.history.repository import SqliteHistoryRepository
from phalanx.selection.service import CandidateSelectionService

AS_OF = date(2026, 8, 20)
CODES = ("005930", "000001", "000660", "035420", "051910", "000002")


def target_inputs(
    directory: Path,
    *,
    size=6,
    count=505,
    codes=None,
    as_of=AS_OF,
    end=AS_OF,
    future=0,
    missing=False,
    top=None,
    degenerate=False,
    failed_candidate=False,
    names=None,
    fetch_receipts=False,
):
    codes = CODES[:size] if codes is None else codes
    days = []
    cursor = end
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor -= timedelta(days=1)
    days.reverse()
    cursor = as_of
    while len(days) < count + future:
        cursor += timedelta(days=1)
        if cursor.weekday() < 5:
            days.append(cursor)
    series = []
    for index, code in enumerate(codes):
        rng = Random(2300 + index)
        price = 100000 + 1000 * index
        closes = []
        for _ in days:
            price += rng.randrange(-1200, 1401)
            closes.append("100000" if degenerate else str(price))
        source = bars(code, closes)
        series.append(
            tuple(
                bar.model_copy(update={"trade_date": day})
                for i, (bar, day) in enumerate(zip(source, days, strict=True))
                if not (missing and index == 0 and i == 200)
            )
        )
    view = view_from_series(tuple(series), codes=codes, failed=failed_candidate)
    view = view.model_copy(
        update={"job": view.job.model_copy(update={"end": max(days[-1], as_of)})}
    )
    if names is not None:
        # Source metadata precedes persistence, features, selection and every hash.
        targets = tuple(
            target.model_copy(update={"name": names.get(target.short_code, target.name)})
            for target in view.job.targets
        )
        view = view.model_copy(update={"job": view.job.model_copy(update={"targets": targets})})
    if fetch_receipts:
        view = HistoryView(
            job=view.job,
            symbols=tuple(
                state.model_copy(
                    update={
                        "attempts": (
                            HistoryAttempt(
                                number=1,
                                started_at=NOW,
                                finished_at=NOW + timedelta(minutes=1),
                                outcome="completed",
                            ),
                        )
                    }
                )
                if state.status == SymbolStatus.COMPLETED
                else state
                for state in view.symbols
            ),
        )
    repository = SqliteHistoryRepository(directory / "history" / "history.sqlite3")
    repository.create(view)
    features = PriceFeatureService(repository, clock=lambda: NOW).calculate(
        view.job.job_id,
        as_of=as_of,
        all_targets=True,
    )
    feature_path = directory / "features.json"
    PriceFeatureService.export(features, feature_path)
    selection_service = CandidateSelectionService(clock=lambda: NOW)
    selection = selection_service.select(
        feature_path,
        SelectionPolicy(
            metric=SelectionMetric.RETURN_60,
            top=len(codes) if top is None else top,
            max_age_days=7,
        ),
    )
    selection_path = directory / "selection.json"
    selection_service.export(selection, selection_path)
    return repository, selection_path, selection, view
