# 후보 평가·선정 엔진 v1

기존 `CandidatePriceFeatures` JSON에 포함된 후보들을 단일 가격 지표로 비교하고 명시한 top개 이내를 선정한다. 정책 ID는 `single_price_feature_rank_v1`이다. 오프라인 연구용 기준 선정기이며 수익성·실전 투자정책 검증을 주장하지 않는다. 비중·매매수량·주문·GUI·자동 유니버스 반영은 수행하지 않는다.

## 사용법과 명시적 정책

```bash
uv run phalanx candidates select \
  --features /absolute/private/features.json \
  --metric return_60 --top 10 --max-age-days 7 \
  --output /absolute/private/selection.json
```

`--features`, `--metric`, `--top`, `--max-age-days`는 모두 필수다. top은 양의 정수, max-age-days는 0 이상의 달력일 정수다. 예시의 10과 7은 기본값이나 검증된 투자 파라미터가 아니다. `--output`을 생략하면 stdout에만 JSON을 출력한다. 지정하면 같은 JSON을 기존 원자적 JSON 저장 유틸리티로 저장하며 기존 파일은 덮어쓰지 않는다. 부분 결과도 출력·저장한다.

| metric | 원천 지표 | 관측 구간 | 우선순위 |
| --- | --- | --- | --- |
| return_20 | price_return | 20 | 큰 값 |
| return_60 | price_return | 60 | 큰 값 |
| return_120 | price_return | 120 | 큰 값 |
| return_252 | price_return | 252 | 큰 값 |
| volatility_20 | annualized_volatility | 20 | 작은 값 |
| volatility_60 | annualized_volatility | 60 | 작은 값 |
| drawdown_60 | maximum_drawdown | 60 | 큰 값 |
| drawdown_252 | maximum_drawdown | 252 | 큰 값 |

최대낙폭은 `0 > -0.1 > -0.5` 순서다. 기간은 기존의 연속된 **관측 종가 구간**이며 거래일 수로 바꾸지 않는다. 원점수를 Decimal로 직접 비교하고 float 변환·양자화·정규화·합성점수를 사용하지 않는다. 내림차순 정렬도 Decimal 부호 반전 없이 안정 정렬하여 전역 Decimal 정밀도·반올림·trap의 영향을 받지 않는다.

## 비교 종점과 평가 가능 조건

`reference_price_date`는 입력 전체에서 `source_status=completed`이며 기준일 이하 관측이 있는 후보들의 `used_end` 최댓값이다. 선택 지표의 자료 충분성, top, 평가 시각과 독립적으로 정한다. 이 날짜는 제공된 후보들의 저장 관측 종점이지 공식 최종 거래일이나 시장 전체 자료 완전성의 증거가 아니다.

순위에 참여하려면 다음 조건을 모두 충족해야 한다.

1. 원천 상태가 completed다.
2. short_code가 정확한 ASCII 숫자·대문자 6자리다.
3. 선택한 지표가 `available=true`다.
4. `used_end == reference_price_date`다.
5. 입력의 `as_of - used_end`가 max-age-days 이하이다.

평가 시각은 가격 경과일 기준으로 사용하지 않는다. 참조 종점이 없거나, 모두 오래되었거나, 최신 종점 후보의 이력이 선택 지표에 부족하면 빈 선정도 정상 부분 결과다. 기준일을 바꾸거나 이전 종점 집단으로 후퇴하지 않는다.

선택한 지표만 충분하면 된다. 예를 들어 관측 61개로 return_60을 계산할 수 있으면 252구간 지표의 null과 입력 `features.complete=false`만으로 탈락시키지 않는다. 정상 0은 유효한 원점수이며 계산 불가 null을 0으로 바꾸지 않는다. 영숫자·선행 0·표준코드·원천 식별자를 보존하고 KoreanStock으로 변환하지 않는다. 식별자 없는 unsupported 후보도 남긴다.

## 동점·순위·상태

평가 가능한 후보만 정책 방향으로 정렬한다. 원점수 동점이면 유효 short_code의 ASCII 오름차순으로 결정하며 입력 순서·ordinal로 동점을 깨지 않는다. `metric_rank`는 경쟁 순위(예: 1, 1, 3), `selection_order`는 최종 정렬의 유일한 순번(1, 2, 3)이다. 앞에서 최대 top개를 선정하며 동률이라고 top을 초과하지 않는다.

| 상태 | 순위·원점수 | 사유 |
| --- | --- | --- |
| selected | 원점수·metric_rank·selection_order 보존 | SELECTED_TOP_N |
| not_selected | 원점수·두 순위 모두 보존 | OUTSIDE_TOP_N |
| unavailable | 두 순위는 null; 원점수는 원천 지표 값 그대로 | 충족하지 못한 조건들 |

평가 불가 사유는 `SOURCE_PENDING`, `SOURCE_IN_PROGRESS`, `SOURCE_FAILED`, `SOURCE_UNSUPPORTED`, `SOURCE_EMPTY`, `INVALID_IDENTIFIER`, `METRIC_UNAVAILABLE`, `NO_REFERENCE_PRICE_DATE`, `PRICE_OBSERVATION_UNAVAILABLE`, `PRICE_ENDPOINT_MISMATCH`, `PRICE_TOO_OLD`와 한국어 설명으로 남긴다. 원천 오류와 선택 지표의 기존 불가 사유도 별도 필드에 보존한다. 예를 들어 종점이 다른 후보의 지표 자체는 계산 가능할 수 있으므로 그 원점수를 유지하면서 순위는 null로 둔다.

모든 입력 후보는 `candidates`에 원래 순서대로 보존하고, `selected_codes`는 최종 선정 순서로 제공한다. `requested_top`, `eligible_count`, `selected_count`, `not_selected_count`, `unavailable_count`, `shortfall`을 기록한다. 평가 가능 수가 부족하면 있는 후보만 선정하며 shortfall은 요청 top에서 실제 선정 수를 뺀 값이다.

- `evaluation_complete`: 모든 입력 후보를 순위 평가할 수 있는가
- `selection_filled`: 선정 수가 요청 top과 같은가
- `complete`: 위 두 값의 AND
- `source.features_complete`: 원천 features의 완료 여부로, 위 플래그들과 별개

## 파일 입력 경계와 증거

서비스는 입력 파일을 **한 번 읽은 바이트**로 파싱과 SHA-256을 수행한다. DB·discovery·자격증명·OAuth·HTTP에 접근하지 않는다. 기존 features 모델을 재사용하되 새 경계에서는 다음을 검증한다.

- 지원 schema/policy와 명시적인 모든 구조 필드. 누락된 버전·정책을 기본값으로 복구하지 않는다.
- 정확한 8개 지표 조합과 중복, ordinal 중복, 유효 short_code 중복. 선택된 features는 원래 작업의 일부일 수 있으므로 ordinal의 연속성은 요구하지 않는다.
- as_of와 요청 기간, 관측 수·실제 사용 기간·양수 last_close·가격 경과일, 창 간 관계.
- source_status·해시 존재 여부·관측 유무와 지표의 available/value/reason·complete 사이의 모순.
- JSON 중복 키와 비유한 값, Decimal 필드의 float/bool, 정수 메타데이터의 문자열/float/bool 변환, 잘못된 수치 범위.
- 중첩된 이름·출처·오류 설명을 포함한 모든 JSON 문자열의 UTF-8 인코딩 가능 여부. 짝이 없는 Unicode surrogate는 입력 오류(`INVALID_FEATURES`, 종료 코드 65)로 거부하며 문자를 삭제·대체하지 않는다. 정상 surrogate pair와 한글·이모지는 그대로 허용한다. 출력 옵션 유무와 관계없이 잘못된 입력은 출력 파일을 만들지 않고 원본을 보존한다.

형식 모순을 정상 자료 부족이나 평가 불가로 숨기지 않는다. 정상 부분 features는 받아들이고 선택 지표 기준으로 평가한다. 원천 가격이 JSON에 없으므로 실제 가격 대비 지표 재계산이나 원천 가격 해시 재검증은 수행하지 않는다. `source.source_price_hashes_verified=false`가 이를 명시한다.

결과는 입력 파일의 정확한 바이트 해시, history/discovery ID, 원천 as_of·계산 시각·schema/policy·완료 여부, 선정 정책·파라미터·정렬 방향, reference_price_date와 UTC aware 평가 시각을 보존한다. 후보마다 target·ordinal·원천 상태·오류·두 가격 입력 해시, 선택 지표 전체와 원점수 `score`, 실제 사용 기간·관측 수·가격 경과일·상태·순위·사유를 보존한다. Decimal 값은 정확한 십진 문자열로 직렬화한다.

평가 시각 또는 features.calculated_at만 바뀌어도 선정과 순위는 같다. 후자의 경우 입력 파일 바이트 해시는 달라질 수 있다. 동일 입력 바이트·정책·주입 평가 시각이면 JSON 바이트가 동일하다.

## 재사용 인터페이스

```python
from datetime import UTC, datetime
from pathlib import Path
from phalanx.domain.candidate_selection import SelectionMetric, SelectionPolicy
from phalanx.selection.service import CandidateSelectionService

policy = SelectionPolicy(metric=SelectionMetric.RETURN_60, top=10, max_age_days=7)
service = CandidateSelectionService(clock=lambda: datetime(2026, 9, 13, tzinfo=UTC))
result = service.select(Path("/absolute/private/features.json"), policy)
service.export(result, Path("/absolute/private/new-selection.json"))
codes = result.selected_codes
```

`selection.validation.parse_features`는 이미 읽은 bytes를 검증하고, 순수 `selection.engine.select_candidates(features, policy, *, input_sha256, evaluated_at)`는 파일 I/O 없이 평가한다. `domain.candidate_selection`은 정책과 결과 계약을 제공한다. 후속 엔진은 `selected_codes`와 후보별 평가 근거를 읽을 수 있다. 현재 배분 엔진의 숫자 전용 계약을 변경하거나 여기에 자동 연결하지 않는다.

## 종료 코드와 데이터 한계

| 코드 | 의미 |
| --- | --- |
| 0 | complete=true인 결과를 출력·저장 완료 |
| 2 | complete=false인 정상 부분 결과를 출력·저장 완료 |
| 65 | JSON 파싱·내용·정책·평가 시각 입력 오류 |
| 66 | 입력 읽기 또는 출력 저장 오류; 기존 출력 파일 존재도 포함 |

필수 옵션 누락·정수 문법 오류 등 Typer 문법 오류도 2이지만, 이 경우 결과 JSON 없이 stderr에 사용법 오류가 나온다. 부분 결과의 stdout JSON과 구분한다. 오류 메시지에는 입력 전체나 traceback을 노출하지 않는다.

선정 범위는 제공된 features의 후보들뿐이다. 시장 전체 비교를 주장하지 않는다. `trading_day_completeness=unverified`, `point_in_time_backtest_guaranteed=false`를 유지하며 현재 후보와 사후 수집 수정주가의 한계를 as_of 필터로 제거하지 않는다. 가격수익률은 배당 포함 총수익률이 아니다.

합성 입력과 기대 결과는 [examples/candidate-selection](../examples/candidate-selection/README.md)에 있다. 테스트는 정렬 방향·0·동점 경계, 일부 지표만 가능한 입력·완료 플래그, 종점·가격 경과일과 후퇴 금지, 잘못된 JSON·정책·구조·수치, 기존 features CLI 연동, 단일 파일 읽기·원천 불변·JSON 재현, 오프라인 실행·원자적 저장 실패를 검증한다.
