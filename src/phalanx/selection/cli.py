"""Offline candidate ranking with explicit parameters and exact JSON output."""

from datetime import date, datetime
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError

from phalanx.desktop.storage import StorageError, read_selected_file
from phalanx.domain.candidate_selection import SelectionMetric, SelectionPolicy
from phalanx.market_data.features.errors import PriceFeatureError
from phalanx.market_data.history.errors import HistoryError, HistoryStorageError
from phalanx.market_data.history.read_receipt import (
    MAX_READ_RECEIPT_BYTES,
    HistoryReadReceiptError,
)
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
from phalanx.selection.history_replay import (
    MAX_REPLAY_TARGETS,
    HistoryReplayError,
    HistoryReplayService,
)
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


@app.command("replay-history")
def replay_history(
    history_db: Annotated[Path, typer.Option("--history-db", help="저장 일봉 SQLite 경로")],
    job_id: Annotated[str, typer.Option("--job-id", help="불변 일봉 작업 ID")],
    as_of: Annotated[str, typer.Option("--as-of", help="YYYY-MM-DD 기준일")],
    decision_at: Annotated[str, typer.Option("--decision-at", help="시간대 포함 판단 시각")],
    metric: Annotated[str, typer.Option("--metric", help="명시적인 단일 가격 지표")],
    top: Annotated[int, typer.Option("--top")],
    max_age_days: Annotated[int, typer.Option("--max-age-days")],
    code: Annotated[list[str] | None, typer.Option("--code", help="반복 가능한 종목 코드")] = None,
    read_receipt: Annotated[
        Path | None, typer.Option("--read-receipt", help="저장 후 읽기 확인 영수증 JSON")
    ] = None,
    output: Annotated[Path | None, typer.Option("--output", help="새 실행 기록 JSON 경로")] = None,
) -> None:
    """저장된 일봉의 로컬 수집 완료 시각을 검사하고 후보를 재선정합니다."""
    try:
        policy = SelectionPolicy(metric=SelectionMetric(metric), top=top, max_age_days=max_age_days)
    except (ValueError, ValidationError):
        typer.echo(
            "INVALID_POLICY: 지원 metric, 양의 top, 0 이상의 max-age-days를 명시하세요.", err=True
        )
        raise typer.Exit(65) from None
    try:
        parsed_as_of = date.fromisoformat(as_of)
        if parsed_as_of.isoformat() != as_of:
            raise ValueError
        parsed_decision_at = datetime.fromisoformat(decision_at)
    except ValueError:
        typer.echo("INVALID_DECISION_TIME: 날짜와 시간대 포함 판단 시각을 확인하세요.", err=True)
        raise typer.Exit(65) from None
    if not code or len(code) > MAX_REPLAY_TARGETS:
        typer.echo(f"INVALID_SELECTION: --code 1~{MAX_REPLAY_TARGETS}개가 필요합니다.", err=True)
        raise typer.Exit(65) from None
    from phalanx.market_data.history.repository import SqliteHistoryRepository

    service = HistoryReplayService()
    try:
        receipt_bytes = (
            read_selected_file(read_receipt, MAX_READ_RECEIPT_BYTES)
            if read_receipt is not None
            else None
        )
        result = service.run(
            SqliteHistoryRepository(history_db),
            job_id,
            parsed_as_of,
            parsed_decision_at,
            policy,
            codes=tuple(code),
            read_receipt_bytes=receipt_bytes,
        )
        if output is not None:
            service.export(result, output)
    except HistoryStorageError as error:
        typer.echo(f"{error.code}: {error}", err=True)
        raise typer.Exit(66) from None
    except (StorageError, OSError):
        typer.echo("RECEIPT_READ_FAILED: 읽기 영수증 경로·권한·크기를 확인하세요.", err=True)
        raise typer.Exit(66) from None
    except (
        HistoryReplayError,
        HistoryReadReceiptError,
        HistoryError,
        PriceFeatureError,
        SelectionInputError,
    ) as error:
        typer.echo(f"{error.code}: {error}", err=True)
        raise typer.Exit(65) from None
    except PrivateJsonAlreadyExistsError:
        typer.echo("OUTPUT_EXISTS: 기존 출력 파일을 덮어쓰지 않습니다.", err=True)
        raise typer.Exit(66) from None
    except PrivateJsonStorageError:
        typer.echo("OUTPUT_STORAGE_FAILED: 실행 기록을 원자적으로 저장하지 못했습니다.", err=True)
        raise typer.Exit(66) from None
    typer.echo(result.to_json_bytes().decode("utf-8"), nl=False)
    if not result.selection.complete:
        raise typer.Exit(2)
