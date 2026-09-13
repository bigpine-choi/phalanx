"""Offline candidate feature calculation, JSON display and optional atomic export."""

from datetime import date
from pathlib import Path
from typing import Annotated

import typer

from phalanx.market_data.features.errors import PriceFeatureError
from phalanx.market_data.features.service import PriceFeatureService
from phalanx.market_data.history.errors import HistoryError, HistoryStorageError
from phalanx.market_data.history.repository import SqliteHistoryRepository
from phalanx.portfolio.private_json_storage import (
    PrivateJsonAlreadyExistsError,
    PrivateJsonStorageError,
)

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    pretty_exceptions_enable=False,
    help="저장된 후보 일봉의 가격 특성값을 오프라인 계산·조회·JSON 내보내기합니다.",
)


def _as_of(value: str) -> date:
    try:
        parsed = date.fromisoformat(value)
        if parsed.isoformat() != value:
            raise ValueError
        return parsed
    except ValueError:
        raise PriceFeatureError("INVALID_AS_OF", "--as-of는 YYYY-MM-DD 날짜여야 합니다.") from None


@app.command("calculate")
def calculate(
    job_id: str,
    as_of: Annotated[str, typer.Option("--as-of")],
    code: Annotated[
        list[str] | None, typer.Option("--code", help="반복 가능한 정확한 단축코드")
    ] = None,
    all_targets: Annotated[bool, typer.Option("--all-targets")] = False,
    history_db: Annotated[Path | None, typer.Option("--history-db")] = None,
    output: Annotated[Path | None, typer.Option("--output", help="덮어쓰지 않을 JSON 경로")] = None,
) -> None:
    """선택 종목을 독립 계산합니다. 일부 지표가 null이어도 JSON을 출력·저장합니다."""
    try:
        cutoff = _as_of(as_of)
        service = PriceFeatureService(SqliteHistoryRepository(history_db))
        result = service.calculate(
            job_id, as_of=cutoff, codes=tuple(code or ()), all_targets=all_targets
        )
        if output is not None:
            service.export(result, output)
    except HistoryStorageError as error:
        typer.echo(f"{error.code}: {error}", err=True)
        raise typer.Exit(66) from None
    except PrivateJsonAlreadyExistsError:
        typer.echo("OUTPUT_EXISTS: 기존 출력 파일을 덮어쓰지 않습니다.", err=True)
        raise typer.Exit(66) from None
    except PrivateJsonStorageError:
        typer.echo("OUTPUT_STORAGE_FAILED: JSON을 원자적으로 저장하지 못했습니다.", err=True)
        raise typer.Exit(66) from None
    except (HistoryError, PriceFeatureError) as error:
        typer.echo(f"{error.code}: {error}", err=True)
        raise typer.Exit(65) from None
    typer.echo(result.to_json_bytes().decode("utf-8"), nl=False)
    if not result.complete:
        raise typer.Exit(2)
