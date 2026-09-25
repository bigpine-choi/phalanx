# 단일 기준일 ERC 합성 재현

저장소 루트에서 실행한다. 개발 의존성은 `uv sync --locked --group dev`로 준비한다. 생성 경로는 **아직 없는 새 디렉터리**로 지정한다.

```bash
PYTHONPATH=tests uv run python examples/selection-allocation-targets/generate.py \
  --directory /tmp/phalanx-targets-demo-ready --case ready
uv run phalanx portfolio allocation-targets \
  --selection /tmp/phalanx-targets-demo-ready/selection.json \
  --history-db /tmp/phalanx-targets-demo-ready/history/history.sqlite3 \
  --output /tmp/phalanx-targets-demo-ready/allocation-targets.json
```

`tests/allocation_targets_helpers.py`는 고정 seed의 정수 가격 변화로 서로 다른 **6종목·종가 505개**를 생성한다. 기존 fixture 유틸리티로 합성 SQLite를 만들고 실제 features→selection 서비스를 사용한다. 계산 명령이 input→risk→ERC 전체 경로를 실행한다. 비선정 failed 후보도 추가하므로 원래 선정 `complete=false`는 보존되지만 선정 6종목 계산은 성공한다.

기대 결과: 종료 코드 0, `status=succeeded`, `succeeded_count=4`. 선정 순서는 `005930`, `051910`, `000001`, `000660`, `000002`, `035420`이며 계산일은 `2026-08-20`이다. 네 시나리오 모두 양의 비중·종목당 20% 이하·정확한 합계 1을 만족한다. 시나리오별 비중은 각각 `scenarios[].target.reconciled_decimal_weights`에 있다.

경계/실패 예제도 새 디렉터리에 생성한다.

```bash
PYTHONPATH=tests uv run python examples/selection-allocation-targets/generate.py \
  --directory /tmp/phalanx-targets-demo-four --case four-assets
uv run phalanx portfolio allocation-targets \
  --selection /tmp/phalanx-targets-demo-four/selection.json \
  --history-db /tmp/phalanx-targets-demo-four/history/history.sqlite3 \
  --output /tmp/phalanx-targets-demo-four/allocation-targets.json
```

| 생성 `--case` | 기대 상태/종료 코드 | 근거 |
| --- | --- | --- |
| `ready` | `succeeded` / 0 | 6종목, 네 시나리오 성공 |
| `four-assets` | `failed` / 2 | 4 × 20%로 합계 1을 만들 수 없어 네 target=null |
| `five-assets` | `succeeded` / 0 | 다섯 종목 각각 20%인 경계 해 |
| `short-history` | `input_unavailable` / 2 | 종가 504개는 수익률 503개; 위험모형·solver 미호출 |

생성기는 기존 디렉터리를 사용하지 않고 계산 명령도 기존 출력 파일을 덮어쓰지 않는다. 같은 파일에 다시 저장하면 종료 66이다. 파일 저장 없이 확인하려면 `--output`을 생략한다.

계좌·자격증명·API를 사용하지 않는다. 생성 DB·원천 가격·JSON은 저장소 및 검토 ZIP에 넣지 않는다. 합성 관측일은 공식 거래일 달력이 아니며 이 예제의 결과는 추천/실행 포트폴리오가 아니다.
