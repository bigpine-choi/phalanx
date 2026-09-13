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
