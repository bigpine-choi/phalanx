# Phalanx

Phalanx는 한국 주식 포트폴리오 운용 프로그램입니다. 현재 첫 번째 마일스톤은 한국투자증권 실전계좌의 예수금 총액과 국내주식 잔고를 읽어 불변 JSON 스냅샷으로 저장하는 기능입니다.

## 현재 마일스톤의 안전 경계

- 한국투자증권 실전투자 환경만 지원합니다. 모의투자 URL, 모의계좌, 실전·모의 분기 로직은 구현하지 않습니다.
- 계좌 조회는 **READ ONLY**입니다. 주문·정정·취소 API와 주문용 POST 요청을 구현하지 않습니다.
- OAuth 접근토큰 발급 POST와 국내주식 잔고조회 GET만 이 마일스톤의 네트워크 범위에 포함됩니다.
- `dnca_tot_amt`는 **예수금 총액**으로만 취급합니다. 가용현금, 주문가능현금 또는 Phalanx 투자예산을 의미하지 않습니다.
- `orderable_cash`는 이번 마일스톤에서 미산정 상태입니다. 향후 매매계획 단계에서 매수가능조회 API의 `nrcvb_buy_amt`를 별도로 확인합니다.
- API 키, 앱 시크릿, 계좌번호, 접근토큰과 `runtime/` 산출물은 Git에 포함하지 않습니다.

현재 브랜치의 첫 구현 단위는 의존성·비밀정보 위생·테스트 기반만 구성합니다. KIS 인증, 잔고조회, 스냅샷 CLI는 후속 구현 단위에서 추가됩니다.

## 개발 환경

Python 3.12와 [uv](https://docs.astral.sh/uv/)를 사용합니다.

```bash
uv sync --all-groups
uv run pytest
uv run ruff check .
uv run mypy src
```

단위테스트는 합성된 KIS 실전 API 응답을 Mock으로 사용하며 `pytest-socket`으로 실제 네트워크를 차단합니다. 자동 테스트와 CI에서는 실제 한국투자증권 API를 호출하지 않습니다.

## 로컬 자격증명

`.env.example`을 `.env`로 복사한 뒤 본인의 실전투자 자격증명을 로컬에서만 입력합니다.

```bash
cp .env.example .env
git check-ignore .env
```

필요한 변수는 다음 세 가지입니다.

- `PHALANX_KIS_APP_KEY`
- `PHALANX_KIS_APP_SECRET`
- `PHALANX_KIS_ACCOUNT_NUMBER` (`8자리-2자리`)

`.env`가 `git check-ignore`에서 제외 대상으로 확인되지 않으면 실행하지 말고 `.gitignore`를 먼저 점검합니다. 실제 값을 문서, 테스트 fixture, 커밋 메시지 또는 터미널 캡처에 기록하지 않습니다.

## CLI 계약

후속 구현이 완료되면 기본 명령만으로 즉시 실전계좌 read-only 스냅샷을 수행합니다.

```bash
uv run phalanx
```

다음 명시적 별칭도 같은 동작을 제공합니다.

```bash
uv run phalanx account snapshot
```

CLI에는 환경 선택 옵션이 없으며 모의투자 모드도 제공하지 않습니다.

## 실제 계좌 read-only 스모크 테스트 절차

이 절차는 KIS 인증·잔고조회 구현이 완료된 뒤 개발자가 로컬에서 명시적으로 수행하는 수동 검증입니다. 자동화 테스트나 CI 절차에 추가하지 않습니다.

1. KIS Developers에서 발급한 실전투자 앱 키·앱 시크릿과 실전계좌 번호를 로컬 `.env`에 설정합니다.
2. `git check-ignore .env runtime/`로 비밀정보와 실행 산출물이 Git 제외 대상인지 확인합니다.
3. 작업 트리에 실제 비밀정보가 없는지 확인합니다. 비밀값 자체를 검색 명령 인자로 넘기거나 출력하지 않습니다.
4. `uv run phalanx`를 한 번 실행합니다.
5. 터미널에 `실전계좌 · READ ONLY` 표시, 마스킹된 계좌번호, 예수금 총액, 주식평가액, 총자산, 종목별 잔고가 출력되는지 확인합니다.
6. 주문가능현금은 `미산정`으로 표시되고 예수금 총액이 그 값으로 복사되지 않았는지 확인합니다.
7. `runtime/snapshots/`에 JSON 한 개가 생성되고 원본 계좌번호·앱 키·앱 시크릿·접근토큰이 포함되지 않았는지 확인합니다.
8. 연속조회 대상 계좌라면 HTS의 보유종목 수와 스냅샷의 실제 보유종목 수를 비교합니다. 보유수량 0인 잔고는 별도 목록인지 확인합니다.
9. 실행 전후 미체결·체결 내역에 변화가 없음을 확인합니다. 이 절차에서는 주문·정정·취소 호출을 절대 수행하지 않습니다.

상세 구현 계획은 [`docs/plans/kis-account-snapshot.md`](docs/plans/kis-account-snapshot.md)에 있습니다.
