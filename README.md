# Phalanx

Phalanx는 한국 주식 포트폴리오 운용 프로그램입니다. 한국투자증권 실전계좌의 예수금 총액과 국내주식 잔고를 읽어 불변 JSON 스냅샷으로 저장하고, 사람이 직접 관리하는 로컬 투자 후보 유니버스, KIS 국내주식 일별 시세 조회, 공통 거래일 수익률 행렬, 과거 유니버스 HTML 리포트와 재현 가능한 자산배분 연구 harness를 제공합니다.

## 현재 마일스톤의 안전 경계

- 한국투자증권 실전투자 환경만 지원합니다. 모의투자 URL, 모의계좌, 실전·모의 분기 로직은 구현하지 않습니다.
- 계좌와 시세 조회는 **READ ONLY**입니다. 주문·정정·취소 API와 주문용 POST 요청을 구현하지 않습니다.
- OAuth 접근토큰 발급 POST, 국내주식 잔고조회 GET과 국내주식 일별 시세조회 GET만 이 마일스톤의 네트워크 범위에 포함됩니다.
- `dnca_tot_amt`는 **예수금 총액**으로만 취급합니다. 가용현금, 주문가능현금 또는 Phalanx 투자예산을 의미하지 않습니다.
- `orderable_cash`는 이번 마일스톤에서 제공되지 않아 `None`/`null`로 유지하고 터미널에는 `미제공`으로 표시합니다. 향후 매매계획 단계에서 매수가능조회 API의 `nrcvb_buy_amt`를 별도로 확인합니다.
- API 키, 앱 시크릿, 계좌번호와 접근토큰은 Git에 포함하지 않습니다. `runtime/` 제외 규칙은 방어 목적으로 유지합니다.

현재 브랜치는 외부 자격증명, OAuth 토큰 캐시, 국내주식 잔고 파싱·연속조회, 불변 스냅샷 저장, 로컬 투자 후보 관리, 수정주가 기준 일별 OHLCV 조회, 공통 거래일 단순수익률 계산, self-contained 과거 성과 리포트와 조건부 자산배분 연구 harness까지 구성합니다. 실제 자격증명과 실제 KIS API는 자동 테스트에서 사용하지 않습니다.

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
- KOSPI benchmark, 정수주, IEWMA, Ledoit-Wolf, ERC, GMV, HRP, HERC, 알파, 모멘텀, Black–Litterman(BL), Max-Sharpe는 이번 연구 범위 밖입니다.
- 기대수익률 모델, optimizer, 종목 추천, 실계좌 목표수량과 주문 초안도 만들지 않습니다.
- KIS 연결은 기존 실전계좌 **READ ONLY** 일별 시세 조회만 사용하며 매수·매도·정정·취소 주문을 전송하지 않습니다.

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
