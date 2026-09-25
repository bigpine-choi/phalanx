"""Render saved research outcomes locally; never launch a browser or a calculation."""

from pathlib import Path
from typing import Annotated

import typer

from phalanx.portfolio.formation_room.errors import FormationRoomInputError
from phalanx.portfolio.formation_room.service import FormationRoomReadError, FormationRoomService
from phalanx.portfolio.private_json_storage import (
    PrivateJsonAlreadyExistsError,
    PrivateJsonStorageError,
)


def formation_room(
    targets: Annotated[Path, typer.Option("--targets")],
    output: Annotated[Path, typer.Option("--output")],
    selection: Annotated[Path | None, typer.Option("--selection")] = None,
) -> None:
    """저장된 목표비중을 오프라인 편성실 HTML로 만듭니다. 계산·추천·주문하지 않습니다."""
    try:
        FormationRoomService().generate(targets, output, selection=selection)
    except FormationRoomReadError:
        typer.echo("INPUT_READ_FAILED: 입력 파일의 경로·권한을 확인해 주세요.", err=True)
        raise typer.Exit(66) from None
    except FormationRoomInputError:
        typer.echo(
            "INVALID_TARGETS: 목표비중·선정 파일의 연결과 화면 입력 계약을 확인해 주세요.", err=True
        )
        raise typer.Exit(65) from None
    except PrivateJsonAlreadyExistsError:
        typer.echo("OUTPUT_EXISTS: 기존 출력 파일을 덮어쓰지 않습니다.", err=True)
        raise typer.Exit(66) from None
    except PrivateJsonStorageError:
        typer.echo("OUTPUT_STORAGE_FAILED: 편성실 HTML을 원자적으로 저장하지 못했습니다.", err=True)
        raise typer.Exit(66) from None
    except Exception:
        typer.echo(
            "FORMATION_ROOM_INTERNAL_ERROR: 화면 생성 중 내부 오류가 발생했습니다.", err=True
        )
        raise typer.Exit(70) from None
    typer.echo("FORMATION_ROOM_SAVED: 오프라인 연구용 편성실 HTML을 저장했습니다.")
