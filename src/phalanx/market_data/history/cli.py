"""History commands; creation and stored reads never assemble a KIS client."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Annotated

import typer

from phalanx.config import ConfigError
from phalanx.discovery.errors import DiscoveryError, DiscoveryStorageError
from phalanx.discovery.repository import SqliteDiscoveryRepository
from phalanx.domain.price_history import HistoryView
from phalanx.kis.errors import KisAuthError
from phalanx.market_data.errors import InvalidMarketDataRequestError
from phalanx.market_data.history.application import production_history_reader
from phalanx.market_data.history.errors import HistoryError, HistoryStorageError
from phalanx.market_data.history.repository import SqliteHistoryRepository
from phalanx.market_data.history.service import HistoryService

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    pretty_exceptions_enable=False,
    help="고정한 적격 후보의 수정주가 일봉을 저장·재개·오프라인 조회합니다.",
)
HistoryPath = Annotated[Path | None, typer.Option("--history-db", help="별도 일봉 SQLite 경로")]
DiscoveryPath = Annotated[
    Path | None, typer.Option("--discovery-db", help="입력 discovery SQLite 경로")
]


def _execute(action: Callable[[], None]) -> None:
    try:
        action()
    except (HistoryStorageError, DiscoveryStorageError) as error:
        typer.echo(f"{error.code}: {error}", err=True)
        raise typer.Exit(66) from None
    except (HistoryError, DiscoveryError) as error:
        typer.echo(f"{error.code}: {error}", err=True)
        raise typer.Exit(65) from None
    except InvalidMarketDataRequestError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(65) from None
    except (ConfigError, KisAuthError):
        typer.echo("AUTHENTICATION_FAILED: 기존 KIS 자격증명·토큰 설정을 확인해 주세요.", err=True)
        raise typer.Exit(69) from None
    except KeyboardInterrupt:
        typer.echo("수집이 중단되었습니다. 같은 작업을 run하여 미완료 종목을 재개하세요.", err=True)
        raise typer.Exit(130) from None


def _date(value: str) -> date:
    try:
        parsed = date.fromisoformat(value)
        if parsed.isoformat() != value:
            raise ValueError
        return parsed
    except ValueError:
        raise HistoryError("INVALID_DATE", "날짜는 YYYY-MM-DD 형식이어야 합니다.") from None


def _summary(view: HistoryView, path: Path) -> None:
    job = view.job
    typer.echo(f"JOB_ID: {job.job_id}")
    typer.echo(
        f"discovery 실행: {job.discovery_run_id} / "
        f"수집 완료: {job.discovery_completed_at.isoformat()}"
    )
    typer.echo(f"요청 기간: {job.start} ~ {job.end} / 대상: {len(job.targets)}")
    typer.echo(" / ".join(f"{status}: {count}" for status, count in view.counts.items()))
    typer.echo("API 조회 완료와 거래일 무누락은 다릅니다. 기간 완전성: unverified")
    typer.echo(f"저장 위치: {path}")
    for target, symbol in zip(job.targets, view.symbols, strict=True):
        result = symbol.result
        typer.echo(
            f"[{symbol.ordinal}] {target.market} {target.short_code!s} / {symbol.status} / "
            f"시도 {len(symbol.attempts)} / 행 {result.row_count if result else '-'}"
        )
        if symbol.attempts:
            last = symbol.attempts[-1]
            typer.echo(f"  최근 수집: {last.started_at.isoformat()} ~ {last.finished_at or '-'}")
        if symbol.error_code:
            typer.echo(f"  {symbol.error_code}: {symbol.error_message}")


@app.command("create")
def create(
    discovery_run_id: Annotated[str, typer.Option("--discovery-run-id")],
    start: Annotated[str, typer.Option("--start")],
    end: Annotated[str, typer.Option("--end")],
    code: Annotated[
        list[str] | None, typer.Option("--code", help="반복 가능한 정확한 단축코드")
    ] = None,
    all_eligible: Annotated[bool, typer.Option("--all-eligible")] = False,
    discovery_db: DiscoveryPath = None,
    history_db: HistoryPath = None,
) -> None:
    """지정한 성공 discovery 실행의 적격 후보를 오프라인으로 고정합니다."""

    def action() -> None:
        repository = SqliteHistoryRepository(history_db)
        view = HistoryService(repository).create(
            SqliteDiscoveryRepository(discovery_db),
            discovery_run_id,
            _date(start),
            _date(end),
            codes=tuple(code or ()),
            all_eligible=all_eligible,
        )
        _summary(view, repository.path)

    _execute(action)


@app.command("run")
def run(
    job_id: str,
    retry_failed: Annotated[bool, typer.Option("--retry-failed")] = False,
    max_symbols: Annotated[int | None, typer.Option("--max-symbols", min=1)] = None,
    history_db: HistoryPath = None,
) -> None:
    """미완료 종목을 순서대로 수집합니다. 실패 재시도는 명시적으로 선택합니다."""

    def action() -> None:
        repository = SqliteHistoryRepository(history_db)
        view = HistoryService(repository).run(
            job_id,
            production_history_reader,
            retry_failed=retry_failed,
            max_symbols=max_symbols,
        )
        _summary(view, repository.path)
        if not view.complete:
            raise typer.Exit(2)

    _execute(action)


@app.command("status")
def status(job_id: str, history_db: HistoryPath = None) -> None:
    """자격증명·네트워크 없이 저장된 작업 진행 상태를 표시합니다."""

    def action() -> None:
        repository = SqliteHistoryRepository(history_db)
        _summary(repository.load(job_id), repository.path)

    _execute(action)


@app.command("show")
def show(job_id: str, stock_code: str, history_db: HistoryPath = None) -> None:
    """저장된 종목 정보·시도·가격·해시·수집 근거를 JSON으로 읽습니다."""

    def action() -> None:
        repository = SqliteHistoryRepository(history_db)
        job, symbol = repository.show(job_id, stock_code)
        payload = {
            "job": job.model_dump(mode="json", exclude={"targets"}),
            "target": job.targets[symbol.ordinal].model_dump(mode="json"),
            "symbol": symbol.model_dump(mode="json"),
        }
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))

    _execute(action)
