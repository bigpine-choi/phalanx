# 합성 선정 → 배분 입력 재현

저장소 루트에서 실행한다. 아래 디렉터리는 **아직 없는 새 경로**로 지정한다. 생성기는 기존 fixture(`tests/feature_helpers.py`, `tests/allocation_input_helpers.py`)와 실제 `PriceFeatureService` → `CandidateSelectionService`를 사용한다. dependencies는 `uv sync --locked --group dev`로 준비한다.

```bash
PYTHONPATH=tests uv run python examples/selection-allocation-input/generate.py \
  --directory /tmp/phalanx-allocation-demo-ready --case ready
uv run phalanx portfolio allocation-input \
  --selection /tmp/phalanx-allocation-demo-ready/selection.json \
  --history-db /tmp/phalanx-allocation-demo-ready/history/history.sqlite3 \
  --output /tmp/phalanx-allocation-demo-ready/allocation-input.json
```

기대 결과: 종료 코드 0, `input_ready=true`, 선정 순서 `005930`, `000001`, 수익률 504행·2열, 시작 가격 날짜 `2025-04-03`, 마지막 종료일 `2026-08-20`. 비선정 합성 후보 `000099`는 failed 상태이므로 원래 선정의 `complete=false`는 보존된다. DB에는 두 종목의 합성 종가가 각각 505개 들어 있다.

```bash
PYTHONPATH=tests uv run python examples/selection-allocation-input/generate.py \
  --directory /tmp/phalanx-allocation-demo-short --case short-history
uv run phalanx portfolio allocation-input \
  --selection /tmp/phalanx-allocation-demo-short/selection.json \
  --history-db /tmp/phalanx-allocation-demo-short/history/history.sqlite3 \
  --output /tmp/phalanx-allocation-demo-short/allocation-input.json
```

기대 결과: 종료 코드 2, `input_ready=false`, `INSUFFICIENT_RETURN_OBSERVATIONS`, 수익률 관측 수 503, `matrix=null`. 준비 불가 결과 파일도 저장된다. 같은 출력 경로로 재실행하면 기존 파일을 보존하고 66을 반환한다.

시각은 fixture의 aware 시각으로 고정한다. 실제 계좌·자격증명·API를 사용하지 않으며 생성된 DB·JSON은 저장소나 검토 ZIP에 포함하지 않는다. 이 예제의 날짜는 합성 관측일이며 공식 거래일 달력이 아니다. 목표비중은 생성하지 않는다.
