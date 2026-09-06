"""Offline daily NAV import, replay, and inspection commands."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal

import typer

from phalanx.nav.models import NavError, parse_bundle_bytes
from phalanx.nav.storage import NavStorageError, NavStore

app = typer.Typer(
    add_completion=False,
    help="정규화된 원장으로 일별 NAV·기준가를 저장·복원합니다 (오프라인).",
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)


class _Environment(StrEnum):
    DEVELOPMENT = "development"
    OFFICIAL = "official"


def _environment(value: _Environment) -> Literal["development", "official"]:
    return "development" if value == _Environment.DEVELOPMENT else "official"


def _through_date(value: str) -> date:
    if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) is None:
        raise NavError("복원 종료일 형식이 올바르지 않습니다.")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise NavError("복원 종료일이 실제 날짜가 아닙니다.") from None


def _run(action: Callable[[], object]) -> None:
    """Keep stdout machine-readable and never echo payloads or exception details."""

    try:
        result = action()
        typer.echo(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    except NavStorageError:
        typer.echo(
            "NAV 저장 오류: 설정·개정 충돌과 저장소 경로·접근 권한·저장 공간을 확인해 주세요.",
            err=True,
        )
        raise typer.Exit(66) from None
    except NavError:
        typer.echo(
            "NAV 입력·계산 오류: 명시한 날짜와 정규화 입력·정정 버전을 확인해 주세요.",
            err=True,
        )
        raise typer.Exit(65) from None
    except KeyboardInterrupt:
        typer.echo("중단됨: NAV 작업을 안전하게 종료했습니다.", err=True)
        raise typer.Exit(130) from None
    except Exception:
        typer.echo("예기치 않은 오류로 NAV 작업을 완료하지 못했습니다.", err=True)
        raise typer.Exit(70) from None


@app.command("import")
def import_data(
    db: Annotated[Path, typer.Option("--db", help="사용자가 지정한 private SQLite 경로")],
    input_path: Annotated[
        Path, typer.Option("--input", help="정규화 원장·평가자료 JSON (십진수는 문자열)")
    ],
) -> None:
    """원본 입력과 개정 이력을 보존합니다. 설정일을 자동 지정하지 않습니다."""

    def action() -> object:
        try:
            payload = input_path.read_bytes()
        except OSError:
            raise NavError("입력 파일을 읽을 수 없습니다.") from None
        bundle = parse_bundle_bytes(payload)
        with NavStore(db, create=True) as store:
            return store.import_bundle(bundle, raw_payload=payload)

    _run(action)


@app.command("restore")
def restore(
    db: Annotated[Path, typer.Option("--db", help="기존 private SQLite 경로")],
    series: Annotated[str, typer.Option("--series", help="성과 계열 식별자")],
    environment: Annotated[_Environment, typer.Option("--environment", help="개발/공식 구분")],
    through: Annotated[str, typer.Option("--through", help="명시적 복원 종료일 YYYY-MM-DD")],
) -> None:
    """저장 원장을 날짜순으로 복원하고 미확정 사유를 포함해 JSON을 반환합니다."""

    def action() -> object:
        end = _through_date(through)
        with NavStore(db) as store:
            return [
                row.model_dump(mode="json")
                for row in store.restore(series, _environment(environment), end)
            ]

    _run(action)


@app.command("query")
def query(
    db: Annotated[Path, typer.Option("--db", help="기존 private SQLite 경로")],
    series: Annotated[str, typer.Option("--series", help="성과 계열 식별자")],
    environment: Annotated[_Environment, typer.Option("--environment", help="개발/공식 구분")],
) -> None:
    """현재 저장된 일별 결과를 조회합니다. 변경한 입력은 restore로 재계산합니다."""

    def action() -> object:
        with NavStore(db) as store:
            return [
                row.model_dump(mode="json")
                for row in store.query(series, _environment(environment))
            ]

    _run(action)


@app.command("history")
def history(
    db: Annotated[Path, typer.Option("--db", help="기존 private SQLite 경로")],
    series: Annotated[str, typer.Option("--series", help="성과 계열 식별자")],
    environment: Annotated[_Environment, typer.Option("--environment", help="개발/공식 구분")],
) -> None:
    """설정 상태·원본 입력·원장/평가 개정·계산 이력을 조회합니다."""

    def action() -> object:
        with NavStore(db) as store:
            return store.history(series, _environment(environment))

    _run(action)
