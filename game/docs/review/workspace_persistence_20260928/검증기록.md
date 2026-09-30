# 관심종목·리서치 노트 저장 · 2026-09-28

기존 Godot 투자 워크스페이스에 **이 기기에서의 자동 저장과 재실행 복원**을 구현했다. 게임 미술, 가상 시세·계좌 계산과 실제 주문 미연결 상태는 유지했다.

## 사용법

1. 시장 화면에서 종목을 선택하고 **★ 관심 / ☆ 추가**로 관심종목을 해제하거나 추가한다.
2. 관심목록에서 사라진 종목은 **전체 보기**나 종목명·코드 검색으로 다시 찾는다. 검색은 관심 여부와 관계없이 현재 제공하는 전체 5개 샘플 종목을 대상으로 한다.
3. 리서치 탭에서 노트를 입력한다. 입력이 잠시 멈추면 약 0.5초 후 자동 저장하며, 종목/탭 변경·대시보드 닫기·정상 종료 때 남은 입력을 저장한다.
4. 앱을 다시 열면 관심종목과 종목별 노트가 복원된다. 관심종목을 모두 해제한 빈 목록도 그대로 유지한다. 관심 해제가 노트를 지우지는 않는다. 노트를 비우면 빈 상태가 저장된다.

첫 실행은 기존 샘플 5개가 관심종목으로 시작한다. 저장 상태는 하단과 노트 아래에 표시하며, 쓰기 실패 시 입력을 유지하고 **저장 재시도**를 제공한다.

## 저장 범위와 위치

- 저장 항목: 종목 코드로 관리하는 관심목록, 종목별 리서치 노트. 목표 비중·계좌·차트 선택은 기존 실행 중 상태 계약을 유지하며 이번 영구 저장 대상이 아니다.
- 기본 위치: Godot `user://investment_workspace.json`. 이 프로젝트의 Windows 기본 경로는 `%APPDATA%\Godot\app_userdata\Phalanx Headquarters\investment_workspace.json`이다. 화면 하단 저장 상태에 마우스를 올리면 실제 경로가 나온다.
- UTF-8 JSON, 버전 1. 노트당 최대 100,000자, 파일 최대 4 MiB. 한도를 넘으면 잘라 저장하지 않고 오류를 표시한다.
- 임시 파일을 쓰고 다시 읽어 확인한 뒤 본 파일로 교체한다. 이전 정상 저장본은 `.bak`에 보관한다.
- 본 파일 손상/유실 시 정상 백업이 있으면 복원하고 화면에 알린다. 복구 후 저장할 때 손상 원본을 `.damaged-*`로 남긴다. 복원 가능한 사본이 없거나 새 버전 파일을 만난 경우 기존 파일을 덮어쓰지 않는다.
- 다른 창에서 파일이 바뀐 것이 감지되면 오래된 창의 덮어쓰기를 막고 안내한다. 여러 창의 동시 편집을 병합하는 기능은 아니다.
- 서버 전송·계정 동기화·암호화·내보내기는 이번 범위가 아니다. 강제 종료/정전 순간의 아직 저장되지 않은 입력까지 보장하지 않는다. 정상 종료에서 마지막 대기 입력 저장은 별도로 검사했다.

## 확인 결과

| 검사 | 결과 |
| --- | --- |
| 새 저장 기능 | Headless 45 / GPU 45 PASS. 정확한 한국어·여러 줄·기호 복원, 빈 목록, 노트 삭제, 손상 복구와 원본 보존, 버전/형식/용량 제한, 다른 창의 이전 상태, 쓰기 실패/재시도, 자동 저장과 종료 직전 입력 |
| 기존 워크스페이스 | Headless 43 PASS. 선택·차트·검색·탭·배치·모달 입력 경계 |
| 기존 가상 계좌/대시보드 | `smoke_test.gd` PASS. `demo_data.gd`는 작업 시작 사본과 해시가 동일 |
| 기존 게임↔투자 화면 왕복 | Headless 157 / GPU 162 PASS, Godot 합성 입력 |
| 서로 다른 실행 프로세스 | 첫 프로세스에서 관심 2개 해제·SK하이닉스 노트 입력 후 대기 타이머 전에 정상 종료. 다음 프로세스에서 관심 3개와 동일 노트를 복원해 GPU 화면 저장 |
| 실제 Windows 창 | 1280×720. 컴퓨터 사용 도구로 삼성전자 관심 해제→한국어 노트 입력→Alt+F4→별도 새 실행→관심 4개와 같은 노트 복원 확인. 테스트 전용 저장 파일 사용 |
| 해상도 | 1440×960, 1280×720, 900×680에서 시장/포트폴리오/리서치 총 9장 GPU 캡처. 새 버튼·저장 상태·좁은 화면을 확인 |

자동 검증은 합성 입력, 실제 창 검수는 컴퓨터 사용 도구 조작이다. 사람이 직접 수행한 검증이라고 표기하지 않는다. 기본 사용자 저장 파일에는 테스트 메모를 기록하지 않았다. 자동 실행 환경은 Windows 인증서 저장소 오류를 출력하지만 검사는 정상 종료했으며, 실제 데스크톱 검수 로그에는 해당 오류가 없었다. 파싱 오류와 `git diff --check` 문제는 없다.

## 변경 파일과 재검증

- 새 `scripts/workspace_store.gd`: 파일 읽기/검증/쓰기/백업/복구 책임.
- `scripts/headquarters.gd`: 관심종목 편집, 자동 저장, 상태/재시도, 불러온 노트 연결.
- `scripts/dashboard_overlay.gd`: 대시보드를 닫기 전 대기 입력 저장.
- 새 `tests/workspace_persistence_test.gd`, `workspace_restart_probe.gd`: 저장 오류·경계·실행 프로세스 간 복원 검사.
- 기존 `terminal_workspace_test.gd`, `smoke_test.gd`, `quarter_flow_test.gd`, `terminal_review.gd`: 검사 시작 시 실제 사용자 파일과 분리된 저장 경로를 선택한다. 기존 검사 의미를 유지했다.
- `README.md`, `docs/SESSION_HANDOFF.md`, `docs/WORKSPACE_PERSISTENCE_VALIDATION.md`: 현재 사용법과 단계 기록.

프로젝트 폴더에서 다음 검사를 실행할 수 있다. 각 회귀 검사는 별도 임시 파일을 사용한다. `PHALANX_WORKSPACE_PATH` 환경 변수는 검수용 프로필 위치를 명시할 때만 사용한다.

```powershell
$godot = 'C:\Users\hanso\Tools\Godot\Godot_v4.7.2-stable_win64_console.exe'
& $godot --headless --path . --script res://tests/workspace_persistence_test.gd
& $godot --headless --path . --script res://tests/terminal_workspace_test.gd
& $godot --headless --path . --script res://tests/smoke_test.gd
& $godot --headless --path . --script res://tests/quarter_flow_test.gd
```

화면 확인은 기존처럼 F5→사령부 지도, 또는 `headquarters.tscn`을 열고 F6이다. 브랜치 `feature/camp-art-pass-b`, HEAD `344b8aa` 유지. commit·merge·push·stage·reset은 하지 않았다.

저장 API의 기준은 Godot 공식 [FileAccess](https://docs.godotengine.org/en/stable/classes/class_fileaccess.html)와 [DirAccess](https://docs.godotengine.org/en/stable/classes/class_diraccess.html) 문서다.
