"""Offline candidate ranking with explicit parameters and exact JSON output."""

from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError

from phalanx.domain.candidate_selection import SelectionMetric, SelectionPolicy
from phalanx.portfolio.private_json_storage import (
    PrivateJsonAlreadyExistsError,
    PrivateJsonStorageError,
)
from phalanx.selection.decision_snapshot import (
    DecisionInputError,
    DecisionSnapshotService,
    DecisionStorageError,
)
from phalanx.selection.errors import SelectionInputError, SelectionStorageError
from phalanx.selection.service import CandidateSelectionService

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    pretty_exceptions_enable=False,
    help="기존 features JSON으로 후보를 오프라인 평가·선정합니다.",
)


@app.command("select")
def select(
    features: Annotated[Path, typer.Option("--features")],
    metric: Annotated[str, typer.Option("--metric", help="명시적인 단일 가격 지표")],
    top: Annotated[int, typer.Option("--top")],
    max_age_days: Annotated[int, typer.Option("--max-age-days")],
    output: Annotated[Path | None, typer.Option("--output")] = None,
) -> None:
    """모든 입력 후보의 평가 근거와 최대 top개 선정 결과를 JSON으로 출력합니다."""
    try:
        policy = SelectionPolicy(metric=SelectionMetric(metric), top=top, max_age_days=max_age_days)
    except (ValueError, ValidationError):
        typer.echo(
            "INVALID_POLICY: 지원 metric, 양의 top, 0 이상의 max-age-days를 명시하세요.", err=True
        )
        raise typer.Exit(65) from None
    service = CandidateSelectionService()
    try:
        result = service.select(features, policy)
        if output is not None:
            service.export(result, output)
    except SelectionInputError as error:
        typer.echo(f"{error.code}: {error}", err=True)
        raise typer.Exit(65) from None
    except SelectionStorageError:
        typer.echo("INPUT_READ_FAILED: features 파일의 경로·권한을 확인해 주세요.", err=True)
        raise typer.Exit(66) from None
    except PrivateJsonAlreadyExistsError:
        typer.echo("OUTPUT_EXISTS: 기존 출력 파일을 덮어쓰지 않습니다.", err=True)
        raise typer.Exit(66) from None
    except PrivateJsonStorageError:
        typer.echo("OUTPUT_STORAGE_FAILED: 선정 JSON을 원자적으로 저장하지 못했습니다.", err=True)
        raise typer.Exit(66) from None
    typer.echo(result.to_json_bytes().decode("utf-8"), nl=False)
    if not result.complete:
        raise typer.Exit(2)


@app.command("replay")
def replay(
    manifest: Annotated[Path, typer.Option("--manifest", help="판단 시점 명세 JSON")],
    features: Annotated[Path, typer.Option("--features", help="해시로 고정한 features JSON")],
    metric: Annotated[str, typer.Option("--metric", help="명시적인 단일 가격 지표")],
    top: Annotated[int, typer.Option("--top")],
    max_age_days: Annotated[int, typer.Option("--max-age-days")],
    output: Annotated[Path | None, typer.Option("--output", help="새 실행 기록 JSON 경로")] = None,
) -> None:
    """명시적 데이터 이용 시각을 검사하고 기존 후보 선정을 재실행합니다."""
    try:
        policy = SelectionPolicy(metric=SelectionMetric(metric), top=top, max_age_days=max_age_days)
    except (ValueError, ValidationError):
        typer.echo(
            "INVALID_POLICY: 지원 metric, 양의 top, 0 이상의 max-age-days를 명시하세요.", err=True
        )
        raise typer.Exit(65) from None
    service = DecisionSnapshotService()
    try:
        result = service.run(manifest, features, policy)
        if output is not None:
            service.export(result, output)
    except (DecisionInputError, SelectionInputError) as error:
        typer.echo(f"{error.code}: {error}", err=True)
        raise typer.Exit(65) from None
    except DecisionStorageError:
        typer.echo("INPUT_READ_FAILED: 입력 파일의 경로·권한을 확인해 주세요.", err=True)
        raise typer.Exit(66) from None
    except PrivateJsonAlreadyExistsError:
        typer.echo("OUTPUT_EXISTS: 기존 출력 파일을 덮어쓰지 않습니다.", err=True)
        raise typer.Exit(66) from None
    except PrivateJsonStorageError:
        typer.echo("OUTPUT_STORAGE_FAILED: 실행 기록을 원자적으로 저장하지 못했습니다.", err=True)
        raise typer.Exit(66) from None
    typer.echo(result.to_json_bytes().decode("utf-8"), nl=False)
    if not result.selection.complete:
        raise typer.Exit(2)
