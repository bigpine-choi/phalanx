# 캐릭터 보행·배경 합성 검증 — 2026-09-28

이번 기록은 쿼터뷰 전환 이후의 **플레이어 캐릭터 한 명** 개선에 관한 것이다. 기존 [쿼터뷰 검증](QUARTER_VIEW_VALIDATION.md)은 당시 정지 이미지 캐릭터를 사용한 이력으로 보존한다.

## 작업 전 상태와 범위

브랜치 `feature/camp-art-pass-b`, HEAD `344b8aa`. 기존 미커밋 아트 패스 B와 쿼터뷰 전환 변경을 확인했다. 적용 경로에서 `AGENTS.md`는 발견되지 않았다. 소스와 변경 패치는 `C:\Users\hanso\AppData\Local\Temp\phalanx-before-avatar-20260928-221541`에 복사 보존했다. commit·merge·push·stage·강제 초기화를 하지 않았다.

배경 2종과 기존 `commander.png`, `camp_navigation.gd`, `phalanx_app.gd`, `fixed_headquarters.gd`, `dashboard_overlay.gd`, `headquarters.gd`, `demo_data.gd`, `price_chart.gd`, `project.godot`는 작업 전 사본과 SHA-256이 같다. 배경 재제작·맵 확장·NPC·대화·전투·훈련·투자 기능 변경은 없다.

사용자 참조 `KakaoTalk_20260928_042401446.png`를 직접 열어 시선 각도·인물 크기·접지·붉은 망토를 확인했다. 이미지 안 문구는 작업 지시로 취급하지 않았다.

## 제작 방식

기존 Godot 4.7.2를 사용했다. 확인한 로컬 도구/에셋 경로에는 Blender와 재사용할 리깅 모델이 없었다. 외부 에셋 다운로드·유료 구매·계정 생성·새 프로그램 설치·새 이미지 생성은 하지 않았다.

방향별로 서로 다른 이미지를 생성하는 대신 **캐릭터 한 명만 3D로 만들고, 38도 고정 직교 카메라의 투명 SubViewport 렌더를 2D 야영지에 합성**한다. 얼굴·갑옷·체형·검집·망토는 모든 방향/프레임에서 같은 지오메트리를 사용한다. 배경과 이동 공간을 3D로 재구축하지 않았다.

- 1.78m 기준 지휘관: 갈색 곱슬머리, 아이보리 리넨 갑주와 치마 장식, 작은 청동 견갑/장식, 가죽 띠·샌들·검집, 비대칭 진홍 망토.
- 앞·뒤·좌·우와 중간 방향을 연속 회전으로 표현한다. 대기 시 마지막 방향을 유지한다. 이름으로 구분하는 네 방향 상태에는 경계 여유를 두고, 실제 모델 회전에는 각속도 제한을 둔다. 좌우 반전은 사용하지 않는다.
- 양발의 지면 좌표와 이동 거리에 따라 보행 주기를 진행하고 두 관절 IK로 다리를 배치한다. 팔은 같은 쪽 발과 반대로 움직이고 망토·옷자락은 보행 주기를 따라 변형한다.
- 이동은 가속/감속하며, 화면의 세로 이동은 카메라의 지면 압축에 맞춰 속도를 줄인다. 가까움/멀어짐에 따른 크기 변화는 0.94~1.02로 제한한다.
- 발 원점을 위치·그림자·렌더 등록·깊이 정렬에 공통 사용한다. 발밑 접촉 그림자와 부드러운 드리운 그림자를 따로 합성한다. 후속 그늘 작업에서 드리운 방향을 배경에 맞춰 왼쪽 아래로 정정했고 그늘 안에서는 약하게 만든다.
- 384×448 투명 렌더, 4×MSAA와 선형 필터를 사용한다. 이 동적 텍스처에는 기존 PNG 가져오기 옵션/밉맵 설정을 적용하지 않는다. 기존 PNG는 보존용으로만 남겼다. 미세 직물 셰이더는 화면 미분으로 고주파 무늬를 줄인다.

사용 API의 원리는 Godot 공식 [SubViewport](https://docs.godotengine.org/en/stable/classes/class_subviewport.html), [Camera3D](https://docs.godotengine.org/en/stable/classes/class_camera3d.html) 문서를 참고했다. 현재 에셋 구분과 출처는 [PROVENANCE](../assets/art/PROVENANCE.md)에 기록했다.

## 수정 파일과 책임

| 파일 | 책임 |
| --- | --- |
| `scripts/camp_avatar.gd` | 기존 경로 추종, 가속/감속, 포커스/정지, 시각 컴포넌트 연결 |
| `scripts/commander_gait.gd` | 방향 안정화, 거리 기반 주기, 발 디딤 좌표와 정지 전환 |
| `scripts/commander_model.gd` | 인체/의복/장비 지오메트리, 다리 IK, 팔·망토·옷자락 포즈 |
| `scripts/commander_visual.gd` | 고정 각도 투명 렌더, 조명·필터·합성·그림자 |
| `scripts/camp_foreground.gd`, `shaders/camp_foliage.gdshader` | 대표 나무/상자 윤곽, 나뭇잎 사이 흙 영역의 가림 완화 |
| `scripts/quarter_camp.gd` | 전경 생성만 별도 모듈로 위임. 이동/입출입 API 유지 |
| `tests/avatar_animation_test.gd` | 방향·발 디딤·정지·재지정·작은 굴곡·포커스·복귀 회귀 |
| `tests/quarter_flow_test.gd` | 캐릭터 텍스처 검사를 새 렌더 방식에 맞춤, 기존 전체 흐름 검사 유지 |
| `tests/avatar_replay.gd`, `tests/Make-AvatarMoviePreview.ps1` | 동일 경로의 실제 렌더 영상과 샘플 프레임 미리보기 제작 |
| README·인수인계·에셋 출처·검증 문서 | 현재 방식과 과거 기록 구분 |

## 실행 검증

자동 검사, 컴퓨터 사용 도구의 OS 입력, 사람이 직접 조작한 검증을 구분한다. 테스트 PASS는 미술 평가를 대신하지 않는다.

이전 보행 작업은 물리 Esc로 컴퓨터 사용이 중단되어 OS 검수와 이 문서가 미완료였다. 2026-09-28 후속 그늘 작업에서 보행 검사 50, 흐름 157(headless)/162(GPU), 대시보드 검사를 다시 실행해 통과했다. GPU 162는 캡처 저장 검사 없이 실행한 수다. 이전 보고의 174와 혼용하지 않는다.

두 해상도(1440×960, 1280×720)의 OS 창에서 정상 속도 전체 왕복, 팝업 우선 Esc와 위치/방향 복원을 확인했다. 대표 나무 뒤 경로도 확인했다. 이동 중 목적지 변경·Alt+Tab 정지와 복귀는 검수 실행의 0.25배 시간 배율에서 확인했다. 제품 속도는 그대로이며 검수 후 1배로 복구했다. 정상 속도 이동 중 Alt+Tab과 사람의 직접 조작은 미검증이다. 자세한 증거와 조건은 [그늘 반응 후속 검증](CAMP_LIGHTING_VALIDATION.md)을 따른다.

## 비교 영상과 연속 프레임

Godot의 [Movie Maker](https://docs.godotengine.org/en/stable/tutorials/animation/creating_movies.html)로 실제 렌더를 AVI에 기록한다. 경로는 Godot 합성 마우스 입력으로 재생하며 영상 안에도 `SYNTHETIC REPLAY`라고 표시한다. OS 수동 검수나 사람 플레이 녹화로 표기하지 않는다.

첫 9초는 동일한 마당 시작 위치 → 사령부 입구 → 정지 구간이다. 이전 캐릭터는 빠르게 도착해 기다리고 새 캐릭터는 보행 속도로 걷는다. 이후 네 방향과 정지, 이동 중 목적지 변경, 나무 옆 긴 이동을 기록한다. 미리보기는 원본 실제 프레임을 샘플링하며 보간·새 포즈 생성은 하지 않는다.

## 미술 평가와 한계

**개선 전:** 하나의 사진풍 포즈가 좌우로 반전되고 몸 전체가 조금 흔들렸다. 이동 거리와 발 동작이 무관했고 앞/뒤 이동도 같은 촬영 각도를 사용했다.

**개선 후:** 동일 모델이 방향에 맞춰 회전하고 양발·무릎·팔·망토가 움직인다. 멈추면 그 방향의 대기로 돌아오고, 실제 발 디딤 좌표가 지면에 고정된다. 고정 배경의 높은 시선과 카메라 각도를 맞추고 장비/체형/조명은 연속 프레임에서 유지된다. 대표 나무의 흙 틈과 상자 윤곽도 보완했다.

실제 창에서 방향 회전·발걸음·가림·정지 포즈를 확인했다. 후속 작업에서 배경 그늘에 따른 밝기와 색감, 그림자 방향 및 망토의 문양/옷단을 추가했다. 다만 얼굴·몸·장비는 여전히 사실적인 배경보다 단순한 게임 모델 느낌이다. 배경의 모든 잎 그림자가 몸에 투영되는 것은 아니고, 대표 그늘 구역에 맞춰 캐릭터 전체 조명을 바꾼다. 테스트 통과를 시안 수준의 미술 완성으로 해석하지 않는다.

## 실행과 재현

`project.godot`를 Godot에서 열고 F5. 조작은 기존과 같다: 목적지 클릭 → 입구 접근/재클릭 → 지도 클릭 → 대시보드. Esc와 야영지로 버튼의 단계별 복귀를 유지한다.

```powershell
$godot = 'C:\Users\hanso\Tools\Godot\Godot_v4.7.2-stable_win64_console.exe'
& $godot --headless --path . --script res://tests/avatar_animation_test.gd
& $godot --headless --path . --script res://tests/quarter_flow_test.gd
& $godot --headless --path . --script res://tests/smoke_test.gd
```

Movie Maker 재현에는 `--headless`를 붙이지 않는다. 결과 AVI는 용량이 크므로 절대 출력 경로를 지정한다. 검수 스크립트는 녹화 뷰포트와 출력 크기를 1440×960으로 맞춘다.

```powershell
$movie = Join-Path $env:TEMP 'phalanx-avatar-review\after-1440x960.avi'
& $godot --path . --resolution 1440x960 --fixed-fps 30 --write-movie $movie --script res://tests/avatar_replay.gd -- after
```
