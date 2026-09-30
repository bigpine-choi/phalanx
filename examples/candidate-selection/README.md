# 합성 후보 선정 예제

실제 종목·계좌·시장 데이터가 아닌 세 후보의 합성 입력이다. `features.json`은 기존 가격 특성값 계산기를 통해 만들었다. 첫 두 후보는 61개, 세 번째는 21개 종가를 사용한다. 기준일과 세 후보의 종점은 `2026-08-20`이다.

```bash
uv run phalanx candidates select \
  --features examples/candidate-selection/features.json \
  --metric return_60 --top 1 --max-age-days 0
```

| 후보 | 60구간 수익률 | 결과 |
| --- | --- | --- |
| `0001A0` | `0.2` | selected, 순위 1 |
| `000001` | `0.1` | not_selected, 순위 2 |
| `000003` | null | unavailable, 관측 부족 |

`selected_codes=["0001A0"]`, `evaluation_complete=false`, `selection_filled=true`, `complete=false`이므로 종료 코드는 `2`다. 252구간 지표가 모두 불가해도 계산 가능한 60구간 지표를 사용한다. `selection.json`은 평가 시각을 `2026-09-13T00:00:00Z`로 주입한 기대 결과이며, 서비스 테스트가 바이트 단위로 재현한다. 일반 CLI 실행의 평가 시각은 달라진다.

top=1과 max-age-days=0은 예제를 설명하기 위한 명시적 입력이며 권장 투자 파라미터가 아니다. 출력 파일을 저장할 때는 `--output /absolute/private/new-selection.json`처럼 새 경로를 사용한다.

## 판단 시점 명세를 붙인 재실행

`decision-manifest.json`은 위 `features.json`의 **정확한 파일 바이트**를 SHA-256으로 고정하고,
합성 자료의 관측·이용 가능·판단 시각과 원천 버전을 명시한다. 다음 명령은 기존 선정 엔진을
다시 사용하고 두 입력의 식별 증거와 부분 결과를 한 JSON에 기록한다.

```bash
uv run phalanx candidates replay \
  --manifest examples/candidate-selection/decision-manifest.json \
  --features examples/candidate-selection/features.json \
  --metric return_60 --top 1 --max-age-days 0 \
  --output /absolute/private/new-decision-snapshot.json
```

이 예제의 종료 코드도 부분 결과를 뜻하는 `2`다. 기존 출력은 덮어쓰지 않는다. 이용 가능 시각은
manifest 작성자의 선언이며, 과거 가격 각각의 실제 수신 시각이나 정정 이력을 검증한 증거가 아니다.
출력의 `availability_check=declared_manifest_only`와
`point_in_time_backtest_guaranteed=false`가 이 한계를 보존한다. 합성 예제를 실제 성과 또는
과거 시점 검증 완료로 해석하지 않는다.
