# KIS 실전계좌 read-only 스냅샷 구현 계획

## 1. 목표와 결정사항

첫 번째 마일스톤은 프로그램을 실행할 때 한국투자증권(KIS) Open API에 인증하고, 실행 시점의 실전계좌 예수금 총액과 국내주식 잔고를 읽어 불변 JSON 스냅샷으로 저장하는 것이다.

이 문서의 결정사항은 이전 계획보다 우선한다.

- Phalanx는 KIS **실전투자 환경만** 지원한다.
- 모의투자 계좌, 모의투자 URL, 모의 TR ID, 환경 선택 옵션과 실전·모의 분기 로직은 구현하지 않는다.
- 첫 마일스톤은 완전한 read-only다. 주문·정정·취소·hashkey API를 구현하지 않는다.
- 네트워크 POST는 OAuth 접근토큰 발급 `/oauth2/tokenP` 하나만 허용한다. 계좌 잔고는 GET으로만 조회한다.
- `dnca_tot_amt`는 모델과 터미널에서 항상 **예수금 총액**으로 명명한다.
- 예수금 총액을 가용현금, 주문가능현금 또는 Phalanx 투자예산으로 사용하지 않는다.
- `orderable_cash`는 `None`/`null`, 표시값 `미산정`으로 유지한다.
- 향후 실제 매매계획 마일스톤에서 매수가능조회 API의 `nrcvb_buy_amt`를 별도로 조회한 뒤 주문가능현금 계약을 설계한다.

1차 자료는 KIS Developers 공식 API 문서와 한국투자증권 공식 `open-trading-api` GitHub 예제를 사용한다.

- API 문서: <https://apiportal.koreainvestment.com/apiservice>
- OAuth 예제: <https://github.com/koreainvestment/open-trading-api/blob/main/examples_llm/auth/auth_token/auth_token.py>
- 인증 공통 예제: <https://github.com/koreainvestment/open-trading-api/blob/main/examples_llm/kis_auth.py>
- 국내주식 잔고조회 예제: <https://github.com/koreainvestment/open-trading-api/blob/main/examples_llm/domestic_stock/inquire_balance/inquire_balance.py>
- 잔고 필드 예제: <https://github.com/koreainvestment/open-trading-api/blob/main/examples_llm/domestic_stock/inquire_balance/chk_inquire_balance.py>

## 2. 제안 파일 구조

기존 Python 3.12, uv, `src` 레이아웃을 유지한다.

```text
.
├── .env.example
├── .gitignore
├── README.md
├── pyproject.toml
├── uv.lock
├── docs/plans/kis-account-snapshot.md
├── src/phalanx/
│   ├── __init__.py
│   ├── __main__.py
│   ├── application.py
│   ├── cli.py
│   ├── config.py
│   ├── domain/
│   │   ├── __init__.py
│   │   └── account.py
│   ├── kis/
│   │   ├── __init__.py
│   │   ├── auth.py
│   │   ├── client.py
│   │   ├── parsing.py
│   │   └── errors.py
│   └── snapshots.py
├── tests/
│   ├── fixtures/kis/
│   ├── test_project_security.py
│   ├── test_config.py
│   ├── test_auth.py
│   ├── test_balance_client.py
│   ├── test_pagination.py
│   ├── test_account_models.py
│   ├── test_snapshots.py
│   ├── test_application.py
│   └── test_cli.py
```

접근토큰 캐시는 저장소 외부의 `~/.cache/phalanx/token-cache/kis-access-token.json`에 저장한다. 완성된 스냅샷도 저장소 외부의 `~/.local/share/phalanx/snapshots/`에 저장한다. `runtime/` 제외 규칙은 방어 목적으로만 유지하며 production 기본 경로로 사용하지 않는다.

## 3. 의존성

운영 의존성:

- `httpx`: 동기 REST 클라이언트, 타임아웃, 테스트 전송 계층 주입
- `pydantic`: 검증된 frozen 모델과 `Decimal` 직렬화
- `pydantic-settings`: 명시적으로 전달된 외부 자격증명 매핑 검증과 `SecretStr`; 현재 작업 디렉터리의 dotenv 자동 탐색은 사용하지 않음
- `typer`: 기본 명령과 명시적 하위 명령 별칭
- `rich`: 사람이 읽을 수 있는 계좌 요약과 잔고 표
- `filelock`: 동일 자격증명의 동시 토큰 갱신 직렬화

개발 의존성:

- `pytest`, `pytest-cov`
- `respx`: `httpx` Mock 응답
- `pytest-socket`: 테스트 전체의 실제 네트워크 차단
- `ruff`, `mypy`

공식 예제의 `pandas`, `PyYAML`은 이번 범위에 추가하지 않는다. 의존성과 잠금 파일은 uv로 관리한다.

## 4. 실전투자 전용 설정

다음 값만 사용한다.

```text
base URL: https://openapi.koreainvestment.com:9443
token endpoint: POST /oauth2/tokenP
balance endpoint: GET /uapi/domestic-stock/v1/trading/inquire-balance
balance TR ID: TTTC8434R
```

URL과 TR ID는 코드 상수이며 자격증명 파일에서 재정의하지 못하게 한다. 환경 열거형과 `--environment` 옵션은 만들지 않는다.

`.env.example`에는 설명과 빈 값만 둔다. 이 파일은 변수 계약 문서이며 실제 값을 입력하거나 프로젝트 루트의 `.env`로 복사하지 않는다.

```dotenv
PHALANX_KIS_APP_KEY=
PHALANX_KIS_APP_SECRET=
PHALANX_KIS_ACCOUNT_NUMBER=
```

실제 운영 자격증명의 고정 기본 위치는 저장소 외부의 `~/.config/phalanx/credentials.env`다. 프로그램은 현재 작업 디렉터리나 프로젝트 루트에서 `.env`를 탐색하거나 읽지 않는다. 외부 자격증명 경로가 없으면 디렉터리나 파일을 자동 생성하지 않고, 비밀값이 포함되지 않은 안전한 설정·권한 안내만 출력한 뒤 실패한다.

README와 파일 부재 오류는 다음 최초 1회 준비 절차를 안내한다. `credentials.env`를 만든 다음 사용자가 외부 파일을 직접 편집한다.

```bash
install -d -m 700 "$HOME/.config/phalanx"
install -m 600 .env.example "$HOME/.config/phalanx/credentials.env"
```

두 번째 명령이 기존 파일을 덮어쓸 수 있음을 함께 경고하며, 프로그램 자체는 이 명령을 실행하거나 경로를 생성하지 않는다.

자격증명 로더는 다음 순서로 경계를 검증한 뒤에만 파일을 연다.

1. `~/.config/phalanx`와 `credentials.env`를 `lstat`하여 심볼릭 링크를 거부한다.
2. 디렉터리와 파일이 현재 유효 사용자 소유인지 확인한다.
3. 디렉터리가 실제 디렉터리이고 권한이 정확히 `0700`인지 확인한다.
4. 자격증명이 일반 파일이고 권한이 정확히 `0600`인지 확인한다.
5. 명시적으로 검증한 파일만 읽어 키-값 매핑을 만들고 Pydantic 모델에 전달한다. `env_file=".env"`나 dotenv 자동 탐색을 사용하지 않는다.

계좌번호는 `8자리-2자리` 형식을 검증하고 API 요청 시 앞 8자리 `CANO`와 뒤 2자리 `ACNT_PRDT_CD`로 분리한다. 설정 객체에서는 앱 키와 앱 시크릿을 `SecretStr`로 보관하며 repr, 로그, 검증 오류에 원문이 나오지 않게 한다.

테스트는 기본 자격증명 로더를 호출하지 않는다. `monkeypatch`로 주입한 임시 환경변수 또는 합성 매핑에서 직접 만든 설정 객체만 사용하며 실제 홈 디렉터리의 파일에 접근하지 않는다.

## 5. OAuth 및 토큰 캐시

프로그램 시작 시 토큰을 안전하게 재사용하거나 새로 발급한다.

1. `~/.cache/phalanx/token-cache/kis-access-token.json`의 안전성을 확인하고 캐시 잠금을 획득한다.
2. 앱 키의 SHA-256 지문이 캐시와 일치하고 만료까지 5분 이상 남았으면 토큰을 재사용한다.
3. 캐시가 없거나 만료가 임박하면 `client_credentials`로 `/oauth2/tokenP`를 호출한다.
4. `access_token_token_expired`를 권위 있는 만료시각으로 파싱하고 `expires_in`과 모순되면 프로토콜 오류로 처리한다.
5. 잔고조회에서 알려진 토큰 만료 오류를 받으면 캐시를 폐기하고 한 번만 재인증한다.
6. 토큰 응답과 토큰 값은 스냅샷이나 일반 로그에 포함하지 않는다.

### 생성 시점 권한 보장

권한을 넓게 생성한 뒤 `chmod`하는 방식을 사용하지 않는다.

- 프로그램이 소유하는 `~/.cache/phalanx`와 `~/.cache/phalanx/token-cache`는 각각 처음부터 `Path.mkdir(mode=0o700)`로 생성한다. 기존 `~/.cache`의 권한은 변경하지 않는다. POSIX umask는 권한을 더 제거할 수만 있으므로 두 디렉터리는 `0700`보다 넓게 생성되지 않는다.
- 토큰 파일, 잠금 파일, 원자 교체용 임시파일은 `os.open`의 `O_CREAT | O_EXCL`과 생성 모드 `0o600`으로 연다.
- 임시파일에 JSON을 쓰고 flush와 `fsync`를 수행한 뒤 `os.replace`한다. 최종 파일은 임시파일의 `0600` 권한을 그대로 가진다.
- 기존 application-owned 디렉터리나 캐시 경로가 심볼릭 링크이거나 소유자·권한 검증에 실패하면 사용하거나 자동 복구하지 않고 안전 오류로 중단한다.
- 생성 직후 chmod에 의존하지 않는다는 사실과 디렉터리·토큰·임시파일 모드는 단위테스트에서 확인한다.

## 6. read-only HTTP 경계

일반-purpose 요청 메서드를 애플리케이션 계층에 공개하지 않는다. KIS 어댑터는 다음 두 작업만 제공한다.

- OAuth 토큰 발급: `POST /oauth2/tokenP`
- 잔고 페이지 조회: `GET /uapi/domestic-stock/v1/trading/inquire-balance`

주문, 정정, 취소, hashkey 경로는 상수·모델·메서드 모두 만들지 않는다. 허용되지 않은 메서드·경로 조합은 네트워크 전송 전에 거부한다.

## 7. 잔고조회와 연속조회

종목별 국내주식 잔고를 다음 파라미터로 조회한다.

```text
AFHR_FLPR_YN=N
OFL_YN=""
INQR_DVSN=02
UNPR_DVSN=01
FUND_STTL_ICLD_YN=N
FNCG_AMT_AUTO_RDPT_YN=N
PRCS_DVSN=00
```

연속조회는 반복문으로 구현한다.

1. 첫 요청은 빈 `CTX_AREA_FK100`, `CTX_AREA_NK100`, 요청 헤더 `tr_cont=""`을 사용한다.
2. 응답 헤더 `tr_cont`가 `M` 또는 `F`이면 응답 본문의 두 커서를 다음 요청에 전달한다.
3. 후속 요청 헤더는 공식 예제대로 `tr_cont=N`을 사용한다.
4. 종료 응답까지 모든 페이지의 실제 종목을 순서대로 합친다.
5. 반복 커서, 계속 표시인데 빈 커서, 페이지 안전 상한 초과는 프로토콜 오류다.
6. 어떤 페이지에서든 실패하면 부분 스냅샷을 저장하지 않는다.
7. 각 페이지의 요약값이 다르면 가장 늦은 응답을 정규화 결과로 사용하고 불일치를 evidence에 기록한다.

## 8. 엄격한 응답 파싱

API 문자열을 `float`로 변환하지 않고 직접 `Decimal`로 파싱한다. 빈 문자열을 무조건 0으로 바꾸지 않는다.

### 행 분류

- `pdno`가 비어 있고 종목명도 비어 있으며 금액·수량 필드가 빈 값 또는 명시적 0뿐인 행은 **빈 pdno 자리표시자 행**으로 분류한다. 실제 포지션에는 넣지 않지만 원본 evidence에는 보존한다.
- `pdno`가 비어 있는데 종목명이나 비영(非零) 금액·수량 등 의미 있는 값이 있으면 손상된 행으로 보고 실패한다.
- `pdno`가 있으면 실제 잔고 행으로 보고 모든 필수 필드를 검증한다.

### 숫자 필드 정책

- 필수 숫자 필드가 없거나 `""` 또는 공백이면 `MissingRequiredNumericField`로 실패한다.
- 선택적 숫자 필드가 비어 있으면 `None`으로 둔다. `Decimal("0")`으로 바꾸지 않는다.
- 필수·선택 여부와 관계없이 비어 있지 않은 값이 유효한 십진 문자열이 아니면 `InvalidNumericField`로 실패한다.
- `NaN`, `Infinity`, 지수형 등 도메인에서 허용하지 않는 표현은 거부한다.
- 보유수량·매도가능수량은 음수를 거부하고 금액·평가손익은 필드 의미에 따라 부호 제약을 각각 검증한다.

필수 포지션 숫자는 최소 `hldg_qty`, `ord_psbl_qty`, `pchs_amt`, `evlu_amt`, `evlu_pfls_amt`다. 계좌 요약의 정규화 대상 숫자도 모두 필수다. 파싱 오류가 하나라도 있으면 전체 실행을 실패시키고 JSON을 저장하지 않는다.

## 9. 불변 계좌 스냅샷 모델

모델은 Pydantic frozen 모델과 tuple 컬렉션으로 구성한다.

```text
AccountSnapshot
├── schema_version
├── provider = "korea_investment_securities"
├── account_number_masked
├── query_started_at
├── query_completed_at
├── currency = "KRW"
├── summary
│   ├── deposit_total
│   ├── orderable_cash = null
│   ├── securities_evaluation_amount
│   ├── purchase_amount_total
│   ├── evaluation_amount_total
│   ├── profit_loss_total
│   ├── total_assets
│   └── net_assets
├── positions
├── zero_quantity_balances
└── evidence
```

정규화 매핑은 다음과 같다.

| 모델 필드 | KIS 필드 | 의미 |
|---|---|---|
| `holding_quantity` | `hldg_qty` | 보유수량 |
| `sellable_quantity` | `ord_psbl_qty` | 매도가능수량 |
| `purchase_amount` | `pchs_amt` | 매입금액 |
| `evaluation_amount` | `evlu_amt` | 평가금액 |
| `profit_loss` | `evlu_pfls_amt` | 평가손익 |
| `deposit_total` | `dnca_tot_amt` | 예수금 총액 |
| `securities_evaluation_amount` | `scts_evlu_amt` | 유가증권 평가액 |
| `purchase_amount_total` | `pchs_amt_smtl_amt` | 매입금액 합계 |
| `evaluation_amount_total` | `evlu_amt_smtl_amt` | 평가금액 합계 |
| `profit_loss_total` | `evlu_pfls_smtl_amt` | 평가손익 합계 |
| `total_assets` | `tot_evlu_amt` | 총자산 평가액 |
| `net_assets` | `nass_amt` | 순자산액 |

`dnca_tot_amt`를 `cash`, `available_cash`, `orderable_cash`, `budget`으로 별칭 처리하지 않는다. `orderable_cash`는 항상 미산정이며 `deposit_total`과 독립적이다.

`hldg_qty > 0`은 `positions`, `hldg_qty == 0`은 `zero_quantity_balances`에 둔다. 후자는 실제 보유종목 합계에서 제외한다.

## 10. JSON evidence와 저장

`~/.local/share/phalanx/snapshots/account_snapshot_{타임스탬프}_{고유값}.json`을 한 번만 생성하고 덮어쓰지 않는다. 경로 결정은 저장 로직과 분리하며 실행 시점의 `Path.home()`만 사용하고 CWD와 XDG 환경변수는 무시한다. 기존 `~/.local/share`의 권한은 변경하지 않으며, 프로그램 소유 `phalanx`와 `snapshots` 디렉터리는 각각 `0700`, 임시파일과 최종 JSON은 `0600`을 유지한다. 모든 `Decimal`은 JSON 부동소수점이 아니라 십진 문자열로 직렬화한다.

evidence에는 다음을 보존한다.

- 조회 시작·완료시각과 페이지별 수신시각
- HTTP 상태, 응답 `tr_cont`, 연속조회 커서
- `rt_cd`, `msg_cd`, 비밀값을 제거한 `msg1`
- 페이지별 원본 `output1`, `output2`
- 정규화 전 응답 본문의 SHA-256
- 빈 pdno 자리표시자 행과 페이지 간 요약 불일치 정보

Authorization 헤더, 앱 키, 앱 시크릿, 접근토큰, 원본 계좌번호와 원본 요청 URL은 저장하지 않는다. 스냅샷 디렉터리와 파일도 각각 `0700`, `0600`으로 보호한다.

## 11. CLI

기본 실행이 즉시 스냅샷을 수행한다.

```bash
uv run phalanx
```

다음은 동일 동작의 명시적 별칭이다.

```bash
uv run phalanx account snapshot
```

환경 옵션은 제공하지 않는다. 출력에는 다음을 포함한다.

- `한국투자증권 실전계좌 · READ ONLY`
- 마스킹된 계좌번호
- 조회 시작·완료시각
- `예수금 총액`
- `주문가능현금: 미제공`
- 주식평가액, 총자산, 평가손익
- 종목별 보유수량·매도가능수량·매입금액·평가금액·평가손익
- 실제 보유종목과 분리된 0수량 잔고 건수
- 생성된 JSON 경로

원본 HTTP 예외는 요청 URL에 계좌번호를 포함할 수 있으므로 그대로 출력하지 않는다. 실패 시 안전한 오류와 0이 아닌 종료 코드를 반환하고 파일을 만들지 않는다.

## 12. 테스트 계획

모든 자동 테스트는 실제 자격증명 없이 합성된 실전 API 계약 Mock만 사용한다. 이 Mock은 모의투자 기능이 아니다. `pytest-socket --disable-socket`을 기본 옵션으로 두어 실제 네트워크를 차단한다.

### 설정·보안

- 실전용 변수 세 개만 허용하고 실제 값 없이 설정 오류가 안전하게 표시되는지
- 모의 URL, 모의 TR ID, 환경 옵션이 코드 계약에 없는지
- 프로젝트 루트 `.env`, 토큰, `runtime/`이 Git에서 제외되고 `.env.example`만 포함되는지
- 프로그램이 프로젝트 루트 `.env`를 탐색하거나 읽지 않는지
- 외부 자격증명 파일 부재 시 아무 경로도 생성하지 않고 안전 안내 후 실패하는지
- 외부 디렉터리·파일의 소유자, 일반 파일 여부, 심볼릭 링크 거부와 정확한 `0700`/`0600` 권한 검증
- 테스트가 실제 `~/.config/phalanx/credentials.env`를 읽지 않고 임시 환경변수 또는 합성 설정만 사용하는지
- 계좌번호, 앱 키, 앱 시크릿, 토큰이 stdout, stderr, repr, 예외, JSON에 없는지
- OAuth POST와 잔고 GET 이외의 메서드·경로가 전송 전에 차단되는지

### 토큰

- 신규 토큰 발급과 만료시각 파싱
- 유효 토큰 재사용과 만료 임박 토큰 재발급
- 캐시 앱 키 지문 불일치 처리
- 알려진 토큰 오류에서 한 번만 재인증
- 캐시 디렉터리가 생성 순간부터 `0700`인지
- 토큰·잠금·임시파일이 생성 순간부터 `0600`인지
- 원자 교체 실패 시 기존 캐시가 손상되지 않는지

### 잔고·연속조회

- 실전 URL, `TTTC8434R`, 헤더와 쿼리 파라미터
- 단일 페이지와 `M`, `F` 다중 페이지
- 다음 요청의 두 커서와 `tr_cont=N`
- 반복 커서, 빈 커서, 페이지 상한 및 중간 페이지 오류
- 모든 페이지의 실제 종목 누락 방지
- 빈 계좌와 보유수량 0 잔고 분리
- 오류 시 부분 스냅샷 미생성

### 엄격한 파싱

- 빈 `pdno` 자리표시자 행은 스킵하되 evidence에 보존
- 빈 `pdno`에 의미 있는 값이 있는 손상 행은 실패
- 빈 필수 숫자는 실패
- 잘못된 숫자 문자열은 실패
- 선택적 빈 숫자는 `None`
- `NaN`, 무한대와 금지된 숫자 형식은 실패
- 정상 0 문자열은 `Decimal("0")`
- 음수 평가손익과 큰 금액을 float 손실 없이 보존

### 스냅샷·CLI

- frozen 모델 변경 불가
- 모든 Decimal의 JSON 문자열 직렬화
- `deposit_total`과 `orderable_cash`의 독립성
- 기본 명령과 명시적 별칭의 동일 동작
- 마스킹과 사람이 읽을 수 있는 출력
- 실제 외부 자격증명 파일과 프로젝트 루트 `.env` 없이 전체 테스트 통과

## 13. 수동 read-only 스모크 테스트

Mock 테스트와 별도로 KIS 기능 구현 완료 후 개발자가 로컬에서만 수행한다. README에 저장소 외부 자격증명 파일의 안전한 생성과 `0700`/`0600` 확인, 루트 `.env` 부재 확인, `uv run phalanx` 실행, 마스킹·예수금 명칭·미산정 주문가능현금·스냅샷 비밀정보 부재·보유종목 대조 절차를 기록한다.

이 테스트는 주문 없이 잔고조회만 수행한다. 자동 테스트와 CI에서는 절대 실행하지 않으며 실제 API 호출이 필요한 pytest marker도 만들지 않는다.

## 14. 커밋 단위

1. `chore: configure dependencies and secret/runtime hygiene`
   - 의존성, `.gitignore`, `.env.example`, 최종 계획, read-only README, 프로젝트 보안 회귀 테스트
2. `feat: add immutable account snapshot models and storage`
   - Decimal 모델, 예수금/미산정 주문가능현금 계약, 0수량 분리, 안전한 JSON 저장
3. `feat: add KIS OAuth token cache`
   - 실전 OAuth, 생성 시점 `0700/0600`, 잠금, 원자 캐시와 테스트
4. `feat: add read-only KIS balance client with pagination`
   - 잔고 GET, 연속조회, 엄격한 빈 값/숫자 파싱, 오류 처리와 테스트
5. `feat: expose read-only account snapshot CLI`
   - 기본 명령, 명시적 별칭, Rich 출력, 통합 Mock 테스트와 README 마무리

현재 4번은 단일 페이지 엄격 파서(4A)와 실전 read-only HTTP 연속조회(4B)로, 5번은 저장 오케스트레이션과 CLI(5A)로 구현했다. 실제 자격증명 입력과 실제 KIS 호출은 자동화하지 않으며 수동 read-only 스모크 테스트로만 남긴다.

각 기능 커밋에는 해당 단위테스트를 함께 포함하며 실제 자격증명이나 실제 API 응답을 커밋하지 않는다.
