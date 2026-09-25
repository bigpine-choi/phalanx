"""Offline, single-date risky-asset research targets with exact write-once JSON."""

from pathlib import Path
from typing import Annotated

import typer

from phalanx.market_data.history.errors import HistoryError, HistoryStorageError
from phalanx.market_data.history.repository import SqliteHistoryRepository
from phalanx.portfolio.allocation_input.errors import AllocationInputError, AllocationInputReadError
from phalanx.portfolio.allocation_input.service import AllocationInputService
from phalanx.portfolio.allocation_targets.service import AllocationTargetsService
from phalanx.portfolio.private_json_storage import (
    PrivateJsonAlreadyExistsError,
    PrivateJsonStorageError,
    store_private_json_bytes,
)


def allocation_targets(
    selection: Annotated[Path, typer.Option("--selection")],
    history_db: Annotated[Path, typer.Option("--history-db")],
    output: Annotated[Path | None, typer.Option("--output")] = None,
) -> None:
    """선정 종목의 마지막 관측일에 네 ERC 연구용 배분안을 독립 계산합니다."""
    try:
        service = AllocationTargetsService(
            AllocationInputService(SqliteHistoryRepository(history_db))
        )
        result = service.calculate(selection)
        payload = result.to_json_bytes()
        if output is not None:
            store_private_json_bytes(output, payload)
    except AllocationInputReadError:
        typer.echo("INPUT_READ_FAILED: selection 파일의 경로·권한을 확인해 주세요.", err=True)
        raise typer.Exit(66) from None
    except HistoryStorageError as error:
        typer.echo(f"{error.code}: {error}", err=True)
        raise typer.Exit(66) from None
    except (AllocationInputError, HistoryError) as error:
        typer.echo(f"{error.code}: {error}", err=True)
        raise typer.Exit(65) from None
    except PrivateJsonAlreadyExistsError:
        typer.echo("OUTPUT_EXISTS: 기존 출력 파일을 덮어쓰지 않습니다.", err=True)
        raise typer.Exit(66) from None
    except PrivateJsonStorageError:
        typer.echo(
            "OUTPUT_STORAGE_FAILED: 목표비중 JSON을 원자적으로 저장하지 못했습니다.", err=True
        )
        raise typer.Exit(66) from None
    except Exception:
        typer.echo(
            "ALLOCATION_TARGETS_INTERNAL_ERROR: "
            "목표비중 처리 중 예상하지 못한 내부 오류가 발생했습니다.",
            err=True,
        )
        raise typer.Exit(2) from None
    typer.echo(payload.decode("utf-8"), nl=False)
    if not result.complete:
        raise typer.Exit(2)
