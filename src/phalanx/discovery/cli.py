"""Korean discovery commands; list and show use only the persisted snapshot."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Annotated

import typer

from phalanx.discovery.application import build_service
from phalanx.discovery.errors import DiscoveryError, DiscoveryStorageError
from phalanx.domain.discovery import DiscoveryView, Eligibility, Snapshot

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    pretty_exceptions_enable=False,
    help="공개 시장 마스터에서 독립적인 투자 후보를 발굴·조회합니다.",
)
StoreOption = Annotated[
    Path | None, typer.Option("--db", help="별도 후보 SQLite 경로 (기본: 사용자 데이터 경로)")
]


def _run(action: Callable[[], None]) -> None:
    try:
        action()
    except DiscoveryStorageError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(66) from None
    except DiscoveryError as error:
        typer.echo(f"{error.code}: {error}", err=True)
        raise typer.Exit(65) from None
    except KeyboardInterrupt:
        typer.echo("후보 수집이 중단되었습니다. 마지막 정상 스냅샷을 보존합니다.", err=True)
        raise typer.Exit(130) from None


def _summary(snapshot: Snapshot, path: Path) -> None:
    typer.echo(f"실행 {snapshot.run_id} / 수집 상태: {snapshot.status}")
    typer.echo(
        f"수집: {snapshot.collection_started_at.isoformat()} ~ "
        f"{snapshot.collection_completed_at.isoformat()}"
    )
    for market in snapshot.markets:
        counts = market.counts
        typer.echo(
            f"{market.market}: 전체 {market.total_records} / 정규화 {len(market.candidates)} / "
            f"적격 {counts['eligible']} / 제외 {counts['excluded']} / 미확인 {counts['unknown']} / "
            f"다운로드 {market.download_status} / 파싱 {market.parse_status}"
        )
        for issue in market.issues:
            typer.echo(f"  {issue.code} (행 {issue.line_number}): {issue.description}")
    typer.echo("시장 전체 완전성: 미검증 / 공급자 기준시점: 미제공 (수집 시점과 다름)")
    typer.echo(f"저장 위치: {path} (원본 ZIP·MST: source_files BLOB)")


def _view_context(view: DiscoveryView) -> None:
    if view.latest_attempt is not None:
        attempt = view.latest_attempt
        typer.echo(
            f"최근 시도: {attempt.run_id} / {attempt.started_at.isoformat()} / {attempt.status}"
        )
        if view.degraded:
            typer.echo(
                "최근 수집이 정상이 아닙니다. 저장된 이전 정상본 또는 부분 결과를 표시합니다."
            )
    if view.snapshot is None:
        typer.echo("저장된 후보 결과가 없습니다. phalanx discovery refresh가 필요합니다.")
        raise typer.Exit(1)
    typer.echo(
        f"표시 스냅샷: {view.snapshot.run_id} / "
        f"수집 완료 {view.snapshot.collection_completed_at.isoformat()} / {view.snapshot.status}"
    )
    if view.degraded and view.latest_snapshot is not None:
        for market in view.latest_snapshot.markets:
            codes = ", ".join(sorted({i.code for i in market.issues})) or "없음"
            typer.echo(
                f"최근 {market.market}: 다운로드 {market.download_status} / "
                f"파싱 {market.parse_status} / 오류 {codes}"
            )
    typer.echo("공급자 기준시점: 미제공 / 시장 전체 완전성: 미검증 / 과거 당시 유니버스 아님")


@app.command()
def refresh(db: StoreOption = None) -> None:
    """KOSPI·KOSDAQ 마스터를 수집하고 판정·원본을 함께 저장합니다."""

    def action() -> None:
        service = build_service(db)
        snapshot = service.refresh()
        _summary(snapshot, service.repository.path)
        if snapshot.status != "success":
            _view_context(service.view())
            raise typer.Exit(1)

    _run(action)


@app.command("list")
def list_candidates(
    status: Annotated[
        Eligibility | None, typer.Option(help="eligible / excluded / unknown")
    ] = None,
    db: StoreOption = None,
) -> None:
    """저장된 스냅샷에서 상태별 후보를 조회합니다 (오프라인)."""

    def action() -> None:
        service = build_service(db)
        view = service.view()
        _view_context(view)
        typer.echo("시장\t단축코드\t한글명\t판정")
        for candidate in service.list_candidates(view, status):
            record = candidate.record
            typer.echo(
                f"{record.market}\t{record.short_code or '(누락)'}\t"
                f"{record.name or '(누락)'}\t{candidate.decision.status}"
            )
        if view.degraded:
            raise typer.Exit(1)

    _run(action)


@app.command("show")
def show_candidate(short_code: str, db: StoreOption = None) -> None:
    """단축코드로 정보·원천값·판정 사유·자료 시점을 조회합니다 (오프라인)."""

    def action() -> None:
        service = build_service(db)
        view = service.view()
        _view_context(view)
        matches = service.show_candidate(view, short_code)
        if not matches:
            typer.echo("저장된 스냅샷에 해당 단축코드가 없습니다. 상장폐지를 의미하지 않습니다.")
            raise typer.Exit(1)
        assert view.snapshot is not None
        for match in matches:
            market = next(m for m in view.snapshot.markets if m.market == match.record.market)
            typer.echo(
                json.dumps(
                    {
                        "candidate": match.model_dump(mode="json"),
                        "source": market.model_dump(mode="json", exclude={"candidates"}),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        if view.degraded:
            raise typer.Exit(1)

    _run(action)
