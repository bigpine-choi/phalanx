# 후보 종목 가격 특성값 v1

특정 history 작업의 고정 후보에서 수정주가 **관측 종가**를 읽고 가격수익률·연율화 변동성·최대낙폭을 계산한다. 자격증명·OAuth·HTTP 없이 동작하며 원천 DB의 작업·상태·가격을 변경하지 않는다. 부분적으로 수집된 작업도 조회할 수 있고, 계산 불가능한 종목을 결과에서 삭제하지 않는다. 종목 순위·매매 판단·비중 계산은 후속 단계다.

## CLI와 조회·내보내기

```bash
# JOB_ID는 기존 history 작업 ID다. 기준일은 그 작업의 요청 기간 안이어야 한다.
uv run phalanx market-data features calculate JOB_ID \
  --as-of 2026-08-31 --code 005930 --code 0001A0

# 모든 고정 대상을 작업 순서대로 계산하고 새 JSON 파일에도 저장한다.
uv run phalanx market-data features calculate JOB_ID \
  --as-of 2026-08-31 --all-targets \
  --history-db /absolute/private/history.sqlite3 \
  --output /absolute/private/features-2026-08-31.json
```

- `--as-of YYYY-MM-DD`는 필수이며 history 요청의 시작일·종료일을 포함한 범위 안이어야 한다. 날짜를 자동으로 바꾸지 않는다.
- 반복 가능한 `--code` 또는 `--all-targets` 중 정확히 하나를 요구한다. 중복 코드와 작업에 없는 코드는 오류다. `--code`는 지정 순서, `--all-targets`는 고정 작업 순서를 유지한다.
- 영숫자 코드와 원천 식별자를 그대로 보존한다. `KoreanStock`으로 변환하지 않는다. `--all-targets`는 `unsupported` 대상도 포함한다.
- 기본 원천은 `~/.local/share/phalanx/market-data/history.sqlite3`다. discovery DB를 다시 읽거나 원천 결과를 갱신하지 않는다.
- stdout은 결과 JSON이다. `--output`이 있으면 같은 JSON을 기존 원자적 저장 유틸리티로 저장한다. 임시 파일 기록·fsync 후 배타적 하드 링크로 게시하며 기존 파일·심볼릭 링크를 덮어쓰지 않는다. 새 파일은 `0600`, 새 출력 디렉터리는 `0700`이다. 부분 결과도 출력·저장한다.

| 종료 코드 | 의미 |
| --- | --- |
| `0` | 선택한 모든 종목의 8개 지표를 계산하고 요청한 출력까지 완료 |
| `2` | 계산 결과에 하나 이상의 불가 지표가 있음. 가능한 값과 불가 사유를 담은 JSON은 정상 출력·저장됨 |
| `65` | 잘못된 기준일·대상 선택, 존재하지 않는 작업·종목, 지원 범위를 벗어난 Decimal 연산 등 |
| `66` | 원천 저장소 손상·경로·권한 오류 또는 출력 파일 존재·원자적 저장 실패 |

CLI 문법 오류나 필수 인자 누락도 Typer의 종료 코드 `2`를 사용한다. 이때는 사용법 오류가 stderr에 나오며 결과 JSON은 없다. `complete=false`인 결과 JSON이 있는 부분 계산과 구분한다. 오류 시 기존 출력은 보존되며, 저장소 손상을 자료 부족으로 표시하지 않는다.

## 관측 기준과 계산식

정책 버전은 `candidate_price_features_v1`이다. 각 종목에서 `trade_date <= as_of`인 관측만 선택하고 마지막 관측 종가를 종점으로 삼는다. 종목 간 공통 날짜로 자르지 않으며 누락 날짜 보간·가격 채우기·기간 자동 축소를 하지 않는다.

N은 연속된 관측 종가 사이의 **N개 구간**이다. 모든 N구간 지표에는 N+1개의 종가가 필요하다. 관측 사이 달력일 간격이 길어도 그 사이 수익률은 한 관측 구간이다. N을 거래일 수 또는 달력일 수로 보장하지 않는다.

| 지표 `name` | N | 계산식 |
| --- | --- | --- |
| `price_return` | 20, 60, 120, 252 | 마지막 종가 / N구간 전 종가 − 1 |
| `annualized_volatility` | 20, 60 | 최근 N개 단순수익률의 표본표준편차(`ddof=1`) × √252 |
| `maximum_drawdown` | 60, 252 | 최근 N+1개 종가에서 `min(close / running_peak - 1)` |

단순수익률은 인접 관측 종가의 `current / previous - 1`이다. 변동성은 평균을 뺀 제곱합을 `N−1`로 나누고 제곱근을 취한 뒤 √252를 곱한다. 결과의 `policy.annualization_periods=252`, `annualization_formula`, `variance_ddof=1`, `interval_basis=consecutive_observed_closes`가 이 가정을 명시한다. 관측 공백을 별도 기간으로 나누어 연율화하지 않는다.

최대낙폭의 최고가는 해당 창의 **첫 종가**에서 시작하며 이후 종가를 포함해 누적 갱신한다. 창 이전 최고가는 가져오지 않는다. 값은 0 이하이고, 창 전체가 일정하거나 계속 상승하면 0이다.

계산은 새 `Context`의 정밀도 50자리, `ROUND_HALF_EVEN`, `Emin=-999999`, `Emax=999999`를 사용한다. traps와 flags도 명시하여 활성 문맥 및 `DefaultContext` 변경의 영향을 받지 않고 호출자의 전역 문맥도 바꾸지 않는다. 기존 계좌 성과 계산의 공개 함수를 유지하면서 이 문맥 생성기를 공용화했다. float 연산·추가 양자화·표시용 반올림을 사용하지 않는다. 가격·지표의 Decimal 값은 JSON에서 지수 표기 없는 정확한 십진 문자열이며 구간·관측 수는 정수 메타데이터다.

## 결과와 자료 부족

최상위 결과는 history 작업 ID, discovery 실행 ID, history 요청 기간, 요청 기준일, timezone-aware UTC 계산 시각, 정책 설정, `complete` 및 순서 있는 `symbols`를 보존한다.

각 종목은 다음을 포함한다.

- 원천 ordinal 및 `target`의 시장·단축코드·표준코드·이름·정책·원천 파일 정보
- `source_status`, 원천 오류 코드·설명 및 `source_price_sha256`
- `eligible_observation_count`: 기준일 이하의 전체 관측 수
- `used_observation_count`, `used_start`, `used_end`: 최대 창에 쓰는 최근 최대 253개 관측의 수와 실제 기간
- `last_close` 및 `calendar_days_since_last_observation`: 마지막 관측일에서 as_of까지의 달력일 차이
- `consumed_input_sha256` 및 8개 지표의 `value`, `available`, 구간·필요 관측 수·기준일 이하 관측 수·실제 창 시작/종료일·불가 사유

달력일 차이가 양수여도 이를 거래일 누락으로 판정하지 않는다. 관측이 없으면 실제 사용 기간·마지막 종가·달력일 차이는 `null`이다. 지표가 불가이면 해당 지표의 창 시작/종료일도 `null`이며 짧은 기간을 정해진 창으로 표시하지 않는다.

| 원인 | 지표별 `reason_code` |
| --- | --- |
| N+1개 관측보다 적음 | `INSUFFICIENT_OBSERVATIONS`; 필요 수·실제 수를 구체적으로 기록 |
| 완료 결과에 기준일 이하 관측이 없음 | `NO_OBSERVATIONS_AS_OF` |
| 원천 미처리·수집 중·실패·미지원·정상 빈 결과 | `SOURCE_PENDING`, `SOURCE_IN_PROGRESS`, `SOURCE_FAILED`, `SOURCE_UNSUPPORTED`, `SOURCE_EMPTY` |

계산된 0은 `value="0", available=true`이고, 계산 불가는 `value=null, available=false`와 사유다. 예를 들어 관측 21개이면 20구간 가격수익률·변동성을 산출하고 더 긴 지표는 `null`로 남긴다. 전체 작업 또는 장기 지표가 불완전하다는 이유로 단기 계산을 버리지 않는다.

## 입력 해시와 재현성

`source_price_sha256`는 history에 저장된 **전체 OHLCV** 해시다. 원천 상태가 `completed` 또는 `empty`이면 읽을 때 전체 결과의 해시를 검증한다. 기준일 이후 행의 손상도 무시하지 않는다. 결과 자체가 없는 원천 상태에서는 이 값이 `null`이다.

`consumed_input_sha256`는 `dated_closes_as_of_v1` 계약, 단축코드, 요청 기준일, 실제 사용한 최근 최대 253개의 관측일·종가에 대한 SHA-256이다. JSON 키를 정렬하고 구분자를 `,`/`:`로 고정하며 ASCII 인코딩한다. 종가는 정확한 십진 문자열 그대로 해시한다. 이 입력 해시는 전체 OHLCV 원천 해시, 작업·discovery ID, 계산 시각을 포함하지 않는다. open/high/low/volume 및 최대 창 이전 종가도 지표의 소비 입력이 아니다.

따라서 기준일 이후 자료를 정상 추가·변경해 전체 원천 해시가 달라져도 지표값과 소비 입력 해시는 같다. 동일한 기준일·소비 종가·정책에서 계산 시각만 달라져도 같다. 동일한 원천·설정·주입한 계산 시각이면 내보낸 JSON 바이트도 같다. Decimal 값의 소수 자릿수 표현은 보존하므로 값이 같더라도 입력 문자열의 자릿수 표현이 바뀌면 소비 해시는 달라질 수 있다.

정상 빈 결과나 완료 결과에 기준일 이하 관측이 없는 경우에는 빈 종가 목록에 대한 소비 해시가 있다. 원천 결과 자체가 없는 pending/in_progress/failed/unsupported에서는 소비 해시도 `null`이다. 일부 지표가 불가한 경우에도 마지막 관측과 계산 가능한 지표에 사용하는 입력의 해시를 보존한다.

## 재사용 인터페이스와 읽기 계약

```python
from datetime import date
from pathlib import Path

from phalanx.domain.price_features import CandidatePriceFeatures
from phalanx.market_data.features.service import PriceFeatureService
from phalanx.market_data.history.repository import SqliteHistoryRepository

repository = SqliteHistoryRepository(Path("/absolute/private/history.sqlite3"))
service = PriceFeatureService(repository)
result = service.calculate("JOB_ID", as_of=date(2026, 8, 31), codes=("0001A0",))
service.export(result, Path("/absolute/private/features.json"))
restored = CandidatePriceFeatures.model_validate_json(result.to_json_bytes())
```

순수 함수 `calculate_price_features(job, states, *, as_of, calculated_at)`는 검증된 history 모델만 받아 파일·네트워크에 접근하지 않는다. `PriceFeatureService`는 `SqliteHistoryRepository.read_selected`로 선택 입력을 한 번 확보한 뒤 순수 계산을 호출한다. 모든 선택 행은 같은 읽기 트랜잭션의 SQLite 스냅샷에서 가져온다. `--code`는 해당 ordinal의 상태 JSON만 읽고, 전체 대상도 각 상태 JSON과 가격 해시를 한 번씩 파싱·검증한다. 전체 고정 입력의 대상 메타데이터는 한 번 파싱한다. 기존 `show`/`read_bars`도 이 선택 읽기를 재사용하며 `load` 및 저장·재개 계약은 유지한다.

## 해석 한계

`trading_day_completeness=unverified`를 유지한다. 가격 관측이 충분하거나 API 조회가 완료되어도 거래일 무누락이 검증된 것은 아니다. 현재 discovery 후보와 사후 수집한 수정주가를 사용하므로 as_of 필터만으로 과거 시점에 알 수 있었던 정보만 사용한 백테스트가 보장되지 않는다(`point_in_time_backtest_guaranteed=false`). 가격수익률은 배당 포함 총수익률이 아니다.

## 자동 검증

`tests/test_price_features.py`는 손계산 가능한 수익률·표본변동성·창 내부 최대낙폭, N/N+1 경계, 일정 가격의 0, 기준일 이후 자료와 계산 시각 변화, 종목별 길이·관측 공백, 지표별 부분 계산, 영숫자와 원천 상태, Decimal 전역 설정 독립성, JSON 왕복을 검증한다.

`tests/test_price_feature_service.py`는 선택 순서, 실제 상태 JSON 파싱·가격 해시 검증 횟수, 동시 SQLite 쓰기 중 일관된 읽기, 원천 DB 불변성, 선택된 원천 손상 전파를 검증한다. 시간 임계치로 성능을 판단하지 않는다.

`tests/test_price_feature_cli.py`는 자격증명·토큰·HTTP 차단, 부분/완전 결과 출력과 내보내기, 입력 오류, 재현성, 덮어쓰기 거부, 저장 실패 시 불완전 파일 미게시를 검증한다. 기존 history·계좌 성과·원자적 JSON 저장 테스트와 전체 pytest도 실행한다.
