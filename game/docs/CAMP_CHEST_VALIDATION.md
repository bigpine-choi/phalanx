# 야영지 배치 수정

2026-09-29

- Godot 편집기를 열고 F5로 실제 게임을 실행했다.
- 분석실의 상자 노드를 제거하고 야영지 오른쪽 보급품 옆으로 이동했다.
- 원본 배경 좌표 (1150, 493), 캐릭터와 같은 78 px/m 기준, 카메라 고도 38도.
- 야영지 그늘 조명과 캐릭터 가림 순서 적용.
- 모델 바닥을 투영한 충돌 영역 및 모델 외곽의 클릭 차단 영역 적용.
- 기존 화면 전환·이동 검사: `PHALANX_QUARTER_FLOW_TEST: PASS (157 checks; synthetic viewport input; renderer=headless)`.
- 이번 배치 전용 검사: `CAMP_CHEST_PLACEMENT: PASS; route_points=4; analysis_room_empty=true`.
- 상자 중심은 이동 불가이며 상자 앞에서 뒤로 이동하는 경로가 네 점으로 우회하고 각 구간의 충돌 검사가 통과했다.
- Godot 실행 창에서 상자를 클릭해 이동 명령이 생기지 않는 것을 확인하고, 상자 앞 바닥으로 캐릭터를 직접 이동했다.
- 캡처는 실제 실행 중인 Godot 창에서 저장했다. 이전 `game-captures` 폴더는 수정 전 기록이다.

배치 전용 검사는 `tests/camp_chest_placement_test.gd`에 보관한다. 캡처는 로컬 Codex 결과 폴더에 보존한다.
