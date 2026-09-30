# 선정 종목 단일 기준일 ERC 목표비중 v1

선정 결과가 지정한 동일 history 작업에서 검증한 수익률로 마지막 관측일 **하나**의 네 ERC 배분안을 만든다. 기존 selection JSON과 영수증이 연결된 history 재실행 결과를 입력으로 받을 수 있다. 위험자산 내부 연구용 결과이며 실제 계좌 실행 목표나 검증된 추천 포트폴리오가 아니다.

```bash
uv run phalanx portfolio allocation-targets \
  --selection /absolute/private/selection.json \
  --history-db /absolute/private/history.sqlite3 \
  --output /absolute/private/allocation-targets.json
```

영수증이 연결된 재실행 결과를 사용할 때는 다음과 같이 입력한다.

```bash
uv run phalanx portfolio allocation-targets \
  --replay-history /absolute/private/history-replay.json \
  --read-receipt /absolute/private/history-read-receipt.json \
  --history-db /absolute/private/history.sqlite3 \
  --output /absolute/private/allocation-targets.json
```

`--selection` 하나 또는 `--replay-history`와 `--read-receipt` 한 쌍을 지정한다. `--history-db`는 두 경로 모두 필수, `--output`은 선택이다. 입력 준비 서비스를 한 번 호출하며 저장된 allocation-input JSON을 다시 파싱하지 않는다. 재실행 경로는 현재 DB의 전체 후보 행과 별도 영수증을 다시 대조하고, 불일치하거나 영수증이 없으면 계산을 거부한다. 입력 계약·해시 검증·날짜 정렬·504~756개 수익률 기준·숫자 코드 제한은 [입력 준비 v1](selection-allocation-input.md)을 따른다. 기존 `--selection` 경로는 그대로 사용할 수 있다.

## 엔진 연결과 비중

`prepared.input_ready=false`이면 기존 사유와 준비 결과를 그대로 보존하고 위험모형·solver를 호출하지 않는다. 준비되면 `used_end == reference_price_date == matrix.dates[-1]`과 종목 순서·관측 수를 확인한다. **계산일은 used_end**이며 휴일일 수 있는 selection_as_of와 구분한다.

`DynamicRiskModel().estimate(prepared.matrix, as_of_date=계산일)`을 한 번 호출한다. 기존 `SCENARIO_KIND_ORDER` 순서로 다음 네 scenario에 `ConstrainedErcSolver().solve_scenario(scenario, as_of_date=계산일)`을 각각 호출한다.

1. `long_run_ledoit_wolf`
2. `fast_iewma`
3. `slow_iewma`
4. `downside_stress_ledoit_wolf`

기존 기본 설정·버전·PSD 품질 경계를 그대로 사용한다. 이미 연환산된 covariance에 252를 다시 곱하지 않는다. 반환 snapshot의 날짜·종목·시나리오 순서·소비 입력 fingerprint를 전달 행렬과 비교한다. target의 날짜·종목·scenario·bounds·solver/covariance fingerprint도 실제 전달 근거와 대조하고 기존 도메인·유한값 검증을 다시 적용한다. 공분산 fingerprint는 기존 `fingerprint_consumed_covariance`의 PSD 경계를 통과한 solver 소비 행렬 기준이다.

동일 위험예산은 solver 기본 생성 규칙에 맡긴다. 별도의 `1/N` 계산으로 다시 비교하지 않는다. solver는 50자리의 선행 예산과 정확한 마지막 잔여 예산을 만들므로 다른 정밀도의 재생성은 사용하지 않는다. `target.reconciled_weights`를 수정 없이 보존한다. 양의 비중·종목당 20% 상한·합계 정확히 1을 유지하며 재정규화·상한 완화·등가중 대체를 하지 않는다. 4종목 이하는 제약 실패이고, 5종목은 각각 20%인 경계 해다.

입력 준비와 금융 연산·결과 검증을 기존 고정 50자리 `financial_decimal_context()`로 보호한다. 기존 엔진 내부 통계 계산의 NumPy float64 경계, solver의 자체 정밀도 및 reconciliation 규칙은 유지한다. JSON의 최종 Decimal은 기존 정확한 십진 문자열 직렬화를 사용한다.

## 결과와 실패

schema는 `phalanx.selection_allocation_targets.v1`, `schema_version=1`이다. `prepared`에 배분 입력 결과 전체를 포함하여 선정 source·정책·완료 플래그·실제로 검증한 가격 해시·날짜 진단·수익률 행렬을 보존한다. 기존 선정 파일 경로에는 선정 파일 SHA가 남는다. 재실행 경로의 `selection_file_sha256`은 `null`이고 `prepared.replay_provenance`에 재실행·영수증 원본 bytes의 SHA-256, 내장 선정·영수증 내용 해시, 행·features 해시가 이어진다. 기존 선정 파일 경로에는 이 추가 근거가 없다. features 소비 해시를 검증 완료로 바꾸지 않는다. 현재 Formation Room은 별도 선정 파일의 SHA를 요구하므로 재실행 경로의 목표비중 JSON은 그 화면의 입력으로 지원하지 않는다.

추가 근거는 선정 기준일·참조 종점·계산일·선정 코드 순서, 위험모형/solver/PSD 설정 및 fingerprint, 코드·모형·solver 버전, Python/NumPy/scikit-learn 버전, `risk_input_fingerprint`, 전체 `risk_snapshot`, 고정 순서의 `scenarios`다. snapshot은 시나리오별 연환산 covariance·변동성·상관행렬·추정 metadata·PSD 근거를 포함한다. 성공 target은 위험예산·상하한·정확한 비중(`reconciled_decimal_weights`), 연환산 예상변동성·위험기여도·reconciliation 전후 KKT 진단·covariance/solver fingerprint를 보존한다.

| 전체 status | 위험 snapshot | 네 시나리오 |
| --- | --- | --- |
| `input_unavailable` | null | `not_run`, 모든 target=null; 기존 prepared 사유 유지 |
| `common_failure` | null | `not_run`, 모든 target=null; 입력 연결/위험계산 공통 실패 |
| `succeeded` | 보존 | 4개 성공 |
| `partial` | 보존 | 성공과 실패를 각각 보존 |
| `failed` | 보존 | 4개 모두 실패, 모든 target=null |

`complete=true`는 네 시나리오 성공일 때만 가능하다. 한 ERC 시나리오 실패 후에도 나머지는 계속 계산한다. 평균·혼합·자동 최적/추천 선택은 없으며 `recommended_scenario=null`이다. 동일 입력·설정·실행 환경은 동일 JSON을 만들고 별도 실행시각·임의 ID를 추가하지 않는다.

실패는 기존 `safe_constrained_erc_failure`와 안전한 표시 규칙으로 변환한다. `stage`는 `input_contract`/`risk_snapshot`/`scenario`, `category`는 `calculation`/`contract`/`unexpected`다. 예상외 엔진 오류도 실패로 명시하며 자료 부족이나 성공으로 바꾸지 않는다. 원본 예외 문자열·traceback·비유한 통계값은 출력하지 않는다.

| 종료 코드 | 의미 |
| --- | --- |
| 0 | 네 시나리오 성공 JSON 출력·선택적 저장 완료 |
| 2 | 준비 불가·공통 실패·시나리오 실패·부분 성공 JSON 출력·선택적 저장 완료 |
| 65 | 잘못된 선정·재실행·영수증 입력 또는 현재 DB 근거와의 불일치 |
| 66 | 입력 파일/DB 읽기·원자 저장 오류 또는 기존 출력 파일 존재 |

stdout과 `--output`은 동일 bytes이며 기존 원자 저장 함수를 재사용한다. 정상 실패/부분 성공도 저장한다. Typer 문법 오류도 2이지만 stdout JSON 없이 stderr 사용법 오류를 낸다. 엔진 바깥에서 결과를 구성·직렬화할 수 없는 예상외 내부 오류는 `ALLOCATION_TARGETS_INTERNAL_ERROR`와 종료 2를 stderr로 보고하며 성공/부분 결과를 출력하지 않는다.

## 재사용·재현·한계

```python
from pathlib import Path
from phalanx.market_data.history.repository import SqliteHistoryRepository
from phalanx.portfolio.allocation_input.service import AllocationInputService
from phalanx.portfolio.allocation_targets.service import AllocationTargetsService

inputs = AllocationInputService(SqliteHistoryRepository(Path("/absolute/private/history.sqlite3")))
service = AllocationTargetsService(inputs)
result = service.calculate(Path("/absolute/private/selection.json"))
service.export(result, Path("/absolute/private/new-allocation-targets.json"))
```

`domain.allocation_targets`는 상태 계약, `allocation_targets.calculation`은 I/O 없는 엔진 연결, 서비스는 단일 입력 준비와 저장, CLI는 옵션·종료 코드를 담당한다. 계산 함수의 엔진 주입은 연결부 실패 검증을 위한 테스트 경계이며 사용자 설정/모델 선택 옵션은 없다.

[6종목 합성 SQLite 재현](../examples/selection-allocation-targets/README.md)은 실제 features→selection→input→risk→ERC 경로를 사용한다. 테스트는 직접 엔진 호출과의 비교, 4/5종목 제약 경계, 미준비 입력의 호출 차단, 휴일/미래 가격, 잘못된 반환 근거, 부분/공통 실패, Decimal 문맥, 원천 불변·오프라인·원자 저장을 검증한다.

숫자 6자리 코드 한계, 공식 거래일 무누락 미검증, 현재 후보·사후 수집 수정주가의 point-in-time 미보장과 배당 제외 가격수익률 한계를 유지한다. 영수증의 시각은 로컬 시계의 기록이며 SHA-256은 파일·내용 식별 근거다. 공급자의 과거 공개 시각·수정 이력 또는 서명을 증명하지 않으며 `point_in_time_backtest_guaranteed=false`다. 실제 API·자격증명·계좌·가용현금·정수주·매매계획·주문·변동성 목표/현금 overlay·새 모델·전체 rolling 연구/과거 백테스트는 포함하지 않는다. Godot의 **연구 배분** 화면은 이 명령이 저장한 결과를 읽기 전용으로 표시한다. 파일을 열 때 DB·영수증·계산을 다시 검증하지 않으며 실계좌 포트폴리오와 연결하지 않는다. 사용법은 [게임 안내](../game/README.md#연구-배분-결과-보기)를 참고한다.
