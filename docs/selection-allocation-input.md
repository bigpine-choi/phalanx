# 선정 결과 → 배분 입력 v1

`portfolio allocation-input`은 **selection JSON**과 그 선정이 참조하는 저장 history 작업으로 `AlignedReturnMatrix`를 준비한다. `input_ready`는 수익률 입력 준비만 뜻한다. 공분산 추정·ERC 제약조건·수치 수렴·목표비중·정수주·매매계획·주문·실전 운용 가능성을 보증하지 않는다.

```bash
uv run phalanx portfolio allocation-input \
  --selection /absolute/private/selection.json \
  --history-db /absolute/private/history.sqlite3 \
  --output /absolute/private/allocation-input.json
```

위 경로는 사용자 파일로 바꿀 자리다. `--selection`, `--history-db`는 필수, `--output`은 선택이다. 최신 파일 자동 검색, 별도 작업 ID·기준일·최소 관측 수 덮어쓰기는 제공하지 않는다. stdout은 JSON이고 출력 파일도 같은 bytes다. 정상 준비 불가 결과도 저장하며 기존 파일은 덮어쓰지 않는다.

## 입력과 원천 검증

선정 파일은 한 번 읽은 bytes로 파싱하고 SHA-256을 구한다. schema `1`과 필수 필드, 정책, 후보 상태·순서·점수·개수·완료 플래그의 일관성을 기존 선정 모델과 검증 규칙으로 확인한다. JSON 중복 키·비유한 값·Decimal의 float/bool·정수/boolean 암묵 변환·UTF-8로 표현할 수 없는 문자열은 거부한다.

`SqliteHistoryRepository.read_selected`는 `show`가 사용하는 동일 검증 경로다. 선정 순서대로 필요한 결과만 한 번의 읽기 전용 SQLite snapshot에서 가져온다. 저장소 생성자는 경로만 보존하고 읽기는 DB 생성·마이그레이션·잠금 파일 생성을 하지 않는다. 기존 전용 디렉터리 0700, DB 0600 및 symlink/hardlink 제한도 유지한다. 비선정 후보의 상태 결과를 읽거나 검증하지 않는다.

작업·discovery ID, 기준일의 요청 기간 포함 여부, 선정 후보의 ordinal과 전체 target(시장·코드·표준코드·이름·정책·원천 파일 근거)을 대조한다. history 모델은 공급자 KIS, 수집 계약, API 경로·TR ID, KRX `J`, 일봉 `D`, 수정주가 `0`을 고정한다. 선정 종목은 completed여야 한다. 저장소에서 검증한 결과의 bars와 SHA-256을 그대로 사용하고 선정 후보의 `source_price_sha256`과도 비교한다.

선정 순서와 선행 0을 보존하며 종목 제외·대체·재선정을 하지 않는다. `selection_filled=true`이고 선정 종목이 통과하면 비선정 후보 때문에 `complete=false`여도 준비할 수 있다. 빈 선정은 DB 가격 읽기를 생략하고 `symbols=[]`, `history_contract=null`로 반환한다. 검증하지 않은 가격 근거를 표시하지 않는다.

## 날짜 정책 `strict_observed_window_v1`

1. 코드·오름차순 고유 날짜·양의 유한 종가를 검증한 뒤 `selection.source.as_of` 이하만 사용한다. 빈 가격열이나 겹치지 않는 기간은 준비 불가다.
2. 시작은 종목별 최초 관측일의 최댓값, 끝은 `reference_price_date`로 고정한다. 각 종목의 최종 사용 종점이 이 날짜와 달라지면 과거 공통 종점으로 후퇴하지 않는다.
3. 겹치는 기간의 관측일 **합집합** 중 마지막 최대 757개 가격 날짜를 검사한다. 모든 선정 종목이 이 창의 모든 날짜에 종가를 가져야 한다. 날짜 교집합 축소·짧은 창 재시도·0·forward-fill·보간은 사용하지 않는다. 창보다 오래된 누락은 이번 창의 검증 범위 밖이다.
4. 같은 날짜열의 인접 종가로 `P_end / P_start - 1`을 계산한다. 기존 고정 50자리 `ROUND_HALF_EVEN` Decimal 문맥을 사용하며 float 변환·추가 quantize 없이 기존 `AlignedReturnMatrix`를 구성한다. 열은 선정 순서, 행은 날짜 오름차순이다.
5. `DynamicRiskModelConfig` 기본값을 사용한다. 최소 **수익률 504개 = 종가 505개**, 최대 **수익률 756개 = 종가 757개**다.

A에 월·화·수, B에 월·수만 있으면 화요일 누락으로 차단한다. 모든 종목이 관측하지 않은 주말은 누락으로 만들지 않는다. 모두가 같은 실제 거래일을 빠뜨린 경우는 공식 달력 없이 검출할 수 없으므로 `trading_day_completeness=unverified`를 유지한다.

## 결과와 준비 불가 사유

JSON schema는 `1`이다. 원래 선정 source·정책·완료 플래그, 선정 코드·기준일·참조 종점, 파일 SHA-256, history/discovery ID, 가격 기준, 최소/최대 관측 수를 보존한다. `symbols`에는 실제 검증한 `verified_source_price_sha256`, 저장/기준일 이하/검사 창 종가 수, 최초·최종 관측일과 `missing_dates`가 있다.

`inspected_price_dates`는 검사한 창이다. 날짜열과 종점이 일치하면 `used_start`, `used_end`, `return_observation_count`로 그 창의 기간과 인접 수익률 수를 남긴다. 관측 수 부족이나 코드 미지원이면 이 수가 있어도 `matrix=null`이다. 날짜 불일치일 때 사용 기간은 null, 수익률 수는 0이며 누락 진단을 확인한다.

성공 시 `matrix.stock_codes`, `matrix.dates`(종료일), 정확한 십진 문자열 `matrix.values`와 각 행의 `return_start_dates`를 기록한다. `price_window_sha256`은 실제 계산 가격 날짜·코드·종가 창, `calculation_fingerprint`는 그 창과 정책·Decimal 규칙·행렬을 식별한다. 둘 다 정렬된 키/고정 구분자 UTF-8 JSON의 SHA-256이다. fingerprint에 파일 경로·작업 ID·평가 시각을 섞지 않는다. 추가 실행시각을 만들지 않으므로 같은 입력은 같은 JSON을 낸다.

후보의 `consumed_input_sha256`은 기존 features가 소비한 최대 253개 종가의 근거다. 이번 최대 757개 창의 해시로 취급하지 않으며 `selection_consumed_input_sha256`로 보존한다. features 입력 해시나 지표 재계산을 검증했다고 주장하지 않는다. `features_consumed_input_hashes_verified=false`와 원래 `selection_source.source_price_hashes_verified=false`를 유지한다.

| 사유 코드 | 의미 |
| --- | --- |
| `INPUT_READY` | 수익률 입력 준비 성공 |
| `EMPTY_SELECTION` | 선정 종목 없음 |
| `SELECTION_SHORTFALL` | 요청 top 미달 |
| `RISK_MODEL_CODE_UNSUPPORTED` | 유효한 영숫자 코드를 기존 숫자 6자리 전용 위험모형이 지원하지 않음 |
| `NO_OBSERVATIONS_AS_OF` | 일부 종목에 기준일 이하 종가 없음 |
| `NO_OVERLAPPING_RANGE` | 관측 가격 기간이 겹치지 않음 |
| `PRICE_ENDPOINT_MISMATCH` | 참조 종점과 실제 최종 사용 종점이 다름 |
| `OBSERVED_DATE_MISMATCH` | 검사 가격 창에 종목별 누락 날짜가 있음 |
| `INSUFFICIENT_RETURN_OBSERVATIONS` | 검증된 수익률 관측이 최소 504개 미만 |

여러 사유가 함께 있을 수 있다. 영숫자 코드는 원문을 보존하고 전체 행렬 준비를 차단한다. 기존 계좌·현재가·유니버스·위험모형 validator는 변경하지 않는다.

| 종료 코드 | 의미 |
| --- | --- |
| 0 | 준비 성공 JSON 출력·선택적 저장 완료 |
| 2 | 정상 준비 불가 JSON 출력·선택적 저장 완료 |
| 65 | 잘못된 선정 JSON, 작업/target/선정 원천 해시 불일치, 완료 상태 모순, 수치 범위 오류 |
| 66 | 파일/DB 읽기·원자 저장 실패 또는 기존 출력 파일 존재 |

필수 옵션 누락 등 Typer **문법 오류도 2**지만 이 경우 stdout JSON 없이 stderr에 사용법 오류를 낸다. 저장소 자체의 손상(저장 해시·날짜·코드·스키마 검증 실패)은 기존 `HistoryStorageError`/`STORAGE_FAILED`의 66을 유지한다. 이를 정상 이력 부족으로 처리하지 않는다.

## 재사용과 재현

```python
from pathlib import Path
from phalanx.market_data.history.repository import SqliteHistoryRepository
from phalanx.portfolio.allocation_input.service import AllocationInputService

service = AllocationInputService(SqliteHistoryRepository(Path("/absolute/private/history.sqlite3")))
result = service.prepare(Path("/absolute/private/selection.json"))
if result.input_ready:
    matrix = result.matrix  # 기존 AlignedReturnMatrix; 후속 위험모형의 입력
service.export(result, Path("/absolute/private/new-allocation-input.json"))
```

`validation.parse_selection(bytes)`, I/O 없는 `calculation.prepare_allocation_input`, 파일/DB 서비스와 CLI를 분리했다. 순수 함수에는 검증된 선정 모델과 저장소에서 해시를 검증한 history 모델을 전달한다. Pydantic의 검증 우회 `model_construct`/`model_copy`로 만든 외부 입력은 지원하지 않는다.

[합성 SQLite 재현 방법](../examples/selection-allocation-input/README.md)은 실제 features→selection 서비스 생산 경로를 사용한다. 테스트는 네트워크 차단 환경에서 수익률 경계·날짜 누락·원천 연결·엄격한 JSON·읽기 전용 단일 조회·바이트 일치·원천 불변·저장 실패를 검증한다.

현재 후보의 생존편향 및 사후 수집 수정주가 한계는 그대로이며 `point_in_time_backtest_guaranteed=false`다. 가격수익률은 배당 포함 총수익률이 아니다. 후속 작업에서 공분산과 ERC 및 목표비중을 별도로 검증해야 한다.
