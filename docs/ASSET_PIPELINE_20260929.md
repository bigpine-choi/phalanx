# Phalanx 첫 3D 에셋 제작 완료

2026-09-29 · 첫 대상: 청동 장식이 달린 나무 보급상자

## 완료 상태

- Blender 5.2.2 LTS 공식 Windows x64 ZIP 배포판을 설치하고 공식 SHA-256과 일치함을 확인했다.
- 설치 위치: `C:\Users\hanso\Tools\blender-5.2.2-windows-x64\blender.exe`
- 바탕화면·시작 메뉴: **Blender 5.2 LTS**, **Tripo Studio** 바로가기.
- Blender 실제 창 실행 확인. 기본 큐브의 GLB 내보내기와 별도 Godot 4.7.2 검수 프로젝트의 메시 불러오기 성공.
- 사용자가 로그인한 Chrome에서 Tripo H2.5로 보급상자 한 개를 생성하고 GLB를 내려받았다.
- 무료 크레딧 40 사용, 생성 후 잔여 160 확인. 유료 구독이나 결제 없이 진행했다.
- Blender에서 크기·면 수·텍스처를 정리했고, 편집 원본과 게임용 GLB를 저장했다.
- 실제 Godot 프로젝트의 **야영지 오른쪽 보급품 더미 옆**으로 배치를 수정했다. 분석실 내부에서 상자를 제거했다.
- 게임은 원래의 2D 야영지 배경에 실제 3D 모델의 투명 렌더를 합성한다. 정적 소품이므로 야영지 진입 때 한 번 렌더하고 결과를 유지한다.
- 야영지 캐릭터와 같은 크기 기준·카메라 높이·그늘 조명을 사용한다. 바닥 충돌 영역과 클릭 차단 영역을 모델의 투영에 맞췄으며 캐릭터와 앞뒤 가림 순서를 공유한다.

## 로컬 제작 원본과 결과 파일

아래 원본·미리보기 경로는 Codex 작업의 `outputs/` 기준이다. Git에는 게임이 사용하는 최적화 GLB·텍스처와 출처 문서를 포함한다.

- `hq-chest/supply_chest.blend`: 재질이 포함된 Blender 편집 파일. 미리보기 조명과 카메라는 별도 컬렉션이다.
- `hq-chest/supply_chest.glb`: 게임용 모델. 조명·카메라는 포함하지 않는다.
- `hq-chest/supply_chest_tripo_original.glb`: Tripo에서 받은 원본.
- `hq-chest/supply_chest_preview.png`: Blender 모델 미리보기.
- `hq-chest/asset_stats.json`: 면 수·크기·텍스처 통계.
- `hq-chest/camp-captures/`: 배치를 수정한 뒤 Godot에서 직접 확인한 야영지 화면.
- `hq-chest/game-captures/`: 최초 배치 검수 기록. 이 폴더의 분석실 상자 배치는 현재 게임에서 제거되었다.

| 항목 | Tripo 원본 | 게임용 |
|---|---:|---:|
| 삼각형 | 501,110 | 12,000 |
| 텍스처 | 4096×4096 | 1024×1024 |
| GLB 용량 | 20.08MB | 3.20MB |

크기는 약 너비 0.90m × 깊이 0.50m × 높이 0.55m이며 기준점은 바닥 중심이다. 편집 과정은 크기 적용 → Decimate로 면 수 감소 → UV·재질 유지 → 텍스처 축소·내장 → 선택한 메시만 GLB 내보내기다.

## 게임 반영 및 검증

- 프로젝트: `C:\Users\hanso\dev\phalanx-godot-prototype\phalanx-headquarters`
- 기존 브랜치: `feature/camp-art-pass-b`. 2026-09-29 개발 체크포인트에 게임 코드·최적화 에셋·문서를 포함한다.
- 모델: `assets/props/supply_chest/supply_chest.glb`
- 출처·사용 조건·실제 프롬프트: `assets/props/supply_chest/README.md`
- 표시 코드: `scripts/camp_supply_chest.gd`
- 야영지 연결: `scripts/quarter_camp.gd`, 원본 배경 좌표 (1150, 493)를 기존 화면 좌표로 변환.
- `scripts/fixed_headquarters.gd`의 상자 관련 변경은 모두 제거했다.
- Godot 4.7.2 모델 가져오기 및 스크립트 검사 성공.
- 배치 수정 후 기존 `quarter_flow_test.gd`: **157개 검사 통과**, headless 실행. 1280×720 및 1440×960에서 이동, 지도 클릭, 대시보드 왕복, 야영지 복귀를 검증했다.
- 별도로 Godot 편집기를 열어 F5로 게임을 실행했고 실제 야영지 화면에서 배치와 재질을 확인했다. 자동 검사의 입력은 Godot 내 합성 입력이다.

## 사용 조건

이번 모델은 Tripo 무료 플랜에서 생성한 **공개·비상업용 프로토타입 에셋**이다. 상업 배포용으로 확정한 에셋은 아니다. [Tripo 요금제 안내](https://www.tripo3d.ai/pricing)의 조건을 기준으로 출처 기록을 남겼다.

[Tripo 생성 모델](https://studio.tripo3d.ai/ko/workspace/generate/af81f1ef-a882-498c-be67-374fa72319d7)

## 다음 소품을 만들 때

1. Tripo Studio 로그인 후 아래 프롬프트로 보급상자를 생성한다. 실행 전 화면에 표시되는 생성 비용과 사용 가능한 크레딧을 확인한다.
2. GLB로 내려받아 원본을 보관한다.
3. Blender에서 재질·불필요한 형상·면 방향을 확인하고 크기와 바닥 중심 기준점을 정리한다. 편집 원본은 `.blend`, 게임용 모델은 `.glb`로 저장한다.
4. Godot에서 야영지의 구도·캐릭터 크기·조명에 맞춘다. 현재 야영지는 2D 배경과 별도 3D 렌더를 합성하므로 이동 경로와 앞뒤 가림도 함께 맞춘다.
5. 화면 크기별 배치·기존 지도 클릭·대시보드 왕복·재실행을 확인한다.

## Tripo 생성 프롬프트

One standalone closed wooden military supply chest for a stylized ancient Macedonian headquarters. A squat rectangular chest made of thick dark walnut planks, aged bronze corner brackets, two bronze reinforcing bands, a simple central bronze latch, and recessed side handles. Restrained Hellenistic ornament, practical craftsmanship, subtle wear, rich brown wood and muted warm bronze. Strong readable silhouette with softly beveled edges. Width 0.9 m, depth 0.5 m, height 0.55 m. Flat solid underside. Lid closed. Complete geometry on all sides. PBR wood grain and metal roughness, neutral texture lighting without baked cast shadows. Single game prop only. No people, weapons, cloth, coins, terrain, pedestal, scenery, lettering, logos, or background geometry. No animation.

## 출처

- [Blender 공식 다운로드](https://www.blender.org/download/)
- [Tripo Studio](https://studio.tripo3d.ai/ko)
- [Tripo의 Blender 연동 안내](https://www.tripo3d.ai/integrations/blender): 별도 Bridge 없이도 파일을 내보내 Blender로 가져올 수 있다.
- [Godot 공식 3D 가져오기 안내](https://docs.godotengine.org/en/stable/tutorials/assets_pipeline/importing_3d_scenes/available_formats.html): glTF/GLB 권장.

## 제작 스크립트

`tools/prepare_supply_chest.py`는 Tripo 원본 GLB를 받아 Blender에서 최적화·편집 원본·미리보기를 생성한다. Blender에서 `--background --python tools/prepare_supply_chest.py -- INPUT.glb OUTPUT_DIRECTORY`로 실행한다. 새 출력 폴더를 지정한다.
