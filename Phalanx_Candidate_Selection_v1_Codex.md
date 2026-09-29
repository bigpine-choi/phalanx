# Phalanx 후보 평가·선정 엔진 v1 — Codex 구현 지시

아래 범위로 실제 코드, 테스트, 문서와 검토용 ZIP까지 완성하라. 설계 설명만으로 종료하지 말고, 통상적인 구현 선택은 자율적으로 결정하라.

1. 작업 기준과 범위

- 저장소: `~/projects/phalanx`
- 기준 main: `27440dd4dc5eb256ba1c098a8c417dce5823c0c1` — PR #20 squash 병합 커밋.
- 작업 브랜치: `feature/candidate-selection-v1`
- 먼저 AGENTS.md, 현재 브랜치·HEAD·작업 상태를 확인하고 지정 커밋에서 분기한다. 기존 사용자 작업은 보존하며 필요하면 독립 worktree를 사용한다. `reports/`, `research/`는 수정·스테이징·패키징하지 않는다.
- 목표는 기존 features JSON으로 후보를 비교하고 상위 N개를 선정하는 오프라인 연구용 기준 선정기다. 후속 학습모형도 같은 선정 결과 인터페이스를 사용할 수 있도록 정책과 실행을 분리한다.
- 최종 투자전략·비중·매매수량·주문·GUI·자동 유니버스 반영은 이번 범위에 포함하지 않는다. 임의 합성점수, 최적 가중치 탐색, 새 데이터 공급자도 추가하지 않는다.
- 구현 완료 후 검토를 위해 커밋·푸시·PR 생성 전 상태로 남긴다.

2. 입력과 CLI

입력은 PR #20의 `CandidatePriceFeatures` JSON 한 파일이다. DB·discovery·자격증명·OAuth·HTTP를 다시 호출하지 않는다. 기준일은 입력 JSON의 `as_of`를 그대로 사용한다. 출력용 평가 시각은 UTC aware datetime이며 테스트에서 주입 가능해야 한다.

CLI를 다음 형태로 제공한다.

```bash
uv run phalanx candidates select \
  --features /absolute/private/features.json \
  --metric return_60 \
  --top 10 \
  --max-age-days 7 \
  --output /absolute/private/selection.json
```

`--features`, `--metric`, `--top`, `--max-age-days`는 필수다. `--output`은 선택이다. top은 양의 정수, max-age-days는 0 이상의 달력일 정수다. 예시의 10과 7을 암묵적 기본값이나 검증된 투자 파라미터로 만들지 않는다.

정책 ID는 `single_price_feature_rank_v1`로 고정한다. 아래 8개 metric 중 하나를 명시적으로 선택하고 정렬 방향은 정책이 결정한다.

| CLI metric | 기존 지표 / intervals | 우선순위 |
| --- | --- | --- |
| return_20, return_60, return_120, return_252 | price_return / 20, 60, 120, 252 | 큰 값 우선 |
| volatility_20, volatility_60 | annualized_volatility / 20, 60 | 작은 값 우선 |
| drawdown_60, drawdown_252 | maximum_drawdown / 60, 252 | 큰 값 우선: 0 > -0.1 > -0.5 |

구간 수는 기존과 같은 관측 구간이며 거래일 수로 바꾸지 않는다. 지표의 Decimal 원값을 보존하고 float 변환·양자화·합성점수는 사용하지 않는다. 산술 연산이 필요하면 기존 `financial_decimal_context()`를 사용한다.

3. 가격 종점과 평가 가능성

- `reference_price_date`는 입력 전체에서 source_status가 completed이고 기준일 이하 관측이 있는 종목들의 `used_end` 중 최댓값이다. 선택한 지표의 자료 충분성이나 top 값에 따라 이 날짜가 달라져서는 안 된다.
- 순위에 참여하려면 원천 완료, 유효한 종목 식별자, 선택한 지표의 available=true, `used_end == reference_price_date`, `as_of - used_end <= max_age_days`를 모두 충족해야 한다.
- 참조 날짜를 얻지 못하면 빈 선정과 종목별 평가 불가 사유를 정상 결과로 출력한다. 오래된 자료만 있거나 최신 관측 종목의 이력이 짧아도 기준일을 바꾸거나 이전 날짜 집단으로 자동 후퇴하지 않는다.
- 참조 날짜는 저장된 관측에서 정한 비교 종점이다. 공식 최종 거래일이나 시장 전체 자료 완전성으로 표현하지 않는다.
- 60구간 수익률을 선택했다면 그 지표만 계산 가능하면 된다. 252구간 지표의 null이나 입력 features.complete=false 자체를 일괄 탈락 사유로 사용하지 않는다.
- pending/in_progress/failed/unsupported/empty, 선택 지표 자료 부족, 종점 불일치, 허용 가격 경과일 초과 등을 기계용 사유 코드와 한국어 설명으로 보존한다. 기존 원천·지표 불가 사유도 유지한다.
- 평가 불가 지표를 0으로 바꾸지 않는다. 정상 0 수익률·0 변동성·0 최대낙폭은 유효한 값이다. 영숫자 코드와 선행 0을 보존하며 KoreanStock의 숫자 코드로 강제 변환하지 않는다. 식별자가 없는 unsupported 대상도 결과에서 삭제하지 않는다.

4. 순위와 선정 규칙

- 평가 가능한 종목만 선택 지표의 정책 방향으로 정렬한다. 동점은 유효한 short_code의 ASCII 오름차순으로 결정한다. 입력 순서와 ordinal을 동점 선택 기준으로 사용하지 않는다.
- 원점수 동률에는 같은 `metric_rank`를 부여한다(경쟁 순위: 1, 1, 3). 최종 정렬 순번 `selection_order`는 1부터 유일하게 부여한다.
- 최종 정렬의 앞에서 최대 top개를 선정한다. 동률로 top을 초과해 채우지 않는다. 평가 가능 후보가 적으면 있는 후보만 선정하고 shortfall을 남긴다. 전원 평가 불가이면 selected_codes는 빈 목록이다.
- 종목 상태는 `selected`, `not_selected`, `unavailable`로 구분한다. 순위 밖 후보도 점수·순위를 유지하고, 평가 불가 후보는 순위를 null로 둔다. 선정·순위 밖·평가 불가의 사유를 구분한다.
- 모든 입력 종목을 candidates에 원래 순서로 보존하고, selected_codes는 최종 선정 순서로 별도 제공한다. 요청 top, 평가 가능 수, 선정 수, 미선정 수, 평가 불가 수, shortfall을 일관되게 기록한다.
- `evaluation_complete`는 모든 입력 종목을 순위 평가할 수 있을 때 true, `selection_filled`는 선정 수가 요청 top과 같을 때 true, 결과 `complete`는 두 값의 AND로 정의한다. 원천 features.complete는 별도 출처 정보로 보존한다.

5. 입력 검증과 증거 보존

- 입력 파일을 한 번 읽은 바이트로 SHA-256과 파싱을 수행한다. 같은 파일을 해시용·파싱용으로 재개방하지 않는다.
- 기존 모델을 재사용하되 새 입력 경계에서 일관성을 검증한다. 지원 schema/policy 버전, 정확한 8개 지표 조합과 중복, ordinal 및 유효 종목코드의 중복, as_of와 요청 기간, 관측 수·사용 기간·last_close·가격 경과일, 상태·available·value·reason·complete의 모순을 확인한다. 유효한 기존 부분 결과는 정상 입력으로 받아야 한다.
- JSON 중복 키, 비유한 값, Decimal 필드의 float/bool, 구조 누락이나 모순을 임의 보정하거나 평가 불가로 숨기지 않고 입력 오류로 거부한다. 형식상 모순과 정상적인 자료 부족을 구별한다.
- 파일 읽기 실패는 저장 오류, 읽은 JSON의 파싱·내용·정책 오류는 입력 오류다. 오류 메시지에 입력 전체나 traceback을 노출하지 않는다.
- 결과에 입력 파일의 정확한 바이트 해시, history/discovery ID, 입력 기준일·계산 시각, feature schema/policy, 선정 정책과 모든 파라미터, reference_price_date, 평가 시각을 보존한다.
- 종목별 target·ordinal·source_status, source_price_sha256·consumed_input_sha256, 선택 지표와 원점수·실제 창·관측 수·가격 경과일, 상태·순위·사유를 보존한다.
- 입력 파일 해시는 이 선정에 사용한 파일의 식별 증거다. 원천 DB를 다시 읽지 않으므로 원천 가격 해시를 재검증했다고 표시하지 않는다.
- 선정 범위는 제공된 features JSON에 포함된 후보로 한정한다. 시장 전체 비교나 point-in-time 백테스트 완전성을 주장하지 않는다. 기존 `trading_day_completeness=unverified`, `point_in_time_backtest_guaranteed=false`와 가격수익률의 배당 제외 한계를 유지한다.
- 평가 시각이나 입력 features.calculated_at만 바뀌면 선정 결과·순위는 같아야 한다. 평가 시각을 가격 신선도 기준으로 사용하지 않는다. 같은 입력 바이트·정책·주입 시각이면 결과 JSON 바이트가 동일해야 한다.

6. 구조와 출력

- 순수 선정 함수, 검증된 정책·결과 도메인, 파일 I/O 서비스, CLI를 분리한다. 후보 평가를 Typer 명령 안에 구현하지 않는다.
- 권장 배치는 `domain/candidate_selection.py`, `selection/` 패키지, CLI 등록부다. 기존 구조에 맞춘 최소한의 조정은 허용한다.
- 후속 배분 엔진이 selected_codes와 평가 근거를 읽을 수 있는 인터페이스를 제공한다. 현재 배분 엔진은 6자리 숫자 코드만 허용하므로 기존 계약을 변경하거나 선정 결과를 자동 전달하지 않는다.
- stdout은 결과 JSON이다. --output에는 같은 JSON을 기존 원자적 저장 유틸리티로 저장하고 기존 파일을 덮어쓰지 않는다. 부분 결과도 출력·저장한다.
- 종료 코드는 완전 결과 0, 부분 결과 2, 입력·정책 오류 65, 입력 읽기·출력 저장 오류 66이다. 필수 옵션 누락 등 Typer 문법 오류의 2는 JSON 부분 결과와 구별해 문서화한다.
- 기존 파일을 덮어쓰지 않는 계약, Decimal 문자열 직렬화, 네트워크 없이 동작하는 계약을 유지한다.

7. 검증과 문서

다음 위험을 확인하는 의미 있는 테스트를 작성한다.

- 수익률 내림차순·변동성 오름차순·음수 최대낙폭 방향, 0 값의 정상 평가.
- 동점의 동일 metric_rank와 결정적 top 경계, 입력 순서 변경에도 동일한 선정, 영숫자·선행 0 보존.
- 선택 지표만 충분한 부분 features 입력, 원천별 불가 상태, 전원 불가, top 미달 및 각 complete 플래그.
- 종점 불일치, 가격 경과일 한도와 한도+1, 참조 종점이 metric/top/평가 시각에 독립적임, 최신 관측 종목의 짧은 이력 때문에 과거 집단으로 후퇴하지 않음.
- 중복 지표·ordinal·유효 코드·JSON 키, 잘못된 지표 구성·정책·기간·상태·수치에 대한 입력 오류. 기존 feature CLI가 만든 정상 완전·부분 JSON의 실제 연동도 검증.
- 동일 입력 파일 바이트 사용, 원천 파일 불변, JSON 왕복, 주입 시각에 따른 재현성, 전역 Decimal 문맥 변경에 대한 독립성.
- 자격증명·OAuth·HTTP 호출 차단, JSON stdout과 내보낸 바이트 일치, 기존 출력 보존, 원자적 기록 실패 전파.

README와 `docs/candidate-selection.md`에 사용법·정책·가격 종점·상태·부분 결과·종료 코드·출처 및 해석 한계를 기록한다. 소규모 합성 examples를 추가해 선정·순위 밖·평가 불가를 확인할 수 있게 한다. 수익성 우수나 실전 투자정책 검증 완료로 표현하지 않는다.

기준 테스트는 1,902개 통과다. 기존 CI 설정을 유지하고 Ruff, mypy src, 전체 pytest, 변경분 공백 검사를 실행한다. 수정 후 영향을 받는 검증을 수행하되, 동일 코드에 불필요하게 전체 테스트를 반복하지 않는다. 무관한 기존 파일을 포맷하거나 검사 설정을 완화하지 않는다.

8. 완료 보고와 검토 ZIP

브랜치·기준 HEAD, 미추적 신규 파일을 포함한 변경 파일 목록과 증감, 검증 명령·결과·전체 테스트 수, 사용 예시, 남은 제한을 보고한다. 사용자 자료 보존 여부와 커밋·푸시·PR 생성 여부도 정확하게 밝힌다.

`phalanx-candidate-selection-review.zip`을 저장소 밖 검토용 경로에 만든다. 실행·검토에 필요한 src/tests/docs/examples, README.md, pyproject.toml, uv.lock, .gitignore, 값이 비어 있는 .env.example, CI 설정 및 REVIEW_CONTEXT.txt·TRACKED_CHANGES.diff를 포함한다. 새 미추적 구현 파일도 누락하지 않는다. REVIEW_CONTEXT에는 기준 커밋·브랜치·변경 범위·검증 결과와 테스트한 파일이 ZIP에 동일하게 들어갔다는 확인을 기록한다.

.git, .venv, 캐시, 실제 자격증명·계좌 데이터·DB·수집 원문, reports/, research/는 포함하지 않는다. 생성한 ZIP의 절대 경로를 보고하고 사용자 검토를 기다린다.
