# Phalanx

Phalanx는 한국 주식 포트폴리오 운용 프로그램입니다. 한국투자증권 실전계좌의 예수금 총액과 국내주식 잔고를 읽어 불변 JSON 스냅샷으로 저장하고, 사람이 직접 관리하는 로컬 투자 후보 유니버스, KIS 국내주식 일별 시세 조회, 공통 거래일 수익률 행렬, 과거 유니버스 HTML 리포트, 재현 가능한 자산배분 연구 harness, 동적 위험모형, Constrained ERC 및 별도 volatility-target/cash-residual 연구 계층을 제공합니다.

## 현재 마일스톤의 안전 경계

- 한국투자증권 실전투자 환경만 지원합니다. 모의투자 URL, 모의계좌, 실전·모의 분기 로직은 구현하지 않습니다.
- 계좌와 시세 조회는 **READ ONLY**입니다. 주문·정정·취소 API와 주문용 POST 요청을 구현하지 않습니다.
- OAuth 접근토큰 발급 POST, 국내주식 잔고조회 GET, 국내주식 일별 시세조회 GET과 현재가 조회 GET만 이 마일스톤의 네트워크 범위에 포함됩니다.
- `dnca_tot_amt`는 **예수금 총액**으로만 취급합니다. 가용현금, 주문가능현금 또는 Phalanx 투자예산을 의미하지 않습니다.
- `orderable_cash`는 이번 마일스톤에서 제공되지 않아 `None`/`null`로 유지하고 터미널에는 `미제공`으로 표시합니다. 향후 매매계획 단계에서 매수가능조회 API의 `nrcvb_buy_amt`를 별도로 확인합니다.
- API 키, 앱 시크릿, 계좌번호와 접근토큰은 Git에 포함하지 않습니다. `runtime/` 제외 규칙은 방어 목적으로 유지합니다.

현재 브랜치는 외부 자격증명, OAuth 토큰 캐시, 국내주식 잔고 파싱·연속조회, 불변 스냅샷 저장, 로컬 투자 후보 관리, 수정주가 기준 일별 OHLCV 조회, 공통 거래일 단순수익률 계산, self-contained 과거 성과 리포트, 조건부 자산배분 연구 harness, 네 개의 독립 공분산 시나리오, 각 시나리오의 Constrained ERC와 별도 deterministic volatility overlay 연구까지 구성합니다. 실제 자격증명과 실제 KIS API는 자동 테스트에서 사용하지 않습니다.

정규화된 원장·일별 평가자료를 입력받는 `phalanx nav`는 일별 NAV·기준가·수익률·MDD와 KOSPI Total Return 비교를 SQLite에 보존하고 누락 자료·과거 정정 이후를 복원합니다. 공식 설정일은 사용자가 직접 지정하며 개발 데이터와 분리합니다. [일별 NAV 사용법과 합성 예시](docs/daily-nav.md)를 참고하세요. KIS 과거 체결·권리·입출금 자동 수집과 HTS 엑셀 변환은 아직 구현하지 않았습니다.

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

실제 KIS 자격증명은 저장소 외부의 다음 파일에만 저장합니다.

```text
~/.config/phalanx/credentials.env
```

프로젝트 루트의 `.env` 파일은 저장하거나 읽지 않습니다. `.env.example`은 필요한 변수명과 설명을 확인하기 위한 템플릿일 뿐이며 실제 값을 입력하거나 루트 `.env`로 복사하지 않습니다.

자격증명 파일이 아직 없을 때만 다음 명령으로 저장소 외부에 안전하게 준비합니다. 두 번째 명령은 기존 파일을 덮어쓸 수 있으므로 이미 만든 자격증명 파일에는 다시 실행하지 않습니다.

```bash
install -d -m 700 "$HOME/.config/phalanx"
install -m 600 .env.example "$HOME/.config/phalanx/credentials.env"
stat -c '%a %n' ~/.config/phalanx ~/.config/phalanx/credentials.env
```

`install`은 디렉터리와 파일을 처음부터 각각 `0700`, `0600` 권한으로 만듭니다. 마지막 명령으로 권한을 확인한 뒤 사용자가 저장소 외부의 `credentials.env`를 직접 편집합니다.

필요한 변수는 다음 세 가지입니다.

- `PHALANX_KIS_APP_KEY`
- `PHALANX_KIS_APP_SECRET`
- `PHALANX_KIS_ACCOUNT_NUMBER` (`8자리-2자리`)

프로그램은 이 파일이 없거나, 일반 파일이 아니거나, 심볼릭 링크이거나, 현재 사용자의 소유가 아니거나, 권한이 정확히 `0600`이 아니면 파일을 생성·수정하지 않고 안전한 설정 방법만 안내한 뒤 실패합니다. 상위 디렉터리도 현재 사용자 소유와 정확한 `0700` 권한을 요구합니다.

실제 값을 프로젝트 루트, 문서, 테스트 fixture, 커밋 메시지 또는 터미널 캡처에 기록하지 않습니다.

## OAuth 토큰 캐시

KIS 접근토큰 캐시의 기본 운영 위치도 저장소 외부로 고정합니다.

```text
~/.cache/phalanx/token-cache/kis-access-token.json
```

프로그램은 `~/.cache/phalanx`와 그 아래 `token-cache`를 필요할 때 생성하며 두 디렉터리를 생성 순간부터 `0700`으로 보호합니다. 기존 `~/.cache`의 권한은 변경하지 않습니다. 캐시 JSON, 잠금 파일과 원자 교체용 임시파일은 생성 순간부터 `0600`입니다.

두 application-owned 디렉터리가 심볼릭 링크이거나, 현재 사용자 소유가 아니거나, 권한이 정확히 `0700`이 아니면 자동 복구나 `chmod` 없이 실패합니다. 현재 작업 디렉터리, 프로젝트의 `runtime/token-cache`, `.env`, `XDG_CACHE_HOME`을 기본 캐시 위치로 사용하지 않습니다. `runtime/` Git 제외 규칙은 방어 목적으로 유지합니다.

## 스냅샷 저장 위치

완성된 계좌 스냅샷의 기본 운영 위치는 저장소 외부로 고정합니다.

```text
~/.local/share/phalanx/snapshots/
```

경로는 실행 시점의 `Path.home()`을 기준으로 결정하며 현재 작업 디렉터리와 `XDG_DATA_HOME`을 사용하지 않습니다. 기존 `~/.local/share`의 권한은 변경하지 않고, 프로그램이 관리하는 `phalanx`와 `snapshots` 디렉터리는 생성·검증 시 각각 정확한 `0700`을 요구합니다. 최종 JSON과 원자 저장용 임시파일은 생성 순간부터 `0600`입니다. 저장소 내부 `runtime/`은 production 저장 위치로 사용하지 않습니다.

스냅샷 JSON 안의 timezone-aware 절대시각은 변환하지 않고 보존합니다. 사용자가 보는 파일명에는 조회 완료시각을 한국시간으로 변환한 `+0900`을 사용합니다.

## 계좌·시세 통합 현황 v1

계좌와 보유종목의 KRX 현재가를 한 번에 조회하고, 보유수량·증권사 평가액·조회 현재가 기준 평가액·보유주식 내 비중을 표시합니다. 종목코드나 파일 경로를 입력할 필요가 없습니다.

```bash
uv run phalanx account overview
```

한 계좌 조회가 끝나면 양수 수량의 보유종목을 원래 순서대로 추출하고 모든 종목의 현재가를 조회합니다. 기존 OAuth 관리자와 하나의 HTTP client, 현재가 서비스와 호출 간격 제어를 사용합니다. 0수량 잔고는 시세 조회에서 제외하고 원본 스냅샷에 보존합니다. 보유종목이 없으면 현재가 조회를 생략하고 빈 종목 목록과 주식평가액 0을 저장합니다. 지원하지 않는 종목코드가 하나라도 있으면 일부 종목을 제외해서 계산하지 않고 전체 통합 조회를 중단합니다.

완성된 결과는 저장소 외부의 다음 위치에 **자동 저장**됩니다.

```text
~/.local/share/phalanx/account-overviews/account_overview_<KST 관측시각>_<임의 식별자>.json
```

기존 private 디렉터리 검증·원자 JSON 저장 기능을 재사용하며 새 디렉터리는 `0700`, 결과 파일은 `0600`입니다. 같은 시각의 재조회도 새 파일을 만들며 기존 파일을 덮어쓰지 않습니다. 경로는 실행 시점의 `Path.home()`을 기준으로 정합니다. 현재 저장 어댑터의 지원 환경은 Linux/WSL입니다.

### 평가 기준과 해석

- **증권사 순자산·예수금·주식평가액**은 계좌 조회 응답 그대로입니다. 주문가능현금은 여전히 `미제공`이며 예수금을 매수가능금액으로 사용하지 않습니다.
- **조회 현재가 기준 보유주식 평가액**은 계좌 조회 당시 각 보유수량에 이후 조회한 가격을 곱한 합계입니다. 이 합계로 계좌 순자산을 대체하지 않습니다. 조회 사이에 발생한 거래로 보유수량이 바뀌었는지 확인하는 기능은 없습니다.
- **주식 내 비중**의 분모는 위 현재가 기준 보유주식 평가액 합계입니다. 현금·부채·기타자산은 포함하지 않으며 계좌 NAV 대비 비중을 뜻하지 않습니다. 화면은 소수점 둘째 자리의 백분율로 표시하고 JSON은 계산한 Decimal 값을 보존합니다.
- **평가기준 간 차이**는 현재가 평가합계에서 증권사 보유행 평가합계를 뺀 값입니다. 매매손익이나 기간 운용성과가 아닙니다. 증권사 주식 요약과 개별 보유행 합계가 다르면 그 차이도 별도로 표시합니다.
- 역산 기타자산·결제조정 및 부채·차감액은 공통 계산 함수에서 계산해 JSON에 남깁니다. 기존 스냅샷 CLI도 이 함수를 재사용합니다.
- 금액·비중은 고정된 50자리 Decimal context와 `ROUND_HALF_EVEN`으로 계산합니다. 보유종목이 없을 때 비중을 만들지 않습니다. 비정상적인 계산 범위는 오류로 처리합니다.

계좌 조회 시작부터 마지막 현재가 응답까지 **전체 관측 구간**의 기본 상한은 60초입니다. 아래 옵션으로 변경할 수 있습니다.

```bash
uv run phalanx account overview --max-observation-span-seconds 120
```

양의 정수 초만 허용하며 입력은 자격증명·네트워크 접근 전에 검사합니다. 상한과 정확히 같은 구간은 허용합니다. 검사는 조회 완료 후 수행하므로 이 옵션은 HTTP 요청을 강제로 취소하는 제한시간이 아닙니다. 요청 간격·재시도·인증 대기도 관측 구간에 포함될 수 있습니다. 관측시각은 실제 체결시각이나 확정 종가시각이 아니며 최근 조회만으로 가격의 최신성이나 체결 가능성을 보장하지 않습니다.

조회 중 계좌 요약 변경, 일부 종목 조회 실패, 종목·시장·관측시각 불일치, 전체 관측 구간 초과 또는 계산 실패 시 완성된 통합 결과 표나 결과 JSON을 만들지 않습니다. 조회 진행 안내는 표시할 수 있습니다. 저장 오류도 성공으로 처리하지 않습니다. 연결정보와 토큰 캐시는 기존 조회 기능과 동일하게 사용됩니다.

### GUI용 공통 결과와 이력

`AccountOverviewApplication.run()`은 화면 출력 없이 `AccountOverviewResult(overview, saved_path)`를 반환합니다. 잔고 조회기·현재가 서비스·저장소를 교체할 수 있고, 진행 콜백으로 계좌 조회·시세 조회·저장 단계를 전달합니다. GUI는 이 서비스를 호출하고 결과를 표시할 수 있으며 별도의 계산식을 작성할 필요가 없습니다.

통합 JSON은 `schema_version: "1"`, `report_type: "account_overview"`를 사용합니다. `snapshot`에 기존 스키마의 완전한 계좌 스냅샷을 포함하고, `positions`에 가격 입력·각 종목의 요청/응답 관측시각·평가액·비중을, `totals`에 합계와 평가 차이를 보존합니다. 평가 분모·Decimal 설정·전체 관측 구간도 명시합니다. 동일한 관측 입력은 동일한 JSON 바이트를 만들며 임의 식별자는 파일명에만 사용합니다. `AccountOverview.model_validate_json()`으로 저장 결과를 다시 읽을 수 있습니다.

기존 스냅샷·성과·연구 JSON 스키마는 변경하지 않습니다. 통합 JSON은 일반 스냅샷 파일과 다른 보고서 형식이므로 `account performance`의 스냅샷 인수에 직접 지정하지 않습니다. 기존 기간 성과 입력용 독립 스냅샷은 계속 `account snapshot`으로 저장합니다. 통합 조회는 별도 스냅샷 파일까지 동시에 저장하지 않고, 모든 결과와 원본 스냅샷을 한 JSON에 보존합니다. 목표비중·정수주 매매계획과 GUI 화면은 후속 단계입니다.

CLI 옵션 오류는 종료 코드 `2`, 설정 `10`, 인증 `20`, 계좌 조회 `30`, 시세 조회 `60`, 통합 검증·계산 `65`, 저장 `66`, 예기치 않은 오류 `70`, 사용자 중단 `130`입니다. 개별 현재가 조회 중 인증 실패는 기존 현재가 서비스의 종목 조회 실패(`60`)로 보고됩니다. 실제 네트워크를 차단한 합성 테스트로 조회·계산·저장과 CLI를 검증합니다.

## 실계좌 전체 기간 운용성과 v1 (오프라인)

저장된 `AccountSnapshot` 두 개와 사용자가 제공한 외부 입출금 원장으로 **실계좌 전체**의 기간 운용손익과 **Modified Dietz 기간 추정 수익률**을 계산합니다. Phalanx 알고리즘만의 성과를 뜻하지 않습니다. 이 명령은 지정된 세 입력 파일만 읽으며 KIS API, 현재가 번들, 자격증명 파일, 토큰 캐시를 사용하지 않습니다. 스냅샷 폴더를 자동 탐색하거나 순자산을 다시 평가하지 않습니다.

```bash
uv run phalanx account performance \
  --start-snapshot <시작-스냅샷.json> \
  --end-snapshot <종료-스냅샷.json> \
  --cash-flows <외부-입출금.json> \
  --output <새-결과.json>
```

`--cash-flows`는 필수이며 생략을 입출금 0으로 해석하지 않습니다. `--output`은 선택사항입니다. 결과 파일은 기존 private JSON 저장 기능으로 원자적으로 생성하며 파일·잠금 파일은 `0600`, 새 결과 디렉터리는 `0700`입니다. 기존 결과나 입력 파일을 덮어쓰지 않습니다. 출력 JSON에는 스키마 버전 `"1"`, 방법명 `modified_dietz`, 범위 `whole_account`, 세 입력 파일 **원본 바이트의 SHA-256**, 관측·조회시각, 순자산, 원장 선언·기간, 개별 입출금의 시간 가중치와 가중 금액, 공식, Decimal context, 미산출 사유를 기록합니다. 금액·수익률은 십진 문자열이고 미산출 수익률은 `null`입니다. 실행시각·임의 ID·입력 경로를 넣지 않아 같은 세 입력 바이트는 같은 결과 JSON 바이트를 만듭니다. 공백 등 입력 파일 내용이 바뀌면 SHA-256도 바뀝니다. 원본 계좌번호나 자격증명은 결과에 포함하지 않습니다.

계산은 아래 정의를 사용합니다. `B`, `E`는 각각 시작·종료 `snapshot.summary.net_assets`이며 `t0`, `t1`은 각 `query_completed_at`입니다.

```text
외부 입금 CF > 0, 외부 출금 CF < 0
기간 운용손익 = E - B - sum(CF_i)
w_i = (t1 - occurred_at_i) / (t1 - t0)
평균투하자본 D = B + sum(w_i * CF_i)
Modified Dietz 기간 추정 수익률 = 기간 운용손익 / D
```

고정된 local Decimal context (`prec=50`, `ROUND_HALF_EVEN`)에서 계산하고, 시간 차이는 UTC 정수 마이크로초로 계산하여 `float`를 거치지 않습니다. 계산 도중 금액이나 수익률을 표시 자릿수로 반올림하지 않으며 터미널에서만 금액 소수 2자리·수익률 퍼센트 소수 6자리로 표시합니다. 순입출금이 같아도 입출금 발생시각별 가중치가 다르므로 서로 다른 거래를 순액으로 상계하지 않습니다. 총출금은 양의 절댓값으로 표시합니다. 기초 순자산 `B <= 0` 또는 평균투하자본 `D <= 0`이면 수익률은 미산출이며 각각의 사유와 유효한 기간 운용손익을 별도로 표시합니다.

**조회 완료시각은 계산용 관측시각**이며 실제 거래소 평가시각이나 확정 종가시각으로 단정하지 않습니다. 위 수익률은 이 관측시각으로 시간 가중치를 계산한 추정치입니다. 정확한 TWR, 기준가 시계열, 연환산수익률, MDD, 벤치마크 비교는 v1 범위에 포함하지 않습니다.

원장은 다음 조건을 모두 만족해야 합니다.

- `schema_version`은 문자열 `"1"`이며 `coverage_start`, `coverage_end`는 두 관측시각과 같은 절대시각이어야 합니다. 다른 timezone 표기로 같은 시각을 나타내도 됩니다.
- `same_account_confirmed`, `external_flows_complete`, `no_in_kind_transfers`는 사용자가 확인한 JSON boolean `true`여야 합니다. 문자열 `"true"`, 숫자 `1`, 누락 또는 `false`는 거부합니다. 프로그램이 실제 원장을 대신 작성하거나 이 선언들을 자동 확인하지 않습니다.
- `events`는 필수 목록이며, `event_id`는 양끝 공백을 제거한 뒤 비어 있지 않은 고유 식별자, `occurred_at`은 timezone-aware ISO 8601 시각, `amount`는 0이 아닌 유한한 십진 문자열입니다. 예: `"+100"`, `"100.25"`, `"-40"`. JSON 숫자, 지수 표기, NaN, Infinity, 중복 JSON 키와 지원하지 않는 필드는 거부합니다. 다른 ID를 가진 여러 거래가 같은 시각에 발생하는 것은 허용합니다.
- 입출금은 두 관측시각 사이에 있어야 합니다. **어느 스냅샷이든 조회 시작부터 완료까지의 닫힌 구간(양쪽 경계 포함)**에 발생한 입출금은 NAV 반영 여부가 모호하여 거부합니다.
- 두 스냅샷은 기존 `AccountSnapshot` 스키마를 통과하고 provider·currency·마스킹 계좌번호가 일치해야 합니다. 마스킹 계좌번호 일치만으로 동일계좌가 입증되지 않으므로 원장의 동일계좌 선언도 필수입니다. 조회 순서가 잘못되거나 두 조회구간이 겹치거나 경계에서 접하면 거부합니다. 어느 스냅샷에든 `summary_consistency_warnings`가 있으면 거부합니다.

매매대금, 계좌 안에서 받은 배당·이자, 수수료·세금은 외부 입출금으로 기록하지 않습니다. NAV에 이미 반영된 비용을 다시 차감하지 않습니다. 현금배당 수령 후 외부로 출금했다면 **그 출금만** 외부 CF입니다. 현물 입출고가 있는 기간은 v1 미지원입니다. 원장 완전성은 사용자 데이터 선언이며 프로그램이 거래 내역과 대조해 입증하지 않습니다.

### 완전한 합성 입력 예시

아래 세 파일은 실제 계좌·API 응답이 아닌 합성 데이터이며 저장소의 `tests/fixtures/account_performance/`에도 동일한 입력이 있습니다. `0000****-**`, 응답 해시와 성공 메시지도 합성 값입니다. 실제 사용 시 아래 선언을 그대로 복사하여 사실 확인을 대신하지 마세요.

시작 `start.json`:

```json
{
  "schema_version": "1",
  "provider": "korea_investment_securities",
  "currency": "KRW",
  "account_number_masked": "0000****-**",
  "query_started_at": "2026-08-01T08:59:59+09:00",
  "query_completed_at": "2026-08-01T09:00:00+09:00",
  "summary": {
    "deposit_total": "100",
    "orderable_cash": null,
    "securities_evaluation_amount": "0",
    "purchase_amount_total": "0",
    "evaluation_amount_total": "0",
    "profit_loss_total": "0",
    "total_assets": "100",
    "net_assets": "100"
  },
  "positions": [],
  "zero_quantity_balances": [],
  "evidence": {
    "pages": [
      {
        "page_number": 1,
        "received_at": "2026-08-01T09:00:00+09:00",
        "http_status": 200,
        "tr_cont": "",
        "ctx_area_fk100": "",
        "ctx_area_nk100": "",
        "rt_cd": "0",
        "msg_cd": "SYNTHETIC",
        "msg1": "Synthetic example only; not an API response",
        "response_body_sha256": "0000000000000000000000000000000000000000000000000000000000000000",
        "output1": [],
        "output2": [],
        "placeholder_rows": []
      }
    ],
    "summary_consistency_warnings": []
  }
}
```

종료 `end.json`:

```json
{
  "schema_version": "1",
  "provider": "korea_investment_securities",
  "currency": "KRW",
  "account_number_masked": "0000****-**",
  "query_started_at": "2026-08-11T08:59:59+09:00",
  "query_completed_at": "2026-08-11T09:00:00+09:00",
  "summary": {
    "deposit_total": "220",
    "orderable_cash": null,
    "securities_evaluation_amount": "0",
    "purchase_amount_total": "0",
    "evaluation_amount_total": "0",
    "profit_loss_total": "0",
    "total_assets": "220",
    "net_assets": "220"
  },
  "positions": [],
  "zero_quantity_balances": [],
  "evidence": {
    "pages": [
      {
        "page_number": 1,
        "received_at": "2026-08-11T09:00:00+09:00",
        "http_status": 200,
        "tr_cont": "",
        "ctx_area_fk100": "",
        "ctx_area_nk100": "",
        "rt_cd": "0",
        "msg_cd": "SYNTHETIC",
        "msg1": "Synthetic example only; not an API response",
        "response_body_sha256": "0000000000000000000000000000000000000000000000000000000000000000",
        "output1": [],
        "output2": [],
        "placeholder_rows": []
      }
    ],
    "summary_consistency_warnings": []
  }
}
```

기간 정중앙 입금 `cash-flows.json`:

```json
{
  "schema_version": "1",
  "coverage_start": "2026-08-01T09:00:00+09:00",
  "coverage_end": "2026-08-11T09:00:00+09:00",
  "same_account_confirmed": true,
  "external_flows_complete": true,
  "no_in_kind_transfers": true,
  "events": [
    {
      "event_id": "synthetic-deposit-1",
      "occurred_at": "2026-08-06T09:00:00+09:00",
      "amount": "+100"
    }
  ]
}
```

명시적 무입출금 원장은 같은 합성 관측기간에 대해 다음과 같이 **전체 필수 필드와 빈 목록**을 제공합니다.

```json
{
  "schema_version": "1",
  "coverage_start": "2026-08-01T09:00:00+09:00",
  "coverage_end": "2026-08-11T09:00:00+09:00",
  "same_account_confirmed": true,
  "external_flows_complete": true,
  "no_in_kind_transfers": true,
  "events": []
}
```

저장소 루트에서 중간 입금 합성 사례를 실행하려면 다음을 사용합니다. 출력 위치를 매번 새 임시 디렉터리로 지정합니다.

```bash
performance_demo_dir=$(mktemp -d)
uv run phalanx account performance \
  --start-snapshot tests/fixtures/account_performance/start.json \
  --end-snapshot tests/fixtures/account_performance/end.json \
  --cash-flows tests/fixtures/account_performance/cash-flows.json \
  --output "$performance_demo_dir/performance.json"
```

기대값은 기초 100원, 기말 220원, 총입금 100원, 총출금 0원, 순입출금 100원, 기간 운용손익 20원, 평균투하자본 150원, 기간 추정 수익률 `13.333333%`입니다.

### 실제 저장 파일을 연결하는 순서

1. 기존 `~/.local/share/phalanx/snapshots/`에서 비교할 **같은 계좌의 저장된 두 파일을 직접 선택**합니다. 각 `query_started_at`, `query_completed_at`, `summary.net_assets` 및 일관성 경고를 확인합니다. 기존 스냅샷을 고치지 않습니다.
2. 거래 기록과 대조해 분석기간의 외부 현금 입출금만 사용자 원장에 기록합니다. 원장 기간을 두 `query_completed_at`과 맞추고, 동일계좌·외부 입출금 완전성·현물 입출고 없음이 실제로 확인된 경우에만 세 선언을 `true`로 명시합니다. 조회 중 입출금이 있거나 조회구간이 겹치면 다른 유효한 스냅샷 쌍을 선택해야 합니다.
3. 원장을 저장소 밖 개인 데이터 위치에 보관하고 세 파일을 `--start-snapshot`, `--end-snapshot`, `--cash-flows`로 명시합니다. 결과를 저장하려면 `--output`에 아직 없는 파일명을 지정합니다. 원장이나 결과를 Git에 추가하지 않습니다.
4. 터미널의 관측시각·순자산·입출금·손익·추정 수익률 또는 미산출 사유를 확인합니다. 저장한 결과의 입력 SHA-256과 가중치·계산 근거를 함께 보관합니다.

CLI 필수 옵션 누락은 종료 코드 `2`, 입력·계산 오류는 기존 분석 오류와 같은 `65`, 결과 저장 실패·기존 파일 충돌은 `66`, 예기치 않은 오류는 `70`, 사용자 중단은 `130`입니다. 유효한 입력에서 수익률만 미산출되는 경우는 손익 결과를 제공하므로 성공(`0`)입니다.

## 투자 후보 유니버스

투자 후보 유니버스는 사용자가 직접 등록한 한국 주식의 종목코드, 종목명, 시장, 활성화 여부와 선택적 메모를 로컬 JSON 파일에 저장합니다. 유니버스 등록·활성화·비활성화 자체는 KIS API나 다른 네트워크에 접속하지 않습니다. 별도의 `market-data universe` 명령만 활성 종목을 읽어 시세를 조회하며, 최적화나 주문은 수행하지 않습니다. 계좌 스냅샷의 **READ ONLY** 경계에도 영향을 주지 않습니다.

현재 MVP의 로컬 유니버스 저장소는 POSIX 파일 권한과 디렉터리 파일 디스크립터를 사용하는 **Linux와 WSL만 지원**합니다. 기본 저장 위치는 다음과 같습니다.

```text
~/.local/share/phalanx/universe.json
```

저장 디렉터리와 JSON/잠금 파일은 각각 `0700`, `0600` 권한으로 보호합니다. 저장은 같은 디렉터리의 private 임시파일을 디스크에 동기화한 뒤 원자 교체하므로 쓰기 실패 시 기존 파일을 보존합니다. 손상되거나 지원하지 않는 JSON은 자동 초기화하거나 덮어쓰지 않고 명확한 오류로 보고합니다.

macOS와 네이티브 Windows에서는 이 저장소를 시작하지 않고 미지원 플랫폼 오류를 반환합니다. 네이티브 Windows 지원은 향후 GUI·패키징 단계에서 운영체제에 맞는 별도 저장소 구현으로 제공합니다.

종목은 등록 시 기본적으로 활성화됩니다. 종목코드는 공백 없는 6자리 숫자이고 시장은 `KOSPI` 또는 `KOSDAQ`이어야 합니다.

```bash
uv run phalanx universe add 005930 삼성전자 --market KOSPI --note "반도체 대형주"
uv run phalanx universe add 035720 카카오 --market KOSPI
uv run phalanx universe list
uv run phalanx universe disable 035720
uv run phalanx universe enable 035720
uv run phalanx universe remove 035720
```

종목코드와 실제 상장 시장의 일치 여부를 네트워크로 조회하거나 검증하지 않으므로 사용자가 올바른 값을 입력해야 합니다. CLI는 저장소를 직접 다루지 않고 유니버스 서비스 계층을 호출합니다. 향후 GUI도 같은 서비스 계층을 사용할 수 있습니다.

## 시장 후보 자동 발굴

KOSPI·KOSDAQ 공개 종목 마스터에서 후보를 자동 수집하고 `eligible`(적격),
`excluded`(제외), `unknown`(미확인)으로 판정합니다. 계좌 설정이나 OAuth 토큰은
필요하지 않으며 수동 유니버스·계좌 자료·NAV 이력을 변경하지 않습니다.

```bash
uv run phalanx discovery refresh
uv run phalanx discovery list --status eligible
uv run phalanx discovery list --status unknown
uv run phalanx discovery show 005930
```

`refresh`는 두 시장의 전체·정규화·적격·제외·미확인 건수와 처리 상태를 표시합니다.
`list`와 `show`는 저장된 결과만 읽으며 네트워크에 접속하지 않습니다.
기본 저장 위치는 `~/.local/share/phalanx/discovery/discovery.sqlite3`이고,
각 명령의 `--db` 옵션으로 별도 경로를 지정할 수 있습니다. 원본 ZIP·MST 바이트와
SHA-256, 시장별 수집 상태·시각, 스키마·파서·정책 버전, 원천값과 판정 사유를 보존합니다.

현재 정책 `domestic-common-stock-v2`는 공식 증권그룹을 1차 분류 근거로 사용합니다.
ST 주권의 ETP 공백은 원시 공백·정규화 `null`로 보존하며, ST 분류를 비ETP의 독립
근거로 기록합니다. 명시적 ETP·미지원 비공백 코드·분류 충돌은 계속 판정에 반영합니다.
우선주·SPAC·거래정지·정리매매·관리종목 제외와 다른 필수값 누락 시 미확인 규칙은
유지합니다. 이전 v1 스냅샷은 조회 시 재판정하거나 덮어쓰지 않습니다. 다른 경고 정보는
보존하며 숫자 필터는 추가하지 않습니다. 최종 투자정책이나 과거 당시 유니버스가 아닙니다.

부분·실패 수집은 종료코드 `1`, 저장 오류는 `66`입니다. 새 수집 실패 시 마지막 정상본을
보존하고, 이전 결과 조회에는 수집 시점과 최근 실패를 함께 표시합니다. 파일 처리 성공이
시장 전체의 무누락을 보장하지 않으며, 공급자 전체 기준시점은 미확인으로 남깁니다.
공식 자료의 고정 커밋, 정책, 한계와 실제 수집 검증은
[시장 후보 발굴 문서](docs/market-candidate-discovery.md)에 설명되어 있습니다.

## 시장 후보 일봉 저장·재개 v1

성공한 discovery 실행의 적격 후보를 고정하고, KIS 수정주가 OHLCV를 별도 SQLite에 저장합니다. `create`, `status`, `show`는 오프라인이고 `run`만 기존 KIS 자격증명·OAuth를 사용합니다.

```bash
uv run phalanx market-data history create \
  --discovery-run-id RUN_ID --start 2026-01-01 --end 2026-09-11 \
  --code 005930 --code 0001A0
uv run phalanx market-data history run JOB_ID --max-symbols 1
uv run phalanx market-data history run JOB_ID
uv run phalanx market-data history status JOB_ID
uv run phalanx market-data history show JOB_ID 0001A0
```

반복 `--code` 또는 `--all-eligible` 중 하나를 명시해야 하며 종료일은 서울 기준 오늘 이전이어야 합니다. 완료 종목은 건너뛰고 실패 종목은 `--retry-failed`로만 재시도합니다. 종목 하나의 전체 요청 기간과 완료 상태를 원자적으로 저장하며, 기간 변경·재수집은 새 작업으로 수행합니다. discovery 갱신은 기존 작업의 대상을 바꾸지 않습니다.

기본 DB는 `~/.local/share/phalanx/market-data/history.sqlite3`입니다. 생성 시 `--discovery-db`와 `--history-db`, 실행·조회 시 `--history-db`로 경로를 지정할 수 있습니다. 일봉은 정확한 ASCII 숫자·대문자 6자리 코드를 보존하지만 공급자의 실제 조회 지원은 별도로 확인해야 합니다. 현재가·계좌 평가와 수동 유니버스의 숫자 전용 계약은 유지합니다.

정상 빈 응답·실패·미처리를 구분하고 거래일 무누락을 보장하지 않습니다. 현재 후보는 과거 당시 유니버스가 아니며 수정주가 이력은 배당 포함 총수익률이 아닙니다. 수동 유니버스·계좌·NAV에 자동 반영하지 않습니다. [저장 계약·재개·공식 출처·읽기 인터페이스](docs/candidate-price-history.md)를 참고하세요.

## 후보 종목 가격 특성값 v1

저장된 history 작업에서 기준일 이하의 수정주가 종가로 후보별 가격수익률·연율화 변동성·최대낙폭을 오프라인 계산합니다. 자격증명·OAuth·HTTP를 사용하지 않으며, 종목마다 관측일과 이력 길이를 독립적으로 처리합니다.

```bash
uv run phalanx market-data features calculate JOB_ID \
  --as-of 2026-08-31 --code 005930 --code 0001A0
uv run phalanx market-data features calculate JOB_ID \
  --as-of 2026-08-31 --all-targets \
  --history-db /absolute/private/history.sqlite3 \
  --output /absolute/private/features-2026-08-31.json
```

`--as-of`는 작업의 요청 기간 안에 있어야 하며 `--code` 또는 `--all-targets` 중 하나를 명시합니다. N구간 지표에는 N+1개의 관측 종가가 필요합니다. 자료가 부족한 지표는 사유와 함께 `null`로 남기고 계산 가능한 지표는 유지합니다. 모든 선택 종목의 지표가 계산되면 종료 코드 `0`, 일부라도 계산 불가이면 JSON을 출력·저장한 뒤 `2`입니다. 기존 출력 파일은 덮어쓰지 않습니다.

결과는 정확한 십진 문자열과 원천·소비 입력 해시, 계산 정책, 실제 사용 기간을 포함합니다. 거래일 무누락과 과거 시점 정보만 사용한 백테스트를 보장하지 않으며 가격수익률은 배당 포함 총수익률이 아닙니다. 종목 순위·매매 판단·비중 계산은 포함하지 않습니다. [계산식·입력 해시·부분 결과·종료 코드](docs/candidate-price-features.md)를 참고하세요.

## 후보 평가·선정 v1

기존 features JSON에서 명시한 단일 지표로 후보를 비교하고 최대 top개를 선정하는 오프라인 연구용 기준 선정기입니다. 원천 DB·discovery·자격증명·네트워크를 다시 조회하지 않습니다.

```bash
uv run phalanx candidates select \
  --features /absolute/private/features.json \
  --metric return_60 --top 10 --max-age-days 7 \
  --output /absolute/private/selection.json
```

네 입력 옵션은 모두 필수이며 10·7은 기본값이나 검증된 투자 파라미터가 아닙니다. 수익률·최대낙폭은 큰 값, 변동성은 작은 값을 우선합니다. 입력의 최신 완료 가격 종점과 같은 종점·허용 가격 경과일·선택 지표 계산 가능 조건을 충족해야 순위에 참여합니다. 최신 종목의 이력이 부족해도 과거 종점 집단으로 후퇴하지 않습니다.

동점은 코드 ASCII 순서로 결정하며 경쟁 순위와 최종 순번을 따로 보존합니다. 모든 후보를 selected/not_selected/unavailable로 남기고 selected_codes를 선정 순서대로 제공합니다. 부분 결과도 JSON으로 출력·저장하며 기존 파일은 덮어쓰지 않습니다. 완전 결과는 종료 코드 0, 부분 결과는 2입니다. 비중·주문·자동 유니버스 반영과 수익성 검증은 포함하지 않습니다. [정책·입력 검증·부분 결과·해석 한계](docs/candidate-selection.md)와 [합성 예제](examples/candidate-selection/README.md)를 참고하세요.

## 선정 결과 → 배분 입력 v1

선정 JSON과 지정한 저장 history DB에서 기존 위험모형용 수익률 행렬을 준비합니다. 네트워크·자격증명 접근 없이 선정 순서와 Decimal 값을 보존합니다.

```bash
uv run phalanx portfolio allocation-input \
  --selection /absolute/private/selection.json \
  --history-db /absolute/private/history.sqlite3 \
  --output /absolute/private/allocation-input.json
```

`--selection`, `--history-db`는 필수이며 `--output`은 선택입니다. `strict_observed_window_v1`은 겹치는 기간의 관측일 합집합에서 최근 최대 757개 종가 날짜를 검사하고, 한 종목이라도 날짜가 빠지면 입력 준비를 차단합니다. 최소 **504개 수익률에는 종가 505개**가 필요합니다. 선정이 채워졌다면 비선정 후보로 인한 `complete=false`는 허용합니다.

빈 선정·top 미달·이력 부족·날짜 불일치·위험모형이 지원하지 않는 영숫자 코드는 `input_ready=false`, `matrix=null`로 출력·저장합니다. 성공은 종료 코드 0, 정상 준비 불가는 2, 입력 모순은 65, 읽기·저장 오류는 66입니다. 공식 거래일 무누락은 검증하지 않습니다. 공분산·ERC·목표비중·매매계획은 후속 단계입니다. [상세 계약](docs/selection-allocation-input.md)과 [합성 입력 재현](examples/selection-allocation-input/README.md)을 참고하세요.

## 선정 종목 단일 기준일 ERC 목표비중 v1

준비된 선정 종목의 마지막 가격 관측일 하나에서 네 위험 시나리오의 ERC 연구용 목표비중을 독립 계산합니다. 위 입력 준비 서비스를 한 번 호출하고, 한 위험 snapshot을 기존 위험모형·solver에 연결합니다.

```bash
uv run phalanx portfolio allocation-targets \
  --selection /absolute/private/selection.json \
  --history-db /absolute/private/history.sqlite3 \
  --output /absolute/private/allocation-targets.json
```

동일 위험예산·양의 비중·종목당 20% 상한·합계 1을 유지하며 기존 `reconciled_weights`를 그대로 사용합니다. **4종목 이하는 제약 실패**, 5종목은 각각 20%인 경계입니다. 최소 6종목 성공 예제는 [합성 입력 재현](examples/selection-allocation-targets/README.md)에 있습니다.

전체 성공은 종료 0, 입력 준비 불가·계산 실패·부분 성공은 2이며 결과 JSON에 구별해 보존합니다. 잘못된 원천 입력 65와 읽기·저장 오류 66은 기존과 같습니다. 휴일 선정 기준일은 실제 관측 종점과 따로 보존하고, 네 결과를 평균·혼합하거나 추천 전략으로 선택하지 않습니다. 결과는 위험자산 내부의 연구용 배분안이며 실제 계좌 실행 목표·가용현금·정수주·주문·변동성/현금 overlay·전체 과거 백테스트는 포함하지 않습니다. [상세 계약과 한계](docs/selection-allocation-targets.md)를 참고하세요.

## Formation Room v1 — 오프라인 편성실

저장된 ERC 목표비중 JSON을 한 파일의 편성실 HTML로 보여줍니다. 네 시나리오의 변동성·전체 100% 구성도·종목 상세·계산 근거로 **위험자산 내부 연구용 배분**을 조회하며, 원본 계산이나 실제 계좌를 다시 호출하지 않습니다. 향후 Windows 설치형 앱에 내장할 오프라인 화면 시제품입니다.

```bash
uv run phalanx portfolio formation-room \
  --targets /absolute/private/allocation-targets.json \
  --output /absolute/private/formation-room.html
```

두 옵션은 필수이며 기존 출력은 덮어쓰지 않습니다. 유효한 실패 결과 화면도 종료 0, 입력 오류 65, 읽기·저장 오류 66입니다. HTML 한 파일을 브라우저로 열면 서버·CDN·외부 폰트 없이 동작합니다. WSL에서는 `explorer.exe "$(wslpath -w /absolute/private)"`로 폴더를 열거나 HTML을 Windows의 새 폴더에 복사해 엽니다. 브라우저는 자동 실행하지 않습니다.

선택적인 `--selection /absolute/private/selection.json`으로 원본 선정 결과의 회사명을 연결할 수 있습니다. 원본 파일 해시와 코드·기준일·정책 등 대응 근거가 일치할 때만 이름을 표시하며, 미제공·이름 누락은 코드와 `이름 미확인`으로 표시합니다. 합성 예제는 생성기가 전달한 명시적 메타데이터로 `합성 데이터 데모` 배지를 표시합니다.

처음에는 무음이며 명시적인 소리 켜기 이후 효과음과 **코드로 합성한 프로토타입 배경음악**을 사용할 수 있습니다. 시작 대기 중에도 전체 무음/취소가 가능합니다. 음향·모션 설정만 보관하고, 브라우저 정책상 저장이 막히면 세션 설정으로 동작합니다. 화면용 projection 검증은 전체 위험모형 재검증이 아닙니다. [입력·화면·음향 계약과 한계](docs/formation-room.md), [합성 상태·이름 경계 예제와 직접 확인 방법](examples/formation-room/README.md)을 참고하세요.

## KIS 국내주식 일별 시세

일별 시세 기능은 한국투자증권 실전투자 서버의 조회 전용 API를 사용합니다. [공식 open-trading-api 예제](https://github.com/koreainvestment/open-trading-api/tree/main/examples_llm/domestic_stock/inquire_daily_itemchartprice)의 계약에 따라 다음 endpoint와 TR ID를 고정합니다.

```text
GET /uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice
TR ID: FHKST03010100
```

요청은 국내주식(`FID_COND_MRKT_DIV_CODE=J`), 일봉(`FID_PERIOD_DIV_CODE=D`), 수정주가(`FID_ORG_ADJ_PRC=0`)로 고정합니다. KIS의 1회 응답 건수 제한을 넘는 범위는 가장 오래된 응답 거래일의 하루 전으로 종료일 커서를 옮겨 과거 방향으로 조회합니다. 중복과 범위 밖 행을 제거한 뒤 거래일 오름차순의 불변 `DailyBar` 값으로 반환합니다.

한 종목을 조회하려면 다음 명령을 사용합니다. 결과에는 조회 건수, 최초·최종 거래일과 최초·최종 종가가 표시됩니다.

```bash
uv run phalanx market-data daily 005930 --start 2026-01-01 --end 2026-08-31
```

로컬 유니버스에서 활성화된 종목만 등록 순서대로 조회하려면 다음 명령을 사용합니다. 한 종목이라도 실패하면 해당 종목코드와 종목명을 명시하고 전체 명령이 실패합니다.

```bash
uv run phalanx market-data universe --start 2026-01-01 --end 2026-08-31
```

이 기능은 **KIS READ ONLY 시세 조회**만 수행합니다. 조회한 시장데이터를 파일이나 데이터베이스에 저장하지 않으며, 포트폴리오 최적화·비중 계산·GUI·매수·매도·정정·취소를 구현하지 않습니다. OAuth는 계좌 스냅샷과 동일한 기존 `KisTokenManager`와 토큰 캐시를 재사용합니다.

## KRX 현재가 묶음 조회·저장

지정한 종목의 현재가를 입력 순서대로 조회하여 한국어 표에 종목코드, 가격, 시장, 요청 시작·응답 수신 관측시각(KST)을 표시합니다. 기존 `KisCurrentPriceClient`와 `ValuationPriceService`, 외부 자격증명·토큰 캐시, 하나의 공유 HTTP client와 호출 간격·호출 제한 알림을 재사용하는 **READ ONLY** 명령입니다.

```bash
uv run phalanx market-data valuation-prices \
  --stock-code 000270 \
  --stock-code 000660 \
  --max-acquisition-span-seconds 60 \
  --output /개인/결과/새-현재가.json
```

`--stock-code`는 한 개 이상 반복 지정하며 공백 없는 ASCII 숫자 6자리여야 합니다. 누락·중복·잘못된 종목코드는 자격증명 접근과 네트워크 호출 전에 거부합니다. 입력을 정렬하거나 중복을 제거하지 않습니다. 시장은 현재 지원하는 `KRX`로 고정되며 통합시장이나 NXT 선택 옵션은 없습니다.

`--max-acquisition-span-seconds`는 양의 정수 초이고 기본값은 `60`입니다. 수집 구간은 묶음의 **가장 이른 요청 시작부터 가장 늦은 응답 수신까지**입니다. 기존 서비스가 전체 조회 후 이 구간을 검증하며, 허용시간과 정확히 같으면 통과하고 초과하면 실패합니다. 따라서 이 옵션은 개별 HTTP 요청을 강제 취소하는 타임아웃이 아닙니다. 요청 시작 이후의 인증·호출 간격·재시도 대기는 관측 수집 구간에 포함될 수 있습니다.

`--output`을 생략하면 결과 표만 표시하고 결과 JSON은 저장하지 않습니다. 지정하면 모든 종목 조회와 묶음 검증에 성공한 뒤에만 별도 JSON을 저장합니다. 중간 종목 조회 실패, 결과 불일치 또는 수집 허용시간 초과 시 부분 결과를 표시하거나 저장하지 않습니다. 기존 private JSON 저장 기능으로 원자적으로 생성하며 결과·잠금 파일은 `0600`, 새 결과 디렉터리는 `0700`입니다. 기존 파일은 덮어쓰지 않습니다.

아래는 저장 형식을 설명하는 **합성 결과 예시**입니다. `stock_codes`와 `observations`의 순서는 입력 순서이며 가격은 반올림하거나 `float`로 변환하지 않은 Decimal 십진 문자열입니다. JSON 시각은 timezone-aware ISO 8601 형식으로 보존합니다.

```json
{
  "schema_version": "1",
  "currency": "KRW",
  "market": "KRX",
  "stock_codes": ["000270", "000660"],
  "max_acquisition_span_seconds": 60,
  "request_started_at": "2026-09-05T00:00:00+00:00",
  "received_at": "2026-09-05T00:00:01.200000+00:00",
  "acquisition_span_microseconds": 1200000,
  "observation_time_basis": "client_request_start_and_response_receipt",
  "observations": [
    {
      "stock_code": "000270",
      "current_price": "108000.25",
      "market": "KRX",
      "request_started_at": "2026-09-05T00:00:00Z",
      "received_at": "2026-09-05T00:00:00.100000Z"
    },
    {
      "stock_code": "000660",
      "current_price": "201000.00",
      "market": "KRX",
      "request_started_at": "2026-09-05T00:00:00.100000Z",
      "received_at": "2026-09-05T00:00:01.200000Z"
    }
  ]
}
```

관측시각은 클라이언트의 REST 요청·응답 경계이며 실제 거래소 체결시각이나 확정 종가시각을 뜻하지 않습니다. 최근에 조회했더라도 장 마감·거래정지 등으로 오래된 가격일 수 있고 체결 가능성을 보장하지 않습니다. 원본 API 응답·계좌번호·자격증명·접근토큰은 결과에 기록하지 않습니다. 이 명령은 계좌 스냅샷, 실계좌 성과 계산, 연구 계산을 변경하거나 현재가로 계좌 순자산을 재계산하지 않으며, 주문·목표비중·주문수량을 만들지 않습니다.

필수 옵션 누락·잘못된 정수 옵션은 종료 코드 `2`, 종목코드 입력·현재가 조회·묶음 검증 실패는 `60`, 결과 저장 실패·기존 파일 충돌은 `66`입니다. 기존 서비스가 개별 종목 조회 실패를 통합하므로 종목 조회 중 인증 실패도 해당 종목의 조회 실패(`60`)로 보고합니다. 원본 오류나 Python traceback은 출력하지 않습니다. 구현 검증은 합성 응답과 차단된 실제 네트워크로 수행합니다.

## 공통 거래일 수익률 행렬

활성 유니버스 전체의 수정주가 종가로 일별 단순수익률 행렬을 계산할 수 있습니다. 행은 수익률 구간의 종료 거래일이고 열은 사용자가 유니버스에 종목을 등록한 순서입니다. 모든 계산값은 이진 부동소수점 `float`로 변환하지 않고 `Decimal`로 유지합니다.

먼저 모든 종목에 공통으로 존재하는 종가 날짜의 교집합을 오름차순으로 정렬합니다. 인접한 두 공통 날짜의 종가를 `previous_close`, `current_close`라 할 때 각 값은 다음 공식으로 계산합니다.

```text
simple_return = current_close / previous_close - 1
```

한 종목에만 존재하는 거래일은 행렬에서 제외합니다. 누락 날짜를 전일 종가로 채우는 forward fill이나 보간을 하지 않으며, 각 행의 모든 종목은 반드시 동일한 시작일과 종료일 사이의 수익률을 비교합니다. 따라서 수익률 기준일은 공통 종가 날짜의 두 번째 날짜부터 시작하고, 수익률 관측치 수는 공통 종가 관측치 수보다 하나 적습니다.

```bash
uv run phalanx portfolio returns --start 2026-01-01 --end 2026-08-31
```

명령은 네트워크 작업 전에 조회 기간과 **READ ONLY** 상태를 표시하고, 종목 수, 공통 종가·수익률 관측치 수, 최초·최종 수익률 기준일과 종목코드 순서를 출력합니다. 기존 활성 유니버스 시세 조회와 shared request pacing 및 호출 제한 진행 알림을 그대로 재사용합니다. 시장데이터나 수익률 행렬을 저장하지 않으며 공분산·기대수익률 추정, 포트폴리오 최적화, 목표 비중, 주문 수량 또는 주문 기능은 제공하지 않습니다.

## 과거 유니버스 성과 HTML 리포트

활성 유니버스의 `AlignedReturnMatrix`로 종목별 과거 성과와 **동일가중 매수후보유 기준선**을 분석할 수 있습니다. 이 기준선은 분석 시작 시 각 종목에 최초 자본의 `1/N`을 배분하고 이후 리밸런싱하지 않습니다. 각 시점의 기준선 성장계수는 종목별 누적 성장계수의 산술평균입니다. 따라서 매일 동일가중으로 되돌리는 일별 재리밸런싱 포트폴리오와 다릅니다.

```text
stock_growth[t] = product(1 + daily_return[0:t])
baseline_growth[t] = arithmetic_mean(stock_growth[t])
baseline_return[t] = baseline_growth[t] / baseline_growth[t-1] - 1
```

최초 기준선 성장계수는 `1`입니다. 모든 계산은 연간 거래일 `252일`, 무위험수익률 `0%`, Decimal precision `50`, `ROUND_HALF_EVEN`을 사용합니다. 성과지표 정의는 다음과 같습니다.

- 총수익률: `final_growth - 1`
- 연환산수익률: `final_growth ** (252 / observation_count) - 1`
- 연환산변동성: 일별 수익률의 표본표준편차 × `sqrt(252)`
- Sharpe: 일별 평균수익률 ÷ 일별 표본표준편차 × `sqrt(252)`
- Sortino: 일별 평균수익률 ÷ downside deviation × `sqrt(252)`; downside deviation은 전체 관측치에 대한 `min(return, 0)` 제곱평균의 제곱근
- Drawdown: `growth / running_peak - 1`; 최초 running peak는 `1`
- 최대낙폭: Drawdown의 최솟값
- Calmar: 연환산수익률 ÷ `abs(최대낙폭)`
- 상승일 비율: 일별 수익률이 `0`보다 큰 관측치 비율
- 최고·최악 일간수익률: 일별 수익률의 최댓값·최솟값
- 월별 수익률: 해당 달의 기준선 일별 수익률을 복리 결합
- 종목 간 상관계수: 공통 날짜 일별 수익률의 Pearson 표본상관계수

표본분산이 0이면 Sharpe와 관련 상관계수, 하방편차가 0이면 Sortino, 최대낙폭이 0이면 Calmar를 계산 불가능한 값인 `N/A`로 표시합니다. 0이나 무한대로 대체하지 않습니다.

```bash
uv run phalanx portfolio historical-report \
  --start 2025-01-01 \
  --end 2026-08-31 \
  --output reports/historical-universe.html
```

리포트에는 성과지표 표, 종목별·기준선 누적 성장 차트, 기준선 Drawdown, 월별 수익률과 종목 간 상관계수 히트맵이 포함됩니다. Plotly JavaScript를 HTML 내부에 포함하므로 CDN이나 인터넷 연결 없이 열 수 있습니다. 새 HTML 파일은 생성 순간부터 `0600`이고 같은 디렉터리에서 원자적으로 저장되며 기존 파일은 덮어쓰지 않습니다.

이 분석에는 다음 한계가 있습니다.

- **실제 계좌 성과가 아니며 Phalanx 전략 백테스트도 아닙니다.** 실제 계좌 NAV, 입출금과 체결 내역을 사용하지 않습니다.
- 현재 활성 유니버스를 과거에도 보유했다고 가정하므로 생존편향 가능성이 있습니다.
- 수수료, 세금, 슬리피지와 입출금을 반영하지 않습니다.
- KOSPI 시계열 데이터가 아직 없으므로 KOSPI 성과를 비교·추정하거나 가짜 벤치마크를 만들지 않습니다.
- 기대수익률·공분산 추정, Max Sharpe, 포트폴리오 최적화, 목표 비중과 주문 수량 계산을 수행하지 않습니다.
- KIS 연결은 기존 실전계좌 **READ ONLY** 시세 조회뿐이며 주문을 전송하지 않습니다. 시장데이터와 수익률 행렬도 별도로 영속 저장하지 않습니다.

## 자산배분 연구 harness

자산배분 연구 harness는 최적화 모델이나 종목 추천기가 아니라, 배분 정책을 동일한 데이터·신호 시점·체결 가격·비용 조건에서 비교하기 위한 재현 가능한 심판입니다. 현재 비교 대상은 5 공통 거래일마다 같은 비중으로 되돌리는 `WeeklyEqualWeight`, 직전 수익률의 표본변동성 역수로 배분하는 `WeeklyInverseVolatility`, 최초 체결 뒤 비중 변화를 그대로 두는 `EqualWeightBuyAndHold`입니다. 모든 정책의 목표 주식비중은 `0.995`이고 나머지 `0.005`는 현금입니다.

```bash
uv run phalanx portfolio allocation-research \
  --start 2023-01-01 \
  --end 2026-08-31 \
  --output-dir research/allocation-trials
```

활성 유니버스의 수정주가 시가·종가가 모두 존재하는 공통 거래일만 등록 순서대로 사용하며 forward fill, 보간 또는 임의 결측 보정은 하지 않습니다. 최초 신호는 close-to-close 수익률 504개를 확보한 거래일 종가 뒤에 생성하고, 이후 신호는 5 공통 거래일 간격으로 생성합니다. 정책에는 신호일까지의 수익률만 전달하며 최대 최근 756개만 사용합니다. 목표비중은 신호일 종가가 아니라 **다음 공통 거래일 시가**에 체결합니다. 따라서 요청 시작일과 실제 평가 시작일은 학습 구간과 다음 날 체결 때문에 다를 수 있습니다.

이 연구는 연속·분할주식(fractional-share) 회계만 사용합니다. 정수주 제약이나 실제 주문 가능 수량을 계산하지 않으며 결과는 주문 초안이 아닙니다. 리밸런싱 사이에는 보유수량을 고정해 비중이 가격에 따라 자연스럽게 변하고, 외부 자금을 넣지 않는 자기금융 조건을 적용합니다. 현금 이자는 `0`으로 가정합니다.

비용은 매수 거래대금의 `0.001`, 매도 거래대금의 `0.0025`를 각각 적용합니다. 이는 정책을 같은 조건에서 비교하기 위한 **현재 연구 가정**이며 수수료·세금·슬리피지를 포함한 실제 체결비용을 뜻하지 않습니다. 지표 정의는 다음과 같습니다.

- 매수 gross turnover: 각 체결의 매수 거래대금을 해당 체결 직전 NAV로 나눈 값을 평가기간에 걸쳐 합산
- 매도 gross turnover: 각 체결의 매도 거래대금을 해당 체결 직전 NAV로 나눈 값을 평가기간에 걸쳐 합산
- 누적비용률: 평가기간의 명목 매수·매도 비용 합계를 초기 NAV로 나눈 값

각 실행은 고유 trial ID를 가진 별도 JSON으로 `--output-dir`에 저장합니다. trial에는 요청기간과 실제 평가기간, 종목 등록 순서, 정책·설정·시장데이터 fingerprint, 정책별 성과 또는 안전하게 정제한 실패 정보가 포함됩니다. 기존 trial 파일은 덮어쓰지 않습니다.

해석할 때는 다음 한계를 반드시 적용해야 합니다.

- 이 결과는 **현재 선택된 9종목을 과거에도 이미 알고 있었다고 가정한 현재 유니버스 조건부 allocation-only 연구**입니다.
- 종목선정 능력을 측정하지 않으며, 전체 Phalanx 전략의 out-of-sample(OOS) 검증도 아닙니다.
- 현재 살아남아 선택된 종목을 과거에 소급 적용하므로 survivorship bias와 hindsight-selection bias가 존재합니다.
- KOSPI benchmark, 정수주, IEWMA, Ledoit-Wolf, ERC, GMV, HRP, HERC, 알파, 모멘텀, Black–Litterman(BL), Max-Sharpe는 이 기본 `allocation-research` 명령의 범위 밖입니다. Constrained ERC는 아래의 별도 연구 명령에서만 수행합니다.
- 기대수익률 모델, optimizer, 종목 추천, 실계좌 목표수량과 주문 초안도 만들지 않습니다.
- KIS 연결은 기존 실전계좌 **READ ONLY** 일별 시세 조회만 사용하며 매수·매도·정정·취소 주문을 전송하지 않습니다.

## 동적 위험모형 연구

동적 위험모형 연구는 다음 constrained ERC 단계가 시나리오를 이름으로 명시해 소비할 수 있도록, 감사 가능한 **다음 공통 수익률 기간의 공분산 예측**을 생성합니다. 기대수익률, 자산 비중, 수량 또는 주문을 만들지 않으며 네 시나리오를 결합하거나 순위를 매기지 않습니다.

```bash
uv run phalanx portfolio risk-model-research \
  --start 2023-01-01 \
  --end 2026-08-31 \
  --output-dir research/risk-model-trials
```

활성 유니버스의 `AlignedReturnMatrix`를 그대로 사용하므로 종목 등록 순서와 공통 거래일 교집합을 보존합니다. forward fill, 보간, 임의 결측 보정은 하지 않습니다. 최초 snapshot은 close-to-close 수익률 504개가 알려진 신호일에 만들고 이후 5 공통 거래일 간격으로 반복합니다. 각 snapshot은 해당 as-of 종가 이하의 최근 최대 756개 수익률만 소비하며, as-of 이후 행은 estimator에 전달하지 않습니다.

v1은 다음 네 공분산 시나리오를 항상 이 순서로 한 번씩 독립 생성합니다.

1. `long_run_ledoit_wolf`: 전체 trailing window에 `LedoitWolf(assume_centered=True, store_precision=False)`를 적용한 zero-daily-mean second moment
2. `fast_iewma`: 변동성 반감기 21일, 상관관계 반감기 63일인 인과적 IEWMA
3. `slow_iewma`: 변동성 반감기 63일, 상관관계 반감기 125일인 인과적 IEWMA
4. `downside_stress_ledoit_wolf`: 현재 유니버스 동일가중 횡단면 수익률이 가장 낮은 정확히 하위 20% 날짜의 전체 수익률 벡터에 적용한 zero-centered stress second moment

IEWMA의 감쇠계수는 다음과 같습니다.

```text
beta(H) = exp(log(0.5) / H) = 2 ** (-1 / H)
```

finite-history 가중치를 합계 1로 정규화합니다. 변동성 seed는 `max(20, 종목 수)`개의 raw squared return으로 만들고, 이후 각 날짜 `t`에는 반드시 `r_t`를 아직 반영하지 않은 `sigma_t`로 `z_t = r_t / sigma_t`를 먼저 계산합니다. 상관관계 입력인 `z_t`만 `[-4.2, 4.2]`로 자르고, 그 뒤 clipping하지 않은 `r_t²`로 변동성 상태를 갱신합니다. 마지막 raw return까지 갱신한 `sigma_(T+1)`이 다음 수익률 기간의 예측 대각원소에 반영됩니다.

하방 스트레스 날짜는 원래 `Decimal` 동일가중 수익률과 날짜의 쌍을 오름차순으로 정렬한 뒤 `ceil(0.20 × T)`개를 정확히 선택합니다. 동률은 날짜로 결정되며 `<= quantile` 비교를 사용하지 않습니다. 선택한 공통 날짜마다 일부 자산만 자르는 대신 모든 종목의 원래 수익률 벡터를 함께 사용합니다. 따라서 이는 일반적인 unconditional covariance나 개별 종목 semivariance가 아니라 **현재 유니버스 동일가중 하위 20% 날짜의 조건부 zero-centered stress second moment**입니다.

통계 estimator 경계에서 원본 `Decimal` 행렬을 한 번만 NumPy `float64`의 `T × N` 행렬로 변환하고 네 시나리오가 이를 공유합니다. 기존 비용·NAV·자기금융 회계는 계속 고정 precision의 로컬 `Decimal` context를 사용하며 변경하지 않습니다. 최종 일별 공분산에만 252를 정확히 한 번 곱해 연환산하고, 상관계수에는 연환산 계수를 적용하지 않습니다.

모든 결과는 대칭화한 뒤 고윳값 품질 검사를 거칩니다. 규모 상대 허용오차 `1e-10`과 절대 허용오차 `1e-15` 안의 작은 음의 고윳값만 0으로 투영합니다. 양의 eigenvalue floor나 diagonal ridge는 추가하지 않으므로 rank deficiency를 숨기거나 가짜 위험을 만들지 않습니다. 허용오차보다 물질적인 음의 고윳값 또는 상대 Frobenius 보정 크기 `1e-8` 초과는 전체 연구 실패입니다. 각 trial에는 전체 원본 Decimal 수익률, 설정·입력 fingerprint, NumPy·scikit-learn·Python 버전, 모든 rolling snapshot과 PSD 진단을 별도 private JSON으로 기록합니다.

해석에는 다음 제한이 있습니다.

- 현재 활성 유니버스를 과거에도 알고 있었다고 가정하므로 survivorship bias와 hindsight-selection bias가 있습니다.
- 어떤 시나리오도 최적 또는 추천 covariance로 지정하지 않으며, 데이터에 맞춰 반감기나 하방 비율을 조정하는 CLI 옵션도 제공하지 않습니다.
- `risk-model-research` 명령 자체는 expected return, alpha, Black–Litterman, CM-IEWMA, covariance blend, Loewner envelope, 자산 비중과 optimizer를 만들지 않습니다. 별도 Constrained ERC 연구가 이 명령과 같은 네 covariance 계약을 이름으로 소비합니다.
- 결과에는 자산 비중, 정수주·분할주 수량, 주문 초안이 없습니다.
- KIS 연결은 기존 실전계좌 **READ ONLY** 일별 시세 조회뿐이며 주문 endpoint나 주문 TR ID를 추가하거나 주문을 전송하지 않습니다.

수치 정의는 [IEWMA 논문](https://arxiv.org/abs/2305.19484), [저자 공식 재현 코드](https://github.com/cvxgrp/cov_pred_finance)와 [scikit-learn LedoitWolf API](https://scikit-learn.org/stable/modules/generated/sklearn.covariance.LedoitWolf.html)를 참고합니다. Phalanx v1의 finite-history 정규화, 인과적 update 순서, 고정 반감기와 PSD 품질 경계는 위 계약대로 trial에 함께 기록합니다.

## Constrained ERC 연구

Constrained ERC 연구는 네 동적 covariance scenario를 서로 섞거나 평균하지 않고 각각 독립적인 equal-budget 위험배분 정책으로 변환합니다. 이는 각 estimator의 사전 고정 가정과 성과 귀속을 보존하고, 결과를 본 뒤 혼합하거나 선택해 생기는 편향을 피하기 위한 설계입니다. 네 ERC와 `WeeklyEqualWeight`, `WeeklyInverseVolatility`, `EqualWeightBuyAndHold` control을 같은 공통 가격 패널, 504/756/5 일정, 신호일, 다음 공통 거래일 수정주가 시가, 비대칭 비용, 초기 NAV와 평가기간으로 비교합니다. winner나 추천 정책을 자동 선택하지 않습니다.

```bash
uv run phalanx portfolio constrained-erc-research \
  --start 2023-01-01 \
  --end 2026-08-31 \
  --output-dir research/constrained-erc-trials
```

각 covariance `Σ`에 대해 risk budget은 `b_i = 1/N`이고, 다음 log-barrier 문제를 deterministic cyclical coordinate descent로 풉니다.

```text
x*(lambda) = argmin sqrt(x' Σ x) - lambda * sum_i(b_i * log(x_i))
subject to 0 < x_i <= 0.20
```

그 뒤 positive `lambda`의 outer bisection으로 `sum_i(x_i)=1`을 직접 만족시킵니다. inner 해를 normalize하거나 cap 적용 뒤 다시 normalize하지 않으며 risk-contribution least-squares를 사용하지 않습니다. 종목별 20% 상한은 사전에 고정한 concentration 연구 제약이지 보편적인 최적값이라는 주장이 아닙니다. 상한 합계가 1보다 작으면 제약을 완화하거나 현금을 추가하지 않고 해당 정책을 실패 처리합니다. 종목이 정확히 5개이면 모두 20%에 걸리는 퇴화해도 유효한 해로 기록합니다.

최종 위험기여도는 다음과 같이 검증합니다.

```text
sigma = sqrt(x' Σ x)
RC_i = x_i * (Σx)_i / sigma
q_i = RC_i - lambda * b_i
```

free 종목은 `q_i≈0`, lower-bound 종목은 `q_i>=0`, upper-bound 종목은 `q_i<=0`이어야 합니다. 따라서 20% 상한에 걸린 종목의 위험기여도가 `lambda*b_i`보다 낮은 것은 정상적인 KKT 결과입니다. 모든 종목의 상대 위험기여도를 억지로 `1/N`로 맞추지 않습니다. covariance는 기존 PSD 품질 정책을 그대로 사용하며 ridge나 양의 eigenvalue floor를 추가하지 않습니다.

solver의 float64 수치해는 `0.000000000001` quantum의 `Decimal`로 내림한 뒤 fractional remainder가 큰 순서와 종목 등록 순서로 남은 quantum을 배분합니다. 최종 합계는 정확히 `1`, 각 목표비중은 양수이면서 20% 이하이고, reconciliation 뒤 다시 feasibility·Euler·KKT 검사를 통과해야 합니다. backtest는 이 reconciled Decimal 목표비중만 사용합니다.

20%는 **리밸런싱 target cap**입니다. 다음 리밸런싱 전 가격 변화로 실현비중이 20%를 넘는 것은 solver 위반이 아니며 `realized drift cap 초과 일수`로 별도 기록합니다. 네 ERC와 세 control은 이 연구에서 위험자산에 100% 투자하고 전략적 현금 목표는 `0`입니다. 현금을 0변동성 ERC 자산으로 넣지 않으며 leverage, short, expected return, alpha, risk-free rate, volatility target, turnover penalty를 사용하지 않습니다.

체결은 fractional-share 자기금융 연구이며 신호일 종가 다음 공통 거래일 수정주가 시가를 사용합니다. 매수비용률 `0.001`, 매도비용률 `0.0025`는 비교를 위한 연구 가정이지 실제 체결비용이 아닙니다. 각 실행은 `phalanx.constrained_erc_research_trial.v1` 전용 private JSON에 공통 입력, 일정, 네 covariance sequence, raw/reconciled 목표비중, KKT 진단과 일별 NAV·비중·비용 경로를 저장합니다. 기존 allocation/risk-model trial schema와 파일은 변경하지 않습니다.

해석에는 다음 제한이 있습니다.

- 이 결과는 **current-universe conditional allocation-only 연구**입니다. 현재 활성 유니버스를 과거에도 알았다고 가정하므로 survivorship bias와 hindsight-selection bias가 있습니다.
- covariance scenario는 각각 독립적으로 소비하며 혼합·평균·자동 선택하지 않습니다.
- 기대수익률이나 alpha 입력이 없고, 결과는 종목선정 alpha 또는 전체 Phalanx 전략의 OOS 성과를 증명하지 않습니다.
- fractional shares와 고정 비용 가정을 사용하며 정수주, 실계좌 목표수량 또는 주문 초안이 아닙니다.
- KOSPI benchmark가 없으므로 시장 대비 성과를 주장하지 않습니다.
- volatility-target scalar와 cash residual은 아래의 별도 연구 계층에서만 적용하며 기존 ERC risky sleeve 해를 변경하지 않습니다.
- KIS 연결은 실전계좌 **READ ONLY** 일별 시세 조회뿐이며 주문 endpoint, 주문 TR ID 또는 주문 전송을 추가하지 않습니다.

수학적 formulation과 box-bound KKT 회귀값은 [Richard와 Roncalli의 원 논문](https://arxiv.org/abs/1902.05710)을 기준으로 검증합니다.

## Volatility-target scalar + cash-residual overlay 연구

이 연구는 기존 네 Constrained ERC 결과를 **합계 1인 위험자산 sleeve**로 그대로 두고, 각 covariance scenario에 별도 scalar를 독립적으로 적용합니다. 목표 연환산변동성은 production 상수가 아니며 매 실행마다 `--target-annual-volatility`로 반드시 명시해야 합니다. 허용 범위는 목표 연환산변동성 `(0, 1]`, 연 현금수익률 `[0, 1]`이고 cash yield 기본값은 정확히 `0`입니다. 두 입력은 trailing zero를 제거한 뒤 소수점 이하 최대 12자리까지 허용하며, `0.20`과 `0.2`처럼 경제적으로 같은 입력은 같은 canonical `Decimal`과 fingerprint로 처리합니다. 100% 상한은 비정상 입력의 자원 증폭을 막기 위한 입력 안전 경계일 뿐, 권장 변동성 또는 권장 현금수익률 가정이라는 뜻이 아닙니다.

```bash
uv run phalanx portfolio volatility-overlay-research \
  --start 2023-01-01 \
  --end 2026-08-31 \
  --target-annual-volatility 0.12 \
  --annual-cash-yield 0 \
  --output-dir research/volatility-overlay-trials
```

한 signal date의 reconciled ERC 종목비중을 `x_i`, 해당 ERC의 post-reconciliation forecast 연환산변동성을 `sigma_forecast`, CLI 목표를 `sigma_target`이라 하면 다음과 같이 계산합니다.

```text
scalar = min(1, sigma_target / sigma_forecast)
final_equity_weight_i = scalar * x_i
cash_residual = 1 - sum_i(final_equity_weight_i)
```

`sigma_target`과 `sigma_forecast`는 양의 유한한 값이어야 하고 scalar는 `0 < scalar <= 1`입니다. `sigma_target`에는 위 `(0, 1]` 입력 범위와 canonical 소수점 이하 12자리 제한도 적용됩니다. 따라서 leverage와 short를 만들지 않으며, scaling 전 ERC 내부 상대비중을 보존합니다. 기존 `x_i <= 0.20` target cap도 scaling 뒤 유지되고 모든 최종 종목비중과 cash residual의 `Decimal` 합계는 정확히 `1`이어야 합니다. forecast가 0, 음수, NaN 또는 infinity이면 clamp·대체값·fallback 없이 해당 scenario를 실패 처리합니다.

네 scenario는 기존 causal rolling window와 동일한 504/756/5 signal schedule을 각각 소비하고, 신호일 종가 뒤 **다음 공통 거래일 수정주가 시가**에 동적 목표 주식비중을 체결합니다. 한 scenario의 ERC 또는 overlay가 실패해도 다른 scenario를 대신 사용하거나 winner를 자동 선택하지 않습니다. 기존 fully-invested ERC solver, KKT 진단, 7-policy backtest 및 `phalanx.constrained_erc_research_trial.v1` schema는 변경하지 않습니다.

연 현금수익률 `y_cash`는 다음 양의 일별 복리계수로 명시 변환합니다. 입력 계약은 `0 <= y_cash <= 1`이고 trailing zero 제거 후 소수점 이하 최대 12자리이며, 연환산 거래일은 source 연구와 같은 252일입니다.

```text
daily_cash_growth_factor = (1 + y_cash) ** (1 / 252)
```

최초 체결일에는 그 이전의 관측되지 않은 기간에 이자를 붙이지 않습니다. 최초 체결 다음 공통 거래일부터 각 거래일 open 체결 전에 잔여 현금에만 위 계수를 한 번 적용합니다. `--annual-cash-yield 0`이면 이 경로는 기존 무이자 자기금융 회계와 정확히 같습니다. 주식 평가액에는 cash yield를 적용하지 않으며 리밸런싱은 기존 매수 `0.001`, 매도 `0.0025` 비대칭 비용을 사용합니다.

**Sharpe hurdle 또는 risk-free rate와 cash yield는 서로 다른 입력 개념입니다.** 현재 과거 성과 HTML 리포트의 Sharpe는 문서상 0% 무위험수익률을 사용하고, 이 overlay 명령은 Sharpe나 risk-free-rate 입력을 받지 않습니다. 분석자가 별도로 3%를 risk-free rate 또는 Sharpe excess-return hurdle로 사용하더라도 그 값은 현금 보유액의 실제 성장률을 뜻하지 않으므로 cash yield로 복사하지 않습니다. 특히 이 명령은 3%를 암묵적으로 사용하지 않으며 `--annual-cash-yield`의 기본값은 0입니다. 독립적인 현금수익 가정을 모델링하려는 경우에만 사용자가 그 값을 명시해야 합니다.

각 실행은 별도 `phalanx.volatility_overlay_research_trial.v1` JSON을 private `0600` 파일로 원자 저장하고 기존 파일을 덮어쓰지 않습니다. required target volatility, optional cash yield, 일별 성장계수, source ERC·시장데이터·covariance·solver fingerprint, 네 overlay target, 일별 NAV·동적 주식/현금 비중·비용 경로와 Python/NumPy/scikit-learn provenance를 기록합니다. CLI 수치 입력은 이진 `float`를 거치지 않고 `Decimal`로 검증·fingerprint·직렬화합니다.

해석과 안전 경계는 다음과 같습니다.

- 이 결과는 **current-universe conditional allocation-only research overlay**이며 종목선정 alpha나 전체 전략의 OOS 성과를 증명하지 않습니다.
- fractional shares와 고정 비용을 쓰는 연구 회계입니다. 정수주, 실계좌 목표수량 또는 주문 초안이 아닙니다.
- cash residual은 합성 backtest 자산입니다. 계좌 스냅샷의 예수금 총액, 주문가능현금, 실제 잔고·보유수량 또는 투자예산을 읽거나 사용하지 않습니다.
- covariance 혼합, scenario fallback, winner·추천 자동 선택, leverage와 short를 제공하지 않습니다.
- KIS 연결은 기존 실전계좌 **READ ONLY** 일별 시세 GET뿐입니다. 잔고를 overlay 입력으로 연결하지 않으며 주문·정정·취소·hashkey endpoint 또는 코드를 추가하지 않습니다.

## CLI 계약

기본 명령만으로 즉시 실전계좌 read-only 스냅샷을 수행합니다.

```bash
uv run phalanx
```

다음 명시적 별칭도 같은 동작을 제공합니다.

```bash
uv run phalanx account snapshot
```

모듈 진입점도 동일한 명령을 실행합니다.

```bash
uv run python -m phalanx account snapshot
```

CLI에는 환경 선택 옵션이 없으며 모의투자 모드도 제공하지 않습니다.

조회 시작·완료시각은 터미널에서 한국시간 `YYYY-MM-DD HH:MM:SS KST` 형식으로 표시합니다. 자산 대사를 돕기 위해 다음 두 값을 표시 계층에서 `Decimal`로 역산합니다.

- 기타 자산·결제조정 = 총자산 - 예수금 총액 - 주식평가액
- 부채 등 차감액 = 총자산 - 순자산

두 값은 KIS가 별도 필드로 직접 제공한 금액이 아니라 익일정산금액, 가수도정산금액, 금일매매금액 같은 결제·정산 요소가 반영된 계정 차이를 이해하기 위한 표시용 역산값입니다. 양수·0·음수가 모두 가능하며, 오류로 단정하거나 현금·가용현금·주문가능현금·투자예산으로 해석하지 않습니다. 스냅샷 JSON schema에는 이 파생값을 추가하지 않습니다. 향후 기준가 계산에는 총자산이나 이 파생값이 아니라 `net_assets`인 순자산금액을 사용합니다.

종료 코드는 정상 `0`, 설정 `10`, 인증 `20`, 잔고조회 `30`, 스냅샷 저장 `40`, 유니버스 `50`, 시세조회 `60`, 수익률·성과·자산배분 분석 `65`, HTML 리포트 또는 연구 trial 저장 `66`, 예기치 않은 오류 `70`, 사용자 중단 `130`으로 구분합니다. 예상 오류와 예기치 않은 오류 모두 원본 HTTP 요청·응답이나 Python traceback을 출력하지 않습니다.

## 실제 계좌 read-only 스모크 테스트 절차

이 절차는 KIS 인증·잔고조회 구현이 완료된 뒤 개발자가 로컬에서 명시적으로 수행하는 수동 검증입니다. 자동화 테스트나 CI 절차에 추가하지 않습니다.

1. KIS Developers에서 발급한 실전투자 앱 키·앱 시크릿과 실전계좌 번호를 `~/.config/phalanx/credentials.env`에 설정합니다.
2. `stat -c '%a %n' ~/.config/phalanx ~/.config/phalanx/credentials.env`로 각각 `700`, `600`인지 확인합니다.
3. 프로젝트 루트에 `.env` 또는 실제 자격증명 파일이 없는지 확인합니다.
4. 작업 트리에 실제 비밀정보가 없는지 확인합니다. 비밀값 자체를 검색 명령 인자로 넘기거나 출력하지 않습니다.
5. `uv run phalanx`를 한 번 실행합니다.
6. 터미널에 `실전계좌 · READ ONLY` 표시, 마스킹된 계좌번호, 예수금 총액, 주식평가액, 총자산, 종목별 잔고가 출력되는지 확인합니다.
7. 주문가능현금은 `미제공`으로 표시되고 예수금 총액이 그 값으로 복사되지 않았는지 확인합니다.
8. `~/.local/share/phalanx/snapshots/`에 JSON 한 개가 생성되고 원본 계좌번호·앱 키·앱 시크릿·접근토큰이 포함되지 않았는지 확인합니다.
9. 연속조회 대상 계좌라면 HTS의 보유종목 수와 스냅샷의 실제 보유종목 수를 비교합니다. 보유수량 0인 잔고는 별도 목록인지 확인합니다.
10. 실행 전후 미체결·체결 내역에 변화가 없음을 확인합니다. 이 절차에서는 주문·정정·취소 호출을 절대 수행하지 않습니다.

상세 구현 계획은 [`docs/plans/kis-account-snapshot.md`](docs/plans/kis-account-snapshot.md)에 있습니다.
