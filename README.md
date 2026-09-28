# Phalanx · 투자 워크스페이스와 사령부

Windows Godot 4.7.2 프로젝트입니다. 작은 야영지에서 목적지를 클릭해 캐릭터를 이동하고, 사령부에 입장해 고정된 구도의 작전 지도를 선택하면 투자 대시보드를 엽니다.

**2026-09-28 설계 정정:** 기본 게임은 쿼터뷰, 사령부 내부는 고정시점입니다. 과거 문서의 ‘사령부 1인칭 자유 이동 유지’는 현재 요구사항이 아닙니다. 기존 1인칭 구현과 아트 패스 기록은 보존하되 새 기본 흐름과 분리합니다.

**리서치는 실제 한국투자증권 일봉과 삼성전자 공식 연간 재무자료를 표시합니다.** 시장·포트폴리오의 지수·가격·계좌·모의 계획은 가상 데이터이며 리서치 가격으로 재평가하지 않습니다. 실시간 현재가·계좌·주문은 미연결입니다.

## 현재 개발 초점 · 투자 워크스페이스

사용자 선택은 **MTS의 명료함 + 터미널의 정보 밀도**입니다. 게임 그래픽 개선은 여기서 멈추고 시장·포트폴리오·리서치를 연결한 투자 화면 개발에 집중합니다. 기존 야영지/고정 사령부 흐름과 가상 계좌 계산을 보존합니다.

- **시장:** 관심종목 검색(Ctrl+K), 캔들/라인 차트, 기간·20일 평균, 비중 계획.
- **포트폴리오:** 보유액·손익·현재/목표 비중을 표로 검토하고 공통 계획을 편집.
- **리서치:** 5개 종목의 KIS 일봉, 삼성전자 2023–2025년 연결 재무, 출처·기준일·갱신 상태, 종목별 자동 저장 노트. 다른 기업의 재무는 자료 없음으로 표시합니다.

차트와 주요 조작은 1280×720에서 한 화면에 표시하며, 긴 계좌 정보·포트폴리오·리서치는 해당 영역을 세로 스크롤합니다. 더 좁은 창의 비중 계획은 포트폴리오에 표시합니다. 모바일 MTS 앱이나 실시간 Bloomberg 서비스 연동을 구현한 것은 아닙니다.

이번 변경과 자동/실제 창 검증은 [투자 UI 검증 기록](docs/TERMINAL_UI_VALIDATION.md), 실행 화면은 [화면 갤러리](docs/review/terminal_pass_20260928/review.html)를 보세요.

## 실제 종목 분석 · 2026-09-29

리서치 탭에서 종목을 고르면 **한국투자증권 KRX 수정주가 일봉**을 조회합니다. 전일까지의 최근 1년이며 당일 현재가가 아닙니다. 1개월/3개월/1년은 22/66/252거래일 근사이고 캔들·라인·20거래일 평균·거래량을 확인할 수 있습니다. 새로고침과 출처·수신 시각을 함께 제공합니다. 실패하면 이전 자료임을 표시하고, 저장된 자료가 없으면 빈 상태를 유지합니다.

삼성전자 매출·영업이익·영업현금흐름은 공식 IR 2023–2025년 연결 연간 **확인본**이며 자동 갱신 자료가 아닙니다. 타 기업 재무, 분기/반기, PER/PBR/컨센서스는 아직 연결하지 않았습니다. OpenDART 키는 없으며 실제 공시 API 호출은 검증하지 않았습니다.

기존 WSL Ubuntu-24.04의 Phalanx 백엔드를 재사용합니다. 인증 파일은 `/home/hansol/.config/phalanx/credentials.env`, 실행기는 `/home/hansol/projects/phalanx/.venv/bin/python`입니다. 키를 Godot에 입력하거나 복사하지 않습니다. 기존 환경이 실행 가능하면 F5 후 리서치에서 바로 조회합니다. WSL 실행/인증이 실패해도 저장된 일봉과 노트는 유지됩니다.

환경이 다른 PC는 `PHALANX_KIS_WSL_DISTRO`와 `PHALANX_KIS_WSL_PYTHON`을 지정해야 합니다. 현재 연결은 이 PC의 개발 환경용입니다. 일봉 캐시는 `user://research_cache`, 관심/노트 저장은 기존 경로를 사용합니다.

[실데이터 검증·출처·한계](docs/RESEARCH_DATA_VALIDATION.md) · [최종 화면](docs/review/research_data_20260929/review.html)

## 관심종목과 노트 자동 저장

시장 화면의 **★ 관심 / ☆ 추가**로 관심종목을 편집합니다. 해제한 종목은 **전체 보기** 또는 이름/코드 검색으로 다시 찾습니다. 관심 해제는 해당 종목의 노트를 지우지 않습니다.

리서치 노트는 입력 후 약 0.5초에 자동 저장하며, 화면 이동·대시보드 닫기·정상 종료 전에 대기 입력을 반영합니다. 하단 저장 상태와 실패 시 **저장 재시도**를 확인하세요. 빈 관심목록과 지운 노트도 그대로 복원됩니다.

저장 위치는 `user://investment_workspace.json`입니다. Windows 기본 경로는 `%APPDATA%\Godot\app_userdata\Phalanx Headquarters`이며 하단 저장 상태의 툴팁에서도 실제 경로를 확인할 수 있습니다. 이전 정상본은 `.bak`에 보관합니다. 이번 영구 저장 대상은 관심종목과 노트이며 목표 비중은 기존처럼 실행 중에 유지됩니다.

[저장 기능 검증](docs/WORKSPACE_PERSISTENCE_VALIDATION.md) · [재실행 후 화면](docs/review/workspace_persistence_20260928/review.html)

## 실행

프로젝트 폴더에서 `project.godot`를 Godot으로 열고 **F5**로 실행합니다. 새 시작 씬은 `scenes/phalanx.tscn`입니다. 기존 대시보드만 확인하려면 `scenes/headquarters.tscn`을 열고 **F6**으로 실행합니다.

```powershell
$godot = 'C:\Users\hanso\Tools\Godot\Godot_v4.7.2-stable_win64.exe'
& $godot --path .
```

## 조작과 화면 흐름

1. **야영지:** 이동 가능한 지면을 왼쪽 클릭해 목적지를 지정합니다. 사령부 입구에 접근한 뒤 표시되는 상호작용으로 입장합니다. 카메라는 정해진 쿼터뷰이며 자유 회전하지 않습니다.
2. **사령부:** 고정 구도에서 지도/작전 테이블에 마우스를 올려 선택 영역을 확인하고 클릭해 대시보드를 엽니다. WASD 보행·마우스 시선 회전·마우스 캡처·중앙 조준점·조준 후 E 입력을 사용하지 않습니다.
3. **대시보드:** 종목 검색, 기간 선택, 차트, 목표 비중과 모의 매매계획을 조작합니다. 대시보드를 닫으면 동일한 사령부 구도로 돌아옵니다.
4. **복귀:** 사령부의 **야영지로** 조작으로 나갑니다. 야영지 캐릭터는 입구 부근의 안전한 위치로 복원됩니다.

Esc는 열린 모의 계획 팝업을 먼저 닫고, 다음 입력으로 대시보드를 닫습니다. 팝업과 대시보드가 없는 사령부에서는 Esc 또는 **야영지로** 버튼으로 나갑니다. 야영지의 Esc는 화면을 바꾸지 않습니다. 상·하단 UI 클릭은 뒤쪽 지도나 야영지 이동에 전달되지 않습니다.

대시보드는 실행 중 재사용하므로 종목 선택과 목표 비중을 유지합니다. 목표 비중 합계가 100%를 넘으면 모의 계획 버튼이 비활성화됩니다. 화면보다 긴 내용은 세로로 스크롤하며, 닫기 조작은 위에 유지합니다.

## 구성과 제작 기준

| 책임 | 파일 |
| --- | --- |
| 시작 씬·화면 전환 | `scenes/phalanx.tscn`, `scripts/phalanx_app.gd` |
| 야영지 표시·입구 상호작용 | `scripts/quarter_camp.gd` |
| 이동 가능 영역·경로 | `scripts/camp_navigation.gd` |
| 캐릭터 경로 추종·이동 속도 | `scripts/camp_avatar.gd` |
| 캐릭터 방향·보행·발 접지 | `scripts/commander_gait.gd` |
| 캐릭터 모델·관절 포즈 | `scripts/commander_model.gd` |
| 캐릭터 3D 렌더·2D 합성·그림자 | `scripts/commander_visual.gd` |
| 배경의 그늘·캐릭터 조명 연결 | `scripts/camp_light_field.gd` |
| 대표 전경 가림 | `scripts/camp_foreground.gd`, `shaders/camp_foliage.gdshader` |
| 고정 사령부·테이블 호버/클릭 | `scripts/fixed_headquarters.gd` |
| 투자 워크스페이스·차트·가상 데이터 | `scenes/headquarters.tscn`, `scripts/headquarters.gd`, `scripts/price_chart.gd`, `scripts/demo_data.gd` |

화면에 보이는 사령부 주변의 작은 구역을 우선합니다. 붉은 군막, 따뜻한 역광, 깊은 내부 그림자, 지도 중심 구도, 낡은 목재와 부분적인 금속 반사, 비대칭 소품 배치가 미술 기준입니다. 고정시점 배경·2.5D 요소를 사용할 수 있으며 배경의 종횡비, 이동 캐릭터의 접지/가림, 클릭 영역 정렬을 함께 관리합니다.

야영지·사령부는 이전 작업의 `image_gen` 배경을 그대로 사용하며, 가림 마스크·불꽃·먼지를 결합한 2.5D 구성입니다. **플레이어 한 명만 코드로 제작한 관절형 3D 모델**을 별도 투명 뷰포트에서 38도 사선으로 렌더해 배경에 합성합니다. 야영지 전체를 3D로 재구축한 것이 아닙니다. 파일별 제작 경위는 [시각 에셋 기록](assets/art/PROVENANCE.md)에 있습니다.

캐릭터는 네 방향을 포함한 연속 방향의 대기·보행 포즈를 사용합니다. 실제 이동 거리에 보행 위상을 맞추고, 지지 중인 발의 지면 기준점과 다리 IK, 팔·망토의 움직임을 함께 계산합니다. 정지하면 마지막 방향으로 대기하며 방향 전환과 출발·도착을 완화합니다. 깊이 정렬·원근 크기·접촉 그림자는 발 위치를 기준으로 관리합니다. 기존 단일 포즈 `commander.png`는 이전 작업 보존용이며 현재 런타임 캐릭터로 사용하지 않습니다.

나무와 상자 일부의 가림 윤곽을 별도 모듈로 관리합니다. 나뭇잎 사이 흙색 부분은 원본 색을 이용한 알파 처리로 열어 두며, 원본 배경과 UV 좌표를 공유합니다. 전체 식생을 다시 분리한 것은 아니며 색 분리 마스크와 캐릭터 합성의 미술적 한계는 실제 실행 기록에서 평가합니다.

기존 `scenes/command_camp.tscn`과 1인칭 관련 `camp_player.gd`, `table_interaction.gd`, 절차적 3D 미술 파일은 이전 구현 자료입니다. 현재 시작 흐름이 그 입력 방식에 의존하도록 되돌리지 않습니다. 전투·훈련·복잡한 NPC 대화는 현재 범위가 아닙니다. 투자 기능은 위의 최신 개발 초점을 따릅니다.

## 검증

최신 실제 종목 분석 검증은 [RESEARCH_DATA_VALIDATION.md](docs/RESEARCH_DATA_VALIDATION.md)를 기준으로 합니다. [TERMINAL_UI_VALIDATION.md](docs/TERMINAL_UI_VALIDATION.md)는 앞선 가상 데이터 UI 단계의 기록입니다. 캐릭터 보행·합성의 실행 증거와 미술 평가는 [캐릭터 움직임 검증 기록](docs/AVATAR_MOTION_VALIDATION.md)을 기준으로 확인합니다. [쿼터뷰 전환 검증 기록](docs/QUARTER_VIEW_VALIDATION.md)은 단일 포즈 캐릭터를 사용했던 이전 단계의 기록입니다. 자동/합성 입력, 운영체제 창 조작, 사람이 직접 수행한 검증을 구분하며, 이전 테스트 PASS를 새 캐릭터의 검증으로 대신하지 않습니다.

기존 데이터·대시보드 회귀, 새 화면 흐름과 기본 실행 확인 명령은 다음과 같습니다.

```powershell
$godot = 'C:\Users\hanso\Tools\Godot\Godot_v4.7.2-stable_win64_console.exe'
& $godot --headless --path . --script res://tests/smoke_test.gd
& $godot --headless --path . --script res://tests/terminal_workspace_test.gd
& $godot --headless --path . --script res://tests/workspace_persistence_test.gd
& $godot --headless --path . --script res://tests/quarter_flow_test.gd
& $godot --headless --path . --quit-after 60
```

실제 GPU 렌더와 두 해상도 스크린샷을 남기는 검증에는 `--headless`를 붙이지 않습니다. 아래는 Godot 안에 합성 입력을 주입하는 테스트이며 운영체제 창 조작이나 사람의 직접 조작을 뜻하지 않습니다.

```powershell
$review = Join-Path $env:TEMP 'phalanx-quarter-review'
& $godot --path . --script res://tests/quarter_flow_test.gd -- $review
```

1280×720과 1440×960에서 야영지 이동 → 사령부 입장 → 테이블 클릭 → 대시보드 → 사령부 복귀 → 야영지 복귀를 확인합니다. 배경 비율, 클릭 위치, 장애물 회피/가림, 팝업 우선 Esc, UI 가독성, 차트와 가상 데이터 표시도 검사합니다. 기능 통과와 시안 대비 미술 품질은 별도로 평가합니다.

## 문서와 이전 기록

- [현재 제작 지침](Phalanx_Command_Camp_Art_Brief_20260928.md)
- [현재 세션 인수인계](docs/SESSION_HANDOFF.md)
- [이전 1인칭 문서 원본 보관](docs/archive/README.md)
- [아트 패스 A 당시 검증](docs/PASS_A_VALIDATION.md), [아트 패스 B 당시 검증](docs/PASS_B_VALIDATION.md)

이전 기록의 조작·시점·검증 결과는 당시 버전의 이력입니다. 현재 요구사항과 충돌할 때는 쿼터뷰 야영지와 고정시점 사령부 설계를 따릅니다.

## 그늘 반응과 후속 검수 · 2026-09-28

배경의 주요 그늘 위치에 따라 캐릭터의 직사광·주변광·드리운 그림자가 변한다. 밝은 지면으로 나오면 원래 조명으로 돌아오고 발밑 접촉 그림자는 유지한다. 원본 배경을 바꾸면 `camp_light_field.gd`의 구역도 다시 맞춰야 한다. 작은 잎 그림자를 몸에 따로 투영하는 방식은 아니다.

두 해상도의 실제 창 왕복과 이번 조명/보행/흐름 검증 결과는 [그늘 반응 검증](docs/CAMP_LIGHTING_VALIDATION.md), 동일 위치 화면은 [전후 비교](docs/review/shade_pass_20260928/review.html)에 있다. 망토의 색·문양·옷단도 함께 정리했다. 캐릭터의 형상/재질은 배경보다 단순한 한계가 남는다.