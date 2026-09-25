# Formation Room 합성 예제

저장소 루트에서 실행한다. 개발 의존성은 `uv sync --locked --group dev`로 준비한다. 출력은 **아직 없는 새 디렉터리**로 지정한다.

```bash
PYTHONPATH=tests uv run python examples/formation-room/generate.py \
  --directory /tmp/phalanx-formation-demo --case all
```

`tests/allocation_targets_helpers.py`의 고정 seed 합성 가격으로 SQLite를 만들고, 실제 PR #23의 features→selection→input→risk→ERC 경로를 실행한다. 원천 history target에 가상의 합성 이름을 부여한 뒤 계산 결과를 저장하고, 생성한 원본 selection을 연결하여 Formation Room 서비스로 HTML을 만든다. 이름·선정 결과·해시는 사후 편집하지 않는다. 성공 예제는 서로 다른 **6종목·종가 505개·수익률 504개**를 사용한다. 모든 가격·종목 편성은 합성 연구 예제이며 실제 투자 포트폴리오가 아니다.

| `--case` | 저장 결과 상태 | 성공 시나리오 수 | 생성 방법 |
| --- | --- | --- | --- |
| `succeeded` | `succeeded` | 4 | 6종목의 비퇴화 합성 가격 |
| `five-assets` | `succeeded` | 4 | 5종목, 각 목표비중 20% 경계 |
| `unavailable` | `input_unavailable` | 0 | 종가 504개·수익률 503개로 준비 불가 |
| `common-failure` | `common_failure` | 0 | 일정한 합성 가격의 위험 snapshot 실패 |
| `failed` | `failed` | 0 | 4종목 × 상한 20%로 배분 불가능 |
| `partial` | `partial` | 3 | `fast_iewma` solver 실패를 명시적으로 주입 |
| `long-names` | `succeeded` | 4 | 원천 단계에서 긴 가상 이름 부여 |
| `no-selection` | `succeeded` | 4 | 선택 옵션 미제공 호환 검사; 이름 미확인 |
| `missing-names` | `succeeded` | 4 | 연결된 원천 target.name이 null |
| `duplicate-names` | `succeeded` | 4 | 서로 다른 코드의 가상 이름 중복 |
| `script-names` | `succeeded` | 4 | 원천 이름에 HTML/script 문자열; 비실행 검증 |

부분 성공 예제는 계산 함수의 테스트 경계에서 `ConstrainedErcCcdConvergenceError`를 한 시나리오에 주입한다. 다른 세 시나리오는 기존 기본 solver가 실제로 계산한다. 저장된 JSON의 상태나 비중을 사후 편집하지 않는다. `synthetic-manifest.json`에 합성 여부·주입 방법·상태·입력과 HTML의 SHA-256을 기록한다. 공통 실패와 전체 실패는 기존 엔진에서 발생한 실제 계산 실패다.

각 예제 디렉터리에는 `synthetic-allocation-targets.json`, `formation-room.html`, `synthetic-manifest.json`과 재현용 합성 원천 파일이 있다. 생성기가 `FormationRoomPresentation(synthetic_demo=True)`를 명시적으로 전달해 화면에 항상 **합성 데이터 데모** 배지를 표시한다. 일반 파일은 이름에 synthetic이 있어도 합성으로 판정하지 않는다. `no-selection`만 호환 검사 목적으로 연결을 생략하고 나머지 예제는 자신이 생성한 원본 selection을 전달한다. 검토 ZIP에는 합성 화면·검토 근거만 넣으며 DB와 가격 원문을 넣지 않는다. 생성기는 기존 디렉터리와 출력 파일을 덮어쓰지 않는다. 한 사례만 필요하면 `--case partial`처럼 지정한다.

일반 저장 결과에서 이름을 연결하는 CLI 호출은 다음과 같다. 이 일반 CLI는 파일의 합성 여부를 추측하지 않는다. 합성 배지가 필요한 재현은 위 예제 생성기를 사용한다.

```bash
uv run phalanx portfolio formation-room \
  --targets /absolute/private/allocation-targets.json \
  --selection /absolute/private/selection.json \
  --output /absolute/private/formation-room.html
```

유효한 실패 결과를 화면으로 생성한 경우에도 Formation Room 종료 코드는 0이다. 입력 오류는 65, 읽기·저장 오류 및 기존 출력 파일은 66이다. 예상하지 못한 내부 오류는 원본 예외·traceback 없이 70으로 구별한다. 이 명령은 저장 결과를 읽기만 하며 DB·위험모형·solver를 다시 호출하지 않는다.

## WSL에서 Windows로 열기

코드는 브라우저를 자동으로 실행하지 않는다. WSL 터미널에서 사용자가 다음 명령으로 탐색기를 열고 `formation-room.html`을 브라우저로 연다.

```bash
explorer.exe "$(wslpath -w /tmp/phalanx-formation-demo/succeeded)"
```

WSL 경로를 브라우저가 열지 못하면 탐색기에서 HTML 한 파일만 Windows의 새 폴더에 복사한 뒤 연다. HTML 안에 화면용 종목·비중·일부 근거가 포함되므로 실제 결과 파일을 공유할 때는 원본 JSON과 같이 취급한다. 서버나 인터넷 연결은 필요 없다.

처음에는 무음이다. 화면 설정에서 명시적으로 소리를 켜거나 미리듣기를 실행한다. 배경음은 **코드로 합성한 프로토타입 배경음악**이며 전용 음악 생성 도구의 AI 작곡 완성곡이 아니다. 브라우저의 자동 재생·`file://` 저장 정책에 따라 설정 저장과 음향 사용 가능 여부가 달라질 수 있다. 페이지를 다른 탭으로 숨기면 음악은 멈추며 복귀 후 수동으로 재개한다.

## 직접 확인하기

성공 화면을 1440×900, 1280×720에서 각각 열어 탭 네 개·종목 카드·상세·접히는 근거·설정을 확인한다. Tab과 방향키로 이동하고 시나리오를 바꿔도 선택 종목이 유지되는지, 실패 탭의 구성도·비중·변동성이 이전 성공 값으로 남지 않는지 확인한다. 누적 막대와 카드를 선택해 같은 종목 상세가 강조되는지 확인한다. 모든 시나리오에서 같은 코드의 색상이 유지되어야 한다. 긴 이름·이름 미확인 화면도 확인한다. 부분 성공 예제의 두 번째 탭은 실패해야 한다.

음향 시작 대기 중 전체 무음/취소가 가능한지 확인한다. 음향 켜기·효과음/배경음 음량·음악 시작/정지·전체 무음·모션 축소를 조작한다. 빠르게 연속 클릭하거나 음악을 여러 번 재시작했을 때 과도한 중첩이 없는지 직접 듣는다. 페이지를 숨겼다가 돌아온 뒤 자동으로 음악이 재개되지 않는지, 다시 열어도 사용자 동작 전 무음인지 확인한다. 개발자 도구에서 외부 요청과 콘솔 오류도 확인한다. 이 절차는 실행 안내이며 실제 검증 결과를 대신하지 않는다.

선택적으로 실제 Chromium 검증 스크립트를 실행할 수 있다. Playwright와 브라우저는 **별도 검증 환경**에 설치하며 제품 의존성이나 JS 빌드 체인을 추가하지 않는다. 아래 준비 단계는 도구를 다운로드한다. 준비 후 화면 검증은 서버 없이 `file://`와 오프라인 브라우저 context에서 실행한다.

```bash
uv venv /tmp/phalanx-browser-venv
uv pip install --python /tmp/phalanx-browser-venv/bin/python playwright
/tmp/phalanx-browser-venv/bin/python -m playwright install chromium
/tmp/phalanx-browser-venv/bin/python tests/browser/verify_formation_room.py \
  --directory /tmp/phalanx-formation-demo \
  --artifacts /tmp/phalanx-formation-browser-review
```

스크립트는 원본 JSON과 표시 수치, 탭·키보드·실패 상태·설정·모션, 외부 요청·콘솔 오류를 확인하고 화면 캡처와 실행 보고서를 남긴다. 사용자는 캡처를 직접 확인하고 실제 출력 장치의 음향도 별도로 들어야 한다. 브라우저나 OS에 필요한 실행 라이브러리가 없는 환경에서는 해당 검증을 실행하지 못할 수 있다. Python pytest 통과와 브라우저 실행·청취 결과는 서로 구별한다.

화면은 저장된 연구 결과를 표시하는 오프라인 시제품이다. 데이터 재수집·실시간 분석·주문 기능은 없으며, 향후 Windows 설치형 앱의 내장 화면으로 발전시킬 예정이다. 입력 계약·표시 수치·음향 한계는 [상세 문서](../../docs/formation-room.md)를 참고한다.

같은 별도 Playwright 환경에서 음향을 검사하고 청취용 합성 WAV를 만든다.

```bash
/tmp/phalanx-browser-venv/bin/python tests/browser/verify_formation_room_audio.py \
  --html /tmp/phalanx-formation-demo/succeeded/formation-room.html \
  --artifacts /tmp/phalanx-formation-audio-review
```

`formation-room-synthetic-ambient-preview.wav`는 코드로 합성한 프로토타입 배경음악의 32초 재현 자료다. 기본 음악 루프의 선율·화성을 실제 OfflineAudioContext로 렌더링하고, 파일 끝에만 짧은 fade를 적용한다. 자동 검사는 파형·재생 수명주기를 확인하며 사람이 실제로 듣는 검증을 대신하지 않는다. 이 검토본에서는 실제 청취·Windows 브라우저·OS 탭 숨김을 확인하지 않았다. 숨김/BFCache는 브라우저 이벤트 주입으로 검사했다.

## 같은 상태의 화면 비교

시각 개선 전후를 비교할 때는 v2 검토 ZIP의 `review-artifacts/demos/`를 보존하고, 개선본 예제를 별도 디렉터리에 생성한다. 아래 스크립트는 양쪽 화면 데이터의 동일성을 먼저 확인하고 같은 시나리오와 종목을 선택한 뒤 두 해상도로 캡처한다. 입력 데이터가 다르면 비교를 거부한다.

```bash
/tmp/phalanx-browser-venv/bin/python tests/browser/verify_formation_room_visual.py \
  --before-directory /absolute/extracted-v2/review-artifacts/demos \
  --after-directory /tmp/phalanx-formation-demo \
  --artifacts /tmp/phalanx-formation-visual-comparison
```

성공·긴 이름·이름 미제공·부분 실패·설정 화면의 비교 갤러리와 측정 기록을 생성한다. 자동 검사는 데이터와 선택 상태·겹침·뷰포트 경계를 확인한다. 정렬의 자연스러움, 한글의 읽기 편함, 구성도→기업명→선택 상세로 이어지는 시선 흐름은 실제 캡처를 직접 검수하며 기능 검사 통과만으로 미적 완성도를 판정하지 않는다.
