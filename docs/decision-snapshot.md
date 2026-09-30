# 판단 시점 후보 선정 재실행 v1

`phalanx candidates replay`는 이미 만든 가격 특성값 JSON과 판단 시점 명세를 읽어 기존 단일 지표 후보 선정 엔진을 다시 실행한다. 입력 파일을 각각 한 번 읽고 SHA-256으로 정확한 바이트를 연결한다. 계좌·주문·네트워크는 사용하지 않는다.

```bash
uv run phalanx candidates replay \
  --manifest examples/candidate-selection/decision-manifest.json \
  --features examples/candidate-selection/features.json \
  --metric return_60 --top 1 --max-age-days 0 \
  --output /absolute/private/new-decision.json
```

`--metric`, `--top`, `--max-age-days`는 기존 [후보 선정 정책](candidate-selection.md)과 같다. `--output`은 선택 사항이다. 예제 명세는 세 후보의 합성 자료를 가리키며, 실제 시장에서 해당 시각에 자료를 얻을 수 있었다는 증거가 아니다.

## 판단 시점 명세

모든 필드는 필수 문자열이다. 알 수 없는 필드·중복 JSON 키·잘못된 형식은 거부한다.

| 필드 | 의미 |
| --- | --- |
| `schema_version` | 명세 버전 `1` |
| `snapshot_id` | 이 입력 묶음의 비어 있지 않은 식별자 |
| `source_name`, `source_revision` | 선언한 자료 출처와 버전; 둘 다 비어 있지 않아야 함 |
| `features_sha256` | features 파일 **원본 바이트**의 SHA-256 |
| `feature_schema_version`, `feature_policy_version` | 각각 `1`, `candidate_price_features_v1`; features와 대조 |
| `price_basis` | `adjusted_close_price_return_excluding_dividends`; features와 대조 |
| `return_unit` | `simple_decimal_ratio` (예: `0.2`는 20% 가격수익률) |
| `market_timezone` | `Asia/Seoul`; 날짜 비교에 사용 |
| `observed_at`, `available_at`, `decision_at` | 시간대가 포함된 관측·자료 이용 가능·판단 시각 |
| `availability_evidence` | `declared`; 시각은 명세 작성자의 선언 |

시각은 `observed_at ≤ available_at ≤ decision_at`이어야 한다. features의 `as_of`는 한국 시간 기준 판단일 이하여야 하고 `calculated_at`도 판단 시각 이하여야 한다. 각 후보의 마지막 사용 관측일(`used_end`)은 한국 시간 기준 `observed_at` 날짜 이하여야 한다. features 해시·스키마·정책·가격 기준이 명세와 다르면 실행을 거부한다. 선정 자체는 기존 지표, 종점, 자료 경과일, 동점 규칙을 그대로 사용한다.

## 결과와 한계

stdout과 선택적 출력 파일에는 명세 전체, 명세 파일의 SHA-256, 기존 `CandidateSelection` 결과가 함께 기록된다. `availability_check=declared_manifest_only`, `point_in_time_backtest_guaranteed=false`를 명시한다. 동일한 입력 바이트·정책·**주입한 평가 시각**이면 결과 바이트가 같다. 일반 CLI 실행은 평가 시각이 바뀌므로 전체 JSON 바이트도 달라질 수 있다. 출력 파일은 기존 파일을 덮어쓰지 않는다.

| 종료 코드 | 의미 |
| --- | --- |
| `0` | 완전한 선정 결과 출력·저장 완료 |
| `2` | 정상적인 부분 선정 결과 출력·저장 완료 |
| `65` | 정책·명세·features 형식 또는 상호 일관성 오류 |
| `66` | 입력 읽기·출력 저장 실패, 또는 출력 파일이 이미 존재함 |

명령 인자 문법 오류도 `2`를 쓸 수 있지만 결과 JSON 없이 사용법 오류를 표시한다.

이 기능은 R1의 **명시적 시간·단위·출처 버전·입력 해시를 기록하고 재실행하는 첫 단계**다. `available_at`은 선언값이며, 원천 일봉마다 과거에 실제로 이용 가능했던 시각이나 수정주가의 당시 버전을 검증하지 않는다. 따라서 과거 시점 정보 집합의 완전성이나 point-in-time 백테스트를 증명하지 못한다. R2의 동일 날짜·거래 가정에 따른 비교 전략 및 성과 비교도 아직 수행하지 않는다.
