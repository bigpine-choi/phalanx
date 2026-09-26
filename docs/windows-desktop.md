# Windows 편성실 v1

Windows 네이티브 Python에서 pywebview + Edge Chromium(WebView2) 독립 창을 엽니다.
기존 Python 입력 준비·공분산·ERC 서비스를 호출하며 브라우저에서 금융 계산을 하지 않습니다.
계좌·인증·KIS API·주문·후보 발굴·NAV·설치 프로그램·자동 업데이트는 포함하지 않습니다.

## 실행 환경 분리

WSL의 `.venv`를 Windows에서 재사용하지 마세요. 저장소/검토 ZIP을 **Windows 로컬
드라이브의 별도 폴더**에 풀고 Windows Python 3.12와 WebView2 Evergreen Runtime을
설치하세요. 아래 명령은 해당 폴더의 **Windows PowerShell**에서 실행합니다.

```powershell
$env:UV_PROJECT_ENVIRONMENT = ".venv-windows"
$env:UV_NO_ENV_FILE = "1"
uv sync --locked --extra desktop --group dev --python 3.12
uv run --locked --extra desktop python -m phalanx.desktop
```

`phalanx-desktop` 진입점도 제공합니다. `phalanx.cli`를 가져오지 않습니다.
`webview.start(gui="edgechromium")`를 주 스레드에서 호출하며 initialized 이벤트에서도
실제 renderer를 검사합니다. WebView2를 사용할 수 없으면 다른 엔진으로 창을 열지 않고
설치 안내와 함께 종료합니다. 설정과 WebView2 캐시는 ACL을 검사한
`%LOCALAPPDATA%\Phalanx` 및 그 하위 경로에 저장합니다.
사용자명·체크아웃 경로는 제품 코드에 하드코딩하지 않았습니다.

공식 안내: [pywebview 설치](https://pywebview.flowrl.com/guide/installation.html),
[사용법](https://pywebview.flowrl.com/guide/usage.html),
[메모리 HTML 구조](https://pywebview.flowrl.com/guide/architecture.html),
[API와 이벤트](https://pywebview.flowrl.com/api/),
[WebView2 Runtime](https://developer.microsoft.com/microsoft-edge/webview2/).

## 두 사용자 흐름

- **저장 결과 열기:** 목표비중 JSON 선택 → 선택적으로 원본 selection JSON 연결 →
  편성실 열기. 원본 SHA-256이 맞아야 기업명을 연결하며, 미연결 시 이름 미확인을 표시합니다.
- **새 목표비중 계산:** selection JSON과 Windows 로컬 history DB 선택 → 목표비중 계산 →
  같은 창의 편성실 → 결과 JSON 저장. 중간 파일을 복사하거나 다시 업로드하지 않습니다.

처리 단계와 실행 중 상태만 표시하고 가짜 진행률을 만들지 않습니다. `input_unavailable`,
`common_failure`, `partial`, `failed`도 진단을 갖춘 결과이며 전체 성공으로 표시하지 않습니다.
저장 여부는 계산 상태와 분리됩니다. 저장 충돌/실패 후 화면과 원본 JSON bytes를 유지하며
다른 파일 이름으로 재시도할 수 있습니다. 기존 파일을 덮어쓰지 않습니다.

시나리오·종목 카드를 키보드로 선택할 수 있습니다. 최초 실행과 결과 화면 교체는 무음입니다.
음량·모션 축소만 설정에 저장하며 음향은 직접 켜야 합니다. 최소화·화면 숨김 시 무음 처리하고
복원 시 자동 재생하지 않습니다. 설정 손상은 기본값과 안내로 복구합니다.
계산 중 닫기는 완료 후 종료이며 강제 스레드 종료나 중간 취소 버튼을 제공하지 않습니다.

## 독립 검토 반영

작업 상태 조회 연결이 실패하면 실행 중인 작업과 입력 잠금을 유지합니다.
**작업 상태 다시 확인**은 같은 작업을 다시 조회하며 새 계산을 만들지 않습니다.
새 요청을 거절할 때는 그 요청의 generation을 반환하고, 기존 작업 식별정보는 별도 필드로
분리합니다. 늦은 응답이 다른 입력이나 결과를 덮어쓰지 않는 계약은 유지합니다.

Windows 디렉터리 핸들에는 `FILE_LIST_DIRECTORY`를 포함합니다. 메타데이터 접근권한만으로는
공유 검사에 참여하지 않는다는 [MS-FSA 계약](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-fsa/8c0e3f4f-0729-49f4-a14d-7f7add593819)을 반영했습니다.
자식 파일 핸들 없이 디렉터리 guard만 유지한 native 테스트에서 충돌 접근·rename·경로 교체를
검증하고, 같은 보호 아래 정상 저장·원자적 완료·ACL·충돌·실패 정리를 함께 검사합니다.

검토 ZIP에는 공개 빈 `.env.example`, `docs/plans/kis-account-snapshot.md`, discovery의
`kospi.hex`·`kosdaq.hex`를 정확한 경로로 포함합니다. 비밀 설정과 사용자 자료는 제외하며,
공개 설정 템플릿에 실제 값이 들어 있으면 ZIP 생성을 거절합니다. 추출본은 자체 가상환경과
`git init`만으로 전체 테스트를 실행합니다. staging·commit은 필요 없습니다.

## 서비스와 파일 경계

`HistoryReader` Protocol → `AllocationInputService.prepare_bytes` →
`AllocationTargetsService.calculate_bytes` 경로를 사용합니다. 기존 path API는 유지합니다.
작업에서 한 번 읽은 selection bytes를 계산과 이름 연결에 그대로 사용합니다.
`AllocationTargetsService` 내부에서 입력을 준비하므로 준비를 중복 호출하지 않습니다.
금융 계산·Decimal 문맥·시나리오 순서·실패 진단·provenance는 기존 서비스를 그대로 사용합니다.

Linux CLI는 기존 POSIX repository를 주입합니다. Windows 앱은
`WindowsHistoryRepository`를 주입하며 공통 schema/version/application_id, 작업·종목·ordinal,
순서·result 연결 검증을 공유합니다. Windows/백업의 테이블 구조 검사는 엄격하게 적용하고,
Linux 저장소는 기존 trigger·쓰기 실패 처리와 메타데이터 검증 계약을 유지합니다.
원천 해시는 기존 domain/입력 검증 경로를 거칩니다.
네이티브 handle이 DB와 모든 상위 경로를 고정하고 DB 쓰기·교체를 차단한 동안
`mode=ro&immutable=1`, `query_only`, 한 SQLite transaction에서 읽습니다.
실제 SQLite header도 검사하며 DELETE 형식의 완료된 백업만 허용합니다. 입력 생성/수정은 없습니다.

Windows v1 경로 정책:

- 고정된 로컬 드라이브의 절대 경로만 지원합니다. UNC/WSL 공유/장치/ADS/SUBST 별칭 경로는 거절합니다.
- 파일과 상위 디렉터리의 reparse point, 파일 hard link, 모호한 예약 이름을 거절합니다.
- 입력 handle은 FILE_SHARE_READ만 허용합니다. 다른 writer가 이미 열고 있으면 실패합니다.
- `-journal`, `-wal`, `-shm`이 있으면 거절합니다. 작업 중 sidecar가 생겨도 실패합니다.
- 결과 임시 파일을 CREATE_NEW로 만들 때부터 현재 사용자·SYSTEM·Administrators만 허용하는
  DACL을 부여하고 handle로 소유자·실효 ACL을 검사합니다. chmod를 Windows 보안으로 쓰지 않습니다.
- flush와 검증 후 `NtSetInformationFile(FileRenameInformation)`에 파일 이름만 전달하고
  `RootDirectory=NULL`로 두어 같은 디렉터리 안에서 원자적으로 이름을 변경합니다.
  [공식 rename 계약](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/ntifs/ns-ntifs-_file_rename_information)에 따라 상위 guard를 유지합니다.
  기존 결과를 덮어쓰지 않으며 동시 저장은 한 번만 성공하고 실패한 temp는 handle로 삭제합니다.
  정전 시 디렉터리 메타데이터 영속성까지 보장한다고 주장하지 않습니다.

관리 설정은 private 앱 디렉터리에 원자적으로 갱신하며 인증정보·결과·선정 파일을 섞지 않습니다.
사용자가 지정한 결과 경로는 native 파일 선택으로 허용합니다. bridge는 opaque 파일 토큰만
수락하며 shell 명령·Python 실행·범용 파일 읽기 API를 노출하지 않습니다.

화면 shell에는 패키지 소유 코드만 들어가고, 기존 편성실은 `sandbox="allow-scripts"`
iframe의 메모리 `srcdoc`에 표시합니다. same-origin/탐색/popup 권한은 부여하지 않습니다.
세대/작업 ID로 늦은 응답을 거절하며 화면 교체 시 음향·timer를 dispose하고 iframe을 제거합니다.
기존 오프라인 CLI 렌더링의 의미와 보안 정책은 유지됩니다.

## WSL history를 Windows로 옮기기

열린 DB와 sidecar를 단순 복사하지 마세요. 다음은 **WSL Bash** 명령입니다.
원본 저장소의 POSIX 검증을 통과한 읽기 연결에서 SQLite backup API로 일관된 백업을 만듭니다.

```bash
uv run --locked python -m phalanx.desktop.export_history \
  --source "$HOME/.local/share/phalanx/market-data/history.sqlite3" \
  --output /tmp/phalanx-history-export/history.sqlite3
```

기존 출력은 덮어쓰지 않습니다. 명령이 완료된 뒤 출력 파일 **하나**와 해당 selection JSON을
Windows 로컬 폴더로 옮기세요. DB export가 끝나기 전에 복사하지 마세요.
Windows 앱에 `\\wsl.localhost\...` 원본을 직접 지정하는 흐름은 v1에서 지원하지 않습니다.

## 검증 명령

**WSL Bash**, GUI 의존성 없이:

```bash
uv run --locked ruff check .
uv run --locked mypy src
uv run --locked pytest -q
git diff --check
```

**Windows PowerShell**, 별도 가상환경에서 이번 이식 범위만:

```powershell
$env:UV_PROJECT_ENVIRONMENT = ".venv-windows"
$env:UV_NO_ENV_FILE = "1"
uv sync --locked --extra desktop --group dev --python 3.12
uv run --locked --extra desktop python -c "import phalanx.desktop; from phalanx.portfolio.allocation_targets.service import AllocationTargetsService; print('native import OK')"
uv run --locked --extra desktop pytest -q tests/test_desktop_application.py tests/test_desktop_storage.py tests/test_desktop_runtime.py tests/test_desktop_view.py tests/test_history_reader.py tests/test_allocation_bytes.py tests/test_windows_files.py tests/test_windows_history_repository.py
uv run --locked --extra desktop python -m phalanx.desktop
```

Linux 기존 helper를 Windows에서 가져오지 않습니다. `desktop_helpers`는 실제 기존 서비스로 만든
합성 HistoryView/selection 원본을 사용해 OS 독립 테스트 DB를 만듭니다. DB 생성은 테스트용뿐입니다.
동일 OS/의존성의 직접 서비스와 application 결과는 byte equality로 검증합니다.
플랫폼 간 BLAS·버전 차이에 대해 재계산 JSON의 byte equality를 강요하지 않습니다.

실제 독립 창 수동 확인:

1. 저장 결과와 원본 selection 연결/미연결, 잘못 연결한 selection, 없는/무효 DB를 확인합니다.
2. 합성 selection+history 계산 후 네 시나리오·기업명·비중·근거를 확인하고 저장/재열기합니다.
3. 두 번 클릭, 계산 중 닫기, 오류 후 재시도, 닫은 뒤 프로세스 종료와 앱 재실행을 확인합니다.
4. 1440×900과 1280×720에서 긴 한글 이름·스크롤·실패 상태와 Tab/화살표 키를 확인합니다.
5. 음향을 직접 켠 뒤 최소화/복원·결과 교체·닫기를 확인하고 **실제 청취**를 기록합니다.
6. Windows 디스플레이 배율과 앱 확대율, Python/pywebview/numpy 버전을 기록합니다.

1차 검토에서 보고한 Windows 애플리케이션 제어 오류 **4551**은 이번 검토에서 재현되지
않았습니다. 애플리케이션 제어 정책을 변경하지 않고 허용된 네이티브 Python으로 Win32
파일 보호·저장과 데스크톱 이식 범위 테스트를 실행했습니다. 실제 WebView2 검증에는
`tools/check_desktop_native.py`가 앱의 진입점과 native 파일 대화상자를 사용합니다.
검증용 합성 입력과 설정은 지정한 출력 폴더 안에만 생성합니다.

```powershell
uv run --locked --extra desktop python tools/check_desktop_native.py --output "$env:TEMP\phalanx-native-review"
uv run --locked --extra desktop python tools/check_desktop_native.py --output "$env:TEMP\phalanx-native-review" --relaunch
```

같은 4551 오류가 발생하면 차단된 `python.exe`의 전체 경로와 원본 오류를 기록하고,
정책에서 허용한 Python 설치본을 사용하세요. 보안 정책을 끄거나 우회하지 않습니다.
Linux Chromium 캡처는 실제 WebView2 검증과 구분하며 자동 음향 상태 검사로
**실제 청취**를 대신하지 않습니다. 최종 검사 수치·화면 배율·미완료 항목과 캡처 정보는
검토 ZIP의 `REVIEW_CONTEXT.txt`를 확인하세요.

## 실제 작업 트리로 검토본 만들기

`git archive HEAD`는 미커밋 변경을 포함하지 않습니다. 아래 도구는 추적/새 파일을 직접 읽어
소스·테스트·합성 fixture·자산·lockfile·diff와 SHA-256 manifest를 만듭니다.
기존 reports/research, 개인 지시문, .env, 인증정보, 가상환경은 allowlist에 없습니다.

```bash
python3 tools/prepare_desktop_review.py \
  --output /tmp/phalanx-windows-desktop-v1-review-v2.zip \
  --context /tmp/phalanx-desktop-review-v2/REVIEW_CONTEXT.txt \
  --evidence /tmp/phalanx-desktop-review-v2/evidence
```

ZIP에 포함된 작업 트리를 Windows 로컬 폴더에 풀어 위 PowerShell 명령으로 검증하세요.
원본 사용자 자료를 포함하거나 WSL 가상환경을 공유할 필요가 없습니다.
