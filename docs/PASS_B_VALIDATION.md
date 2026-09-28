# 사령부 아트 패스 B · 2026-09-28

> 과거 1인칭 구현의 검증 기록입니다. 2026-09-28 설계 정정 이후의 쿼터뷰 야영지·고정시점 사령부 흐름을 검증한 결과가 아닙니다. 현재 기준은 [README](../README.md)를 따릅니다.

## 시작 상태와 범위

- 프로젝트·상위 경로·하위 검색에서 적용할 `AGENTS.md`를 찾지 못했다.
- 시작 브랜치 `feature/camp-first-person`, HEAD `344b8aa`, 작업 트리 깨끗함을 확인했다.
- 같은 HEAD에서 `feature/camp-art-pass-b`를 생성했다. commit / merge / push는 하지 않았다.
- 이번 패스 B는 사령부 한 장면의 구도·미술·안내 개선이다. 과거 문서의 참모 제작 계획은 이번 범위에 포함하지 않는다.
- 저장소의 절차적 재질·SurfaceTool 메시와 설치된 Godot 4.7.2를 사용했다. 별도 이미지·모델·패키지·외부 에셋은 추가하지 않았으며 외부 에셋 라이선스 취득을 주장하지 않는다.

## 실제 변경 파일

| 파일 | 변경 |
| --- | --- |
| `scenes/command_camp.tscn` | 시작 위치 z -2.65 → -2.40, 낮아진 테이블에 맞춘 상호작용 영역, 비활성 `ReviewCamera` 설정 |
| `scripts/camp_player.gd` | 눈높이 1.65 → 1.76m, 초기 하향각 15 → 12도, FOV 70 → 64도. 피치/FOV는 export 설정. 이동·포커스·캡처 로직 유지 |
| `scripts/camp_table.gd` | 상판 높이 1.02 → 0.94m, 코어 두께 23 → 13cm, 앞판·다리 비례와 모서리 조정, 지도 가장자리 들림과 지형 법선 개선, 양피지·해수·잉크 색 조정 |
| `scripts/camp_scroll.gd` + `.uid` | 두 면과 절단면을 가진 2.75회 감긴 종이 메시. 속 빈 중심·층별 단면·바깥 입술·불규칙한 끝단. 두 두루마리가 메시 공유 |
| `scripts/camp_architecture.gd` | 붉은 안팎 천막 색, 지붕 두께 18 → 24mm, 봉제선 위치, 커튼·벽·차양의 덜 규칙적인 주름 |
| `scripts/camp_lighting.gd` | 중립적인 지도 채움광, 완화한 태양/AO, 24~175m 거리 안개. 블룸 비활성 유지 |
| `scripts/camp_backdrop.gd` | 고정 시드 노이즈와 완만한 비대칭 단면의 3단 산맥, 거리별 차가운 색. 앞뒤 경사가 있는 3D 지형 유지 |
| `scripts/camp_collision.gd` | 테이블 충돌 높이를 가구 상수와 동기화. 바닥·통로·탐색 경계 유지 |
| `shaders/camp_bronze.gdshader` | 황동의 거칠기 증가, 금속성·반사 강도 감소 |
| `scripts/command_camp.gd` | 탐색 대기 안내를 하단 한 곳으로 통합. 탐색 중 테이블 조준 시에만 E 안내. 중앙 지도 가림 제거, 가상 데이터 문구 유지 |
| `tests/camp_smoke_test.gd` | 대기/조준/시선 이탈/일시정지 시 안내의 상호 배타적 표시 검증 |
| `tests/camp_visual_test.gd` | 변경된 상판과 충돌 일치, 시작 구도의 지도 노출 및 하단 안내 배치 검증 |
| `tests/first_person_test.gd` | 첫 캡처 이벤트 검사를 새 캡처 직후 동기적으로 주입하도록 조정. 실제 창의 자동 재중앙정렬 이벤트와 합성 검사의 순서 경합 제거 |
| `tests/camp_pass_b_review.gd` + `.uid` | 고정 구도·실제 시작 화면 분리 캡처, 합성 클릭·E·Esc GPU 검수 |
| `README.md`, 이 문서 | 현재 설정·재현 명령·검증과 한계 기록 |

기존 `table_interaction.gd`, `dashboard_overlay.gd`, `headquarters.gd`, `demo_data.gd`, 차트 및 대시보드 씬은 수정하지 않았다. 씬 연결/HUD·입력·상호작용·충돌·가구·건축·원경·조명의 책임 분리를 유지한다.

## 검증

Windows Godot `4.7.2.stable.official.ed1daf0bf` 사용.

- `smoke_test.gd`: PASS, exit 0 — 기존 데이터·계산·대시보드.
- `camp_smoke_test.gd`: PASS, exit 0 — 클릭 진입·E·Esc·팝업 계층·재사용·두 해상도 대시보드·새 안내 표시 조건.
- `camp_visual_test.gd`: PASS, exit 0 — 천막 법선·지도 앞뒤·상판/충돌·시점·HUD·지도 노출.
- `first_person_test.gd`: PASS, exit 0 — 합성 WASD/마우스 입력, 대각 속도·시점 제한·테이블/벽/소품/경계 충돌·통로/경사로 왕복·거리/가림·대시보드 입력 차단·Esc 복귀·합성 포커스 회복.
- 위 1인칭 테스트를 실제 GPU 창에서도 실행: PASS, exit 0 (`first-person-gpu-final.log`). 물리 프레임을 진행하며 이동·충돌·시선·E·Esc를 합성 입력으로 확인했다.
- 실제 D3D12 Forward+ / RTX 5070 Ti Laptop GPU 실행에서 1280×720, 1440×960 렌더와 합성 클릭 → E → Esc 왕복 검수: `PASS_B_CAPTURE_DONE ... failures=0`, exit 0. 닫기 후 위치·시점 유지도 검사.
- 스크립트/셰이더 파싱 오류 없음. `git diff --check` 통과.

샌드박스 headless 로그에는 기존 OS 인증서 저장소 읽기 오류가 있으며, 최초 editor import에는 사용자 영역의 에디터 설정 저장 권한 오류도 있었다. 실제 GPU 검수는 승인된 별도 프로세스로 실행했고 해당 환경 오류 없이 완료했다. 이를 소스 파싱 오류와 구분한다. 기존 사용자 에디터를 종료하지 않았다.

GPU 전체 입력 검사의 첫 실행에서는 캡처 직후 첫 마우스 이벤트에 관한 두 검사가 실패했다. 이전 테스트가 여러 프레임을 기다린 뒤 주입한 이벤트를 '첫 이벤트'로 가정했기 때문이다. 진단 로그에서 그 사이 Windows는 이미 첫 이벤트를 받았고(`value=true`), headless는 받지 않았음(`value=false`)을 확인했다. 입력 코드를 바꾸지 않고, 테스트가 새 캡처 직후 첫 이벤트를 주입·flush한 다음 다음 프레임을 기다리도록 수정했다. 두 실행 환경 모두 다시 PASS했다. 실제 Alt+Tab 수동 검증을 대체하는 결과는 아니다.

## 화면 비교와 재현

출력 폴더: `%TEMP%\phalanx-pass-b-review` (프로젝트 밖).

- `before-b-fixed-*` / `after-final-fixed-*`: **위치·회전·FOV·해상도가 같은** 미술 비교. HUD 숨김.
- `before-b-startup-*` / `after-final-startup-*`: 각각의 실제 시작 카메라와 HUD 비교. 카메라 변경 효과를 보여주므로 같은 구도 비교가 아니다.
- `before-b-detail-left-*` / `after-final-detail-left-*`: 동일한 좌측 소품 검수 시점.
- `after-final-interaction-*`, `after-final-dashboard-*`, `after-final-returned-*`: 안내·대시보드·복귀 실제 GPU 렌더.
- `comparison.html`: 원본 PNG를 나란히 여는 로컬 비교 페이지.
- `*.log`: 파싱·각 자동 테스트·GPU 검수 로그.

고정 카메라는 `(0, 1.80, -2.40)`, 회전 `(-12, 180, 0)`, 수직 FOV `64`, near `0.05`, far `210`이다. 씬 `ReviewCamera`는 평상시 비활성이며 자유 이동을 대체하지 않는다. 검수 스크립트는 구도를 독립 상수로 고정해 이전 버전에서도 같은 카메라를 재현한다. 화로 광량 변화는 중지하지만 불꽃·군기 셰이더의 시간 위상은 캡처마다 약간 다를 수 있다.

```powershell
$godot = 'C:\Users\hanso\Tools\Godot\Godot_v4.7.2-stable_win64_console.exe'
$review = Join-Path $env:TEMP 'phalanx-pass-b-review'
& $godot --path . --script res://tests/camp_pass_b_review.gd --log-file (Join-Path $review 'review.log') -- $review review
```

안개의 거리 모드는 [Godot Environment API](https://docs.godotengine.org/en/4.6/classes/class_environment.html#class-environment-property-fog-depth-begin)를 확인하고 설치된 엔진의 실제 렌더에서 검증했다.

## 남은 한계

- 이번 실행의 입력 검증은 합성 이벤트다. 물리 키보드의 지속 입력·실제 상대 마우스 캡처·이동키를 누른 채 Alt+Tab 후 복귀는 직접 미검증이다. 이전 버전의 사용자 수동 확인을 이번 수정의 수동 검증으로 간주하지 않는다.
- 천·지형·수목·불꽃은 양식화한 절차적 모델이다. 사실적인 직물 시뮬레이션·조각 가구·고밀도 식생·연기는 추가하지 않았다.
- 두루마리와 산맥 메시 정밀도가 증가했다. 이번에는 지속 FPS나 순수 GPU 시간의 성능 비교를 수행하지 않았으며 성능 향상을 주장하지 않는다.
- 스크린샷은 로컬 임시 산출물이므로 임시 폴더 정리 시 사라질 수 있다. 검수 스크립트와 재현 명령은 저장소에 남긴다.
