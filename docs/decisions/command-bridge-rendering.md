# ADR: 함교 렌더링 기술과 Python 연결
> **폐기된 SF 검토 이력 — 현재 구현 기준 아님 (2026-09-26).**
> SF·우주전함 방향은 폐기됐다. 현재 적용 문서는 [원정군 사령부 설계](expedition-headquarters-rendering.md)다.
> 아래 본문과 당시의 상태/권고는 기존 작업 보존을 위한 기록이다. 현재의 미술·엔진·지원 사양 지시로 사용하지 않는다.
> 재사용할 Python·작업 수명·저장 계약은 새 문서군에 통합했다.

상태: **미적 방향 확정 · 제품 엔진/지원 사양 미확정 · 구현 전**.
조사일 2026-09-26, 기준 `main@de77b6b41fde2a82753d70cf78eaef11a28449df`.
연결 문서: [제작 사양](../command-bridge/spec.md), [자산 계획](../command-bridge/assets.md).

## 결정 제안

최종 방향은 **승인했던 사실적인 함교의 미적 목표를 유지하는 고품질 3D**다. 기본·고급
그래픽 설정을 검토하며 기본에서도 캐릭터와 상호작용의 매력을 유지한다. 게임 감각과 접근성을
함께 추구하고 캐주얼 전환이나 초고사양 전용을 전제로 삼지 않는다.

**제품 엔진과 지원 사양은 대표 함교 + 실제 Python 분석의 동시 실행 검증 후 확정한다.**
이전 Unity URP 우선 제안은 후보 비교의 참고로 남기며 현재의 우선 채택 결론으로 사용하지 않는다.
Unreal·Unity·Godot·현재 WebView/Three를 제작 과정·Python 연결·기본/고급 품질·배포 비용의
동일 기준으로 검토한다. 엔진 이름만으로 사실적 품질이나 저사양 성능을 보장하지 않는다.

실행 가능한 실험을 위해서는 먼저 엔진 하나가 필요하므로, 후속 착수 때 인력/도구·자산·계약과
실물 기준 PC를 확인해 **실험용 후보 하나만 임시 선택**한다. 작은 연결 실험 → 대표 함교의
기본·고급 화면 승인 → 실제 분석 동시 부하·정확성·Windows 배포 검증 → 제품 엔진/지원 사양
확정의 순서를 따른다. 임시 선택을 최종 채택으로 표현하거나 여러 엔진을 병행 구현하지 않는다.

금융 계산·Decimal/기존 통계 경계·원본 저장은 Python에 유지한다. 앱 세션의 작업/결과 보존,
알림 복귀·놀이 중단/재개 계약도 유지한다. 이번에는 기존 문서만 갱신하며 설치·구매·제품
구현은 하지 않는다. 라이선스/배포 조건은 [기존 조사](#라이선스자산운영-비용)를 실제 채택 시 확인한다.

## 표현 방식 비교

앞선 조사 내용은 비교 근거로 보존한다. **현재 채택한 미적 방향은 사실적 고품질 3D**이며,
2.5D/스타일화는 기본 그래픽 설정의 다른 이름이나 성능 실패 시 자동 전환 방안이 아니다.

같은 고정 함교 구도·장치 하나·움직이는 인물 한 명·창밖·읽기 가능한 정보층을 비교 단위로 삼는다.
아래는 제작 위험의 비교이며 세 방식의 실제 제작 시간/성능을 측정한 표가 아니다. 정확한 비용은
담당 인력과 샘플 자산 견적 후 산정한다. 2.5D는 깊이 레이어/투영 배경과 제한된 3D 또는 sprite
인물을 섞는 방식으로 정의하며 단순히 해상도를 낮춘 3D를 뜻하지 않는다.

| 기준 | 2.5D — 비교 기록 | 스타일화 3D — 비교 기록 | 사실적 고품질 3D — 최종 방향 |
|---|---|---|---|
| 미술과 놀이 | 고정 구도에서 밀도 높은 회화적 화면 가능. 가림/클릭 영역·인물과 배경의 접지·시차를 정교하게 맞춰야 함 | 큰 형태·색면·고유 실루엣·과장된 주목 동작으로 장치와 인물의 반응을 읽히게 함. 캐주얼 톤도 가능 | 재질·빛·인물의 존재감이 강점. 부자연스러운 얼굴/접촉/조명의 작은 차이가 드러나기 쉬움 |
| 제작 비용의 중심 | 배경 paint/render, 레이어 분리, 가림 mask, 각 자세/시점/조명 변형. 방·인물 수가 늘면 그림 변형량 증가 | 모델·UV·rig·접촉 모션과 스타일 가이드에 초기 투자. 공통 rig/모듈·장면 조명으로 반복 제작 가능하지만 미술 감독은 필요 | 얼굴·피부·모발·의복·재질 정합성과 모션/조명 polish, LOD와 최적화 반복의 부담이 커질 가능성 |
| 실제 부하 요인 | 고해상도 atlas/레이어·투명 overdraw·다수 애니메이션 프레임이 RAM/VRAM/fill-rate를 소모. 항상 가장 가볍지 않음 | skinned mesh/뼈·재질 수·동적 그림자·투명 홀로그램·후처리가 비용을 결정. 스타일만으로 비용이 줄지 않음 | 동적 GI/반사·모발·고해상도 texture를 쓰면 비용 증가. baked lighting/고정 구도에서는 통제 가능하므로 무조건 가장 느리다고 하지 않음 |
| 여러 공간/다섯 참모 | 공간별 배경과 자세 변형의 재작업·메모리 관리 필요. 대사 중심 허브라면 유리할 수 있음 | 공통 skeleton/모듈/상태를 재사용하면서 공간마다 색·소품·일상을 변형하기 좋다는 판단 | 재사용 가능하나 인물·의복·조명 간 품질 차이를 맞추는 검수 부담 |
| 현재 위치 | 과거 비교 자료. 현재 개발 방향 아님 | 과거 비교 자료. 기본 설정을 캐주얼하게 바꾸는 근거로 쓰지 않음 | 승인한 미적 목표를 기본·고급에서 유지하고 실제 동시 부하로 엔진/지원 사양 판정 |

사실적 함교의 구도·인물·재질/조명 기준을 고정한 뒤 기본·고급을 비교한다. 세 표현 방식이나
네 엔진의 동시 시제품 제작으로 확대하지 않는다. 실제 runtime에서 프레임/메모리와 제작 시간을
기록하며 자산 미완성, 그래픽 설정, 엔진 제약, Python과의 자원 경쟁을 구분한다.

## 확인한 개발 환경

조회는 네이티브 Windows PowerShell/CIM, DXGI adapter 열거, DPI API, `nvidia-smi`,
PATH/레지스트리/표준 설치 경로 검사, 기존 native Python의 버전 출력으로 수행했다.
아래 값은 **이 PC의 관측값**이며 제품 최소 사양이 아니다.

| 항목 | 확인한 값과 한계 |
|---|---|
| 저장소 | 기준 `main@de77b6b…`, 현재 `design/command-bridge-spec`, HEAD 동일. tracked/staged 변경 없음; 보호 자료와 설계 문서 3개 미추적 |
| PC/OS | HP OMEN MAX Gaming Laptop 16-ak0xxx; Windows 11 Home 64-bit, 10.0.26200 |
| CPU | AMD Ryzen AI 7 350, 8 cores / 16 logical processors. 최대 부하 clock은 측정하지 않음 |
| RAM | 모듈 17,179,869,184 bytes × 2 = 32 GiB; OS 가시 약 31.29 GiB |
| 외장 GPU | NVIDIA GeForce RTX 5070 Ti Laptop GPU, driver 592.82 |
| 전용 GPU 메모리 | DXGI `DedicatedVideoMemory`: 12,524,191,744 bytes = 11,944 MiB. `nvidia-smi memory.total`: 12,227 MiB. API별 값 그대로 기록; 같다고 보정하거나 명목 사양을 추정하지 않음 |
| 내장 GPU | AMD Radeon(TM) Graphics, DXGI dedicated 512 MiB; shared system memory를 외장 VRAM으로 합산하지 않음 |
| 화면 | 활성 1개, 물리 2560×1600, 현재 WMI 60 Hz, 작업영역 2560×1528 |
| DPI | per-monitor-aware 조회의 `GetDpiForMonitor`: 144×144 = 150%. 미래 엔진 UI의 DPI 적용 성공을 뜻하지 않음 |
| 어댑터 배치 | 현재 화면 모드는 AMD에 연결되어 보고됨. 실제 Unreal/Unity/Three/Godot 렌더 어댑터는 실행하지 않아 미확인 |
| 전원 | AC 연결, 배터리 100%, 절전 flag 0, 전원 계획 균형 조정. 설정은 변경하지 않음 |
| GPU 전력 | 현재 power.limit N/A, API default 80 W / min 5 W / max 140 W, 유휴 순간 4.77 W. 지속 실효 TGP·OEM 모드·열 제한은 미확인 |
| 디스크 | C: 조회 시 여유 878,602,764,288 bytes. 설치 소요량은 선택 버전/콘텐츠에 따라 별도 산정 |
| Windows 런타임 | 기존 검토용 Python 3.12.14 64-bit 직접 실행 성공; pywebview 6.2.1, pywin32 312, pythonnet 3.1.0; WebView2 154.0.4258.37 |
| Windows 개발 도구 | Git 명령 발견, VS Code 1.139.1, PowerShell 5.1.26100.9444 |
| 설치 미발견 | Unreal/Epic, Godot, Blender, Visual Studio/MSVC, Windows SDK, Node/npm, .NET SDK, CMake: 관련 PATH·레지스트리·표준 설치 위치에서 미발견. 휴대용/사용자 지정 경로는 전수 조사하지 않음 |
| Unity 설치 상태 | 앞선 환경 조회의 확인 대상에 포함하지 않았음. Hub/Editor/모듈·버전 모두 미확인 |
| WSL 개발 환경 | Linux 6.18.33.2-microsoft-standard-WSL2, 기존 `.venv` Python 3.12.3, uv 0.12.5. Windows 환경과 공유하지 않음 |

실효 GPU budget, D3D12/SM6 기능을 쓰는 실제 엔진 실행, 노트북 열 안정화 후 frame time,
사용자의 최종 배포 대상 PC/최저 사양, 오디오 장치별 청취 결과는 **미확인**이다.
개발 노트북 관측값을 보급형 PC의 대체 기준으로 쓰지 않는다. [성능 실험 계획](../command-bridge/spec.md#b-성능안정성-합격-제안)은
확인된 개발 PC에서 시작해 추가 실물 PC로 넓히며 각 해상도·설정별 목표를 측정 전에 고정하는 절차다.
미확인 PC의 fps·해상도·메모리 합격 숫자는 아직 정하지 않았다.
이번 요구 갱신에서는 앞선 조회 결과를 재사용했고 장비를 재측정하거나 Unity를 설치하지 않았다.

조사 원본은 저장소 밖 `/tmp/phalanx-command-bridge-design/`의
`windows-hardware.json`, `windows-dxgi-dpi.json`, `windows-tools.json`,
`windows-python.json`, `windows-power.json`과 각 `*-command.ps1`에 보관했다.
`windows-evidence-SHA256.txt`의 해시는
`7985acf853bc96a63de9995e9f68f37e84dbf57afeefc89106e99021a1bf5982`다.
임시 증거는 영구 저장소 자산이나 제품 입력이 아니다.

### 재확인과 미확인 항목의 확인 방법

다음은 Windows PowerShell의 **조회 명령**이다. 이번 조사에서 실행한 전체 DXGI/DPI 호출은
위 원본 명령 파일에 있다. 단순 `Win32_VideoController.AdapterRAM`으로 큰 VRAM 용량을 판정하지 않는다.

```powershell
Get-CimInstance Win32_OperatingSystem | Select-Object Caption,Version,OSArchitecture
Get-CimInstance Win32_Processor | Select-Object Name,NumberOfCores,NumberOfLogicalProcessors
Get-CimInstance Win32_PhysicalMemory | Select-Object Capacity,Speed,ConfiguredClockSpeed
Get-CimInstance Win32_VideoController | Select-Object Name,DriverVersion,CurrentHorizontalResolution,CurrentVerticalResolution,CurrentRefreshRate
nvidia-smi --query-gpu=name,memory.total,driver_version,power.limit,power.default_limit,power.max_limit --format=csv
powercfg /GETACTIVESCHEME
Get-Command UnrealEditor.exe,Unity.exe,godot.exe,godot4.exe,blender.exe,node.exe,cl.exe,cmake.exe,dotnet.exe -ErrorAction SilentlyContinue
Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\Include" -ErrorAction SilentlyContinue
Get-ChildItem "$env:ProgramFiles\Unity Hub","$env:ProgramFiles\Unity\Hub\Editor" -ErrorAction SilentlyContinue
```

사용자 지정 설치가 있다면 알려진 **설치 폴더**에서 `UnrealEditor.exe`와 Build.version,
Unity Hub의 실제 Editor 설치 목록/버전과 Windows build module, Godot의 `--version`, Blender의 `--version`, `vswhere -all -products *` 및 C++ 구성 요소를
확인한다. 명령 미발견만으로 디스크 전체에 없다고 단정하지 않는다. 다음 실험 시작 로그에는
실제 RHI/adapter 이름, feature level, engine 버전, client/render 해상도, window DPI를 넣는다.
DPI는 엔진 창의 `GetDpiForWindow`, GPU 사용량/budget은 선택된 adapter의
[DXGI QueryVideoMemoryInfo](https://learn.microsoft.com/en-us/windows/win32/api/dxgi1_4/nf-dxgi1_4-idxgiadapter3-queryvideomemoryinfo)로
확인한다. TGP가 N/A이면 부하 중 측정·OEM 설정 기록 전까지 미확인으로 둔다.

## 네 후보 비교

공식 기능과 현재 코드에 근거한 **설계 판단**이다. 실측 성능·제작비·미술 점수를 엔진 이름으로
대체하지 않는다. Unity는 URP를 기준으로 하며 HDRP를 같은 비용으로 취급하지 않는다.

| 기준 | Unreal 네이티브 | Unity URP 네이티브 | Godot 네이티브 | 현재 pywebview + Three.js/WebGL2 |
|---|---|---|---|---|
| 미술·인물 작업 | Control Rig/IK retargeting/Sequencer, 인물·연출 통합 도구. 사실적 스타일에 한정되지 않음 | DCC rig → Humanoid Avatar/Animator, 장치·짧은 연출 Timeline. 사실적 목표의 재질·인물 표현과 두 설정의 작업성을 검증할 후보 | DCC → AnimationPlayer/AnimationTree/retargeting. 제한된 장면·고유 스타일 제작 가능; 실제 팀의 importer/rig 작업성 확인 | DCC glTF → AnimationMixer. 캐릭터·장면 편집/연출 검수 환경을 더 구성해야 함 |
| 자산 확보 | FBX skeletal/static·morph·LOD, Fab/MetaHuman 후보. 실제 확보 없음 | FBX 중심 모델/모션, Asset Store 후보. URP 재질 호환·개별 권리 확인, 기존 UE 자산 자동 전환 가정 금지 | glTF/FBX 수입. Blender 경유/엔진 재질 재작업 검토 | glTF/GLB·GLTFLoader와 필요한 decoder 배포. 소스 권리와 최적화 필요 |
| Python 연결 | Editor Python 제품 runtime 불가; C++ process/pipe adapter | C# launcher/비동기 binary pipe 후보; Windows player의 backend/API 지원 직접 검사 | OS.execute_with_pipe/native 확장 + 동일 backend 계약 | NativeBridge/worker 재사용성이 가장 큼. 앱 세션/결과 registry는 여전히 새 기능 |
| 한글·수치 UI | UMG/Slate Composite Font·DPI. 정확한 문자열·복사·입력 새 검증 | UI Toolkit/TextCore font fallback 후보. 긴 한글·glyph atlas·복사/키보드·DPI를 player에서 검사 | Control/Label/RichTextLabel·fallback/DPI. 정보층 재작성 | HTML/CSS 정보층 재사용 우수. 3D canvas와 DOM 분리 |
| 성능 | baked 조명/LOD/제한된 효과도 가능. Lumen·고급 기능을 기본 요구로 두지 않음 | rendering path·광원·shadow·render texture·MSAA 품질을 제어. URP 자체가 보급형 성능 보장은 아님 | Forward+/Mobile/Compatibility의 기능·성능 차이를 장비에서 확인. 자동 품질 하락으로 통과 금지 | WebView2 GPU/JS/process·투명 효과·자산 메모리/context loss 비용. 웹이라고 가볍지 않음 |
| Windows 패키징 | cook/package·C++ runtime·Python bundle·콘텐츠 | Windows x64 player·Mono/IL2CPP 선택·Python bundle. Editor 성공과 분리 | exe/PCK export + Python bundle. export가 Python을 자동 포함하지 않음 | Python + WebView2 runtime + 자산/decoder. 개발 실행과 설치판 분리 |
| 유지보수 | 엔진/C++/Blueprint/SDK·자산 pipeline·Python 고정. 빌드/통합 범위 큼 | Editor/URP/Timeline/UI package lock·C#·backend·자산 설정 고정. 금융 앱 라이선스/배포권 확인 필요 | engine/importer/script·native boundary·Python 고정. MIT 고지/제3자 권리 관리 | Python/pywebview/Three/WebView2·CSP/origin·GPU 자원 수명 관리 |
| 이번 판단 | 인물/연출 제작과 기본·고급의 품질/동시 성능을 검증할 후보 | 제작 도구·기본/고급 품질·동시 성능과 계약/배포권을 검증할 후보 | 목표 인물/재질 품질·두 설정·동시 성능과 제작 과정을 검증할 후보 | 데이터 UI 재사용 이점과 사실적 자산/인물 제작·보안·동시 성능을 검증할 후보 |

공식 근거는 다음과 같다. 문서가 기능의 존재를 보장하더라도 팔랑크스의 완성도나 생산성을
보장하는 것은 아니다.

- Unreal: [Control Rig](https://dev.epicgames.com/documentation/unreal-engine/animating-with-control-rig-in-unreal-engine),
  [IK 리타기팅](https://dev.epicgames.com/documentation/unreal-engine/ik-rig-animation-retargeting-in-unreal-engine),
  [FBX 파이프라인](https://dev.epicgames.com/documentation/unreal-engine/fbx-content-pipeline),
  [Composite Font](https://dev.epicgames.com/documentation/unreal-engine/font-asset-and-editor-in-unreal-engine),
  [Font DPI](https://dev.epicgames.com/documentation/unreal-engine/font-dpi-scaling-in-unreal-engine),
  [Lumen](https://dev.epicgames.com/documentation/unreal-engine/lumen-global-illumination-and-reflections-in-unreal-engine),
  [패키징](https://dev.epicgames.com/documentation/unreal-engine/packaging-your-project).
  [공식 개발 권장 사양](https://dev.epicgames.com/documentation/unreal-engine/hardware-and-software-specifications-for-unreal-engine)의
  RAM 32 GB·VRAM 8 GB 이상 안내는 팔랑크스의 제품 성능 보장/최저 사양과 구분한다.
- Unity: [URP 소개](https://docs.unity3d.com/6000.0/Documentation/Manual/urp/urp-introduction.html),
  [성능 설정](https://docs.unity3d.com/6000.0/Documentation/Manual/urp/configure-for-better-performance.html),
  [shading model](https://docs.unity3d.com/6000.0/Documentation/Manual/urp/shading-model.html),
  [Animator](https://docs.unity3d.com/6000.0/Documentation/Manual/class-AnimatorController.html),
  [Humanoid retargeting](https://docs.unity3d.com/6000.0/Documentation/Manual/Retargeting.html),
  [Timeline](https://docs.unity3d.com/Packages/com.unity.timeline@1.8/manual/index.html),
  [한글 등 fallback font](https://docs.unity3d.com/6000.0/Documentation/Manual/UIE-fallback-font.html),
  [Windows build](https://docs.unity3d.com/6000.0/Documentation/Manual/WindowsStandaloneBinaries.html).
  문서의 6000.0/Timeline 1.8은 조사 근거이며 설치된 버전이 아니다. 실험 전 지원되는 정확한
  Editor patch·URP/Timeline/UI package·API profile·Windows backend 조합을 한 번 고정한다.
- WebView/Three: [WebGLRenderer](https://threejs.org/docs/pages/WebGLRenderer.html)는 WebGL2를 사용하며
  r163부터 WebGL1을 지원하지 않는다. [GLTFLoader](https://threejs.org/docs/pages/GLTFLoader.html),
  [애니메이션](https://threejs.org/manual/pages/animation-system.html),
  [GPU 자원 해제](https://threejs.org/manual/pages/cleanup.html),
  [pywebview API](https://pywebview.flowrl.com/api/),
  [WebView2 배포](https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/distribution)를 확인했다.
- Godot: [수입 포맷](https://docs.godotengine.org/en/stable/tutorials/assets_pipeline/importing_3d_scenes/available_formats.html),
  [AnimationTree](https://docs.godotengine.org/en/stable/tutorials/animation/animation_tree.html),
  [retargeting](https://docs.godotengine.org/en/stable/tutorials/assets_pipeline/retargeting_3d_skeletons.html),
  [폰트](https://docs.godotengine.org/en/stable/tutorials/ui/gui_using_fonts.html),
  [OS/pipe](https://docs.godotengine.org/en/stable/classes/class_os.html),
  [렌더러](https://docs.godotengine.org/en/stable/tutorials/rendering/renderers.html),
  [Windows export](https://docs.godotengine.org/en/stable/tutorials/export/exporting_for_windows.html).

## 기존 코드의 재사용과 변경 경계

아래 경로·함수는 기준 커밋에서 직접 확인했다. 금융 서비스 내부에는 Decimal 문맥과
통계/최적화용 기존 float 경계가 함께 있다. 모든 내부 연산이 Decimal이라고 설명하지 않는다.
이 경계 전체를 Python에 유지하고 화면에서 수치 재계산·재정규화하지 않는다.

| 현재 코드 | 재사용 | 다음 구현에 필요한 변경 |
|---|---|---|
| [DesktopApplication](../../src/phalanx/desktop/application.py) `_start`, `_reject_start`, `job_status`, `request_close` | 단일 worker, generation/job ID, 요청에 맞는 거절, 재조회, 완료 후 종료 | HTML 결합 분리, session/request/revision adapter, Python 결과 registry 추가. `_start`가 이전 원본을 지우는 현재 구조를 바꾸고 active job과 selected result 분리 |
| [NativeBridge/_Lifecycle](../../src/phalanx/desktop/runtime.py) | 최소 API·native chooser 승인·opaque token·닫기/무음의 의미 | Unreal/Unity/Godot에서 pywebview 객체를 직접 사용하지 않음. 새 native chooser·launcher·IPC·window lifecycle adapter. scene unload와 앱 close 분리 |
| [AllocationInputService](../../src/phalanx/portfolio/allocation_input/service.py), [AllocationTargetsService](../../src/phalanx/portfolio/allocation_targets/service.py) | 같은 selection bytes, 한 번의 입력 준비, `calculate_bytes`와 기존 금융 문맥 | 금융 로직 변경 없음. 기존 타입/예외를 어댑터에서 표현 |
| [HistoryReader](../../src/phalanx/market_data/history/reader.py), [WindowsHistoryRepository](../../src/phalanx/market_data/history/windows_repository.py) | 공통 DB 검증·한 read snapshot·read-only/immutable·native guard | 엔진은 SQLite에 직접 접근하지 않음 |
| [desktop storage](../../src/phalanx/desktop/storage.py), [Windows files](../../src/phalanx/platforms/windows_files.py) | 원본 bytes·SHA, ACL, 상위 guard, flush·같은 디렉터리 atomic rename·no-overwrite·실패 정리 | 결과·선정·인증자료를 새 화면/자산 저장소와 섞지 않음. 그래픽 설정이 필요하면 별도 schema 설계 |
| [FormationRoomModel](../../src/phalanx/portfolio/formation_room/model.py) `to_payload`, [parser](../../src/phalanx/portfolio/formation_room/parser.py) | 검증된 presentation model, exact 문자열·시나리오·진단·provenance | typed DTO presenter 추가. 수치 UI를 선택 엔진의 2D UI로 새로 구성; full HTML을 IPC로 보내지 않음 |
| [view](../../src/phalanx/desktop/view.py), [shell](../../src/phalanx/desktop/assets/shell.js), [오프라인 renderer](../../src/phalanx/portfolio/formation_room/rendering.py) | 기존 WebView/오프라인 HTML 소비자 유지 | 네이티브 함교로 그대로 이식할 수 없음. 데이터·연출 동기화는 별도 presentation state |
| [audio.js](../../src/phalanx/portfolio/formation_room/assets/audio.js) | 최초 무음·사용자 동작 후 재생·silence/dispose의 요구사항 | native audio mixer로 구현/청취 필요. 기존 합성 음향을 최종 미술/음향 자산으로 간주하지 않음 |

[기존 application 테스트](../../tests/test_desktop_application.py),
[bytes 계약](../../tests/test_allocation_bytes.py), [native 경계](../../tests/test_desktop_runtime.py),
[Windows 파일](../../tests/test_windows_files.py), [DB](../../tests/test_windows_history_repository.py),
[회복 UI](../../tests/browser/verify_desktop_recovery.py)는 회귀 기반으로 유지한다.
새 통신/패키징/네이티브 창 검증이 이를 대체하지 않는다.

### 네이티브 엔진 공통 연결 제약

Epic은 [Python Editor 플러그인](https://dev.epicgames.com/documentation/unreal-engine/scripting-the-unreal-editor-using-python)이
Editor 전용이며 PIE·Standalone·cooked executable의 제품 런타임에서 사용할 수 없다고 명시한다.
[C++ CreateProc](https://dev.epicgames.com/documentation/unreal-engine/API/Runtime/Core/FGenericPlatformProcess/CreateProc)의
프로세스/pipe API로 별도 Python과 연결할 수 있지만, 신뢰·프레이밍·시간초과·재조회·종료
계약은 팔랑크스가 구현해야 한다. Godot의 pipe API도 같은 책임을 없애 주지 않는다.

Unity 후보는 C# `System.Diagnostics.Process`와 binary stdin/stdout adapter다.
[.NET stdout redirect 계약](https://learn.microsoft.com/en-us/dotnet/api/system.diagnostics.processstartinfo.redirectstandardoutput?view=net-10.0)의
`UseShellExecute=false`·비동기 stream 처리/교착 주의를 따른다. 이것은 모든 Unity backend의
지원 보장이 아니다. 첫 실험은 Windows x64 Mono player와 선택한 .NET API profile을 고정하는
안을 우선 검토하고 실제 패키지에서 실행한다. [Unity .NET profile](https://docs.unity.com/en-us/engine/6000.3/manual/scripting/environment-and-tools/overview-of-dot-net-in-unity/dotnet-profile-support)과
[Windows backend 설정](https://docs.unity.com/en-us/engine/6000.6/manual/platform-specific/windows/playersettings)을 확인하고,
IL2CPP 전환은 별도 검증으로 둔다. 길이 프레임은 line reader가 아닌 BaseStream으로 처리한다.

금액/비중 문자열과 presentation DTO만 화면에 전달한다. 원본 bytes는 Python에 남기고
저장은 불변 result ID로 요청한다. 입력 토큰은 실제 chooser가 승인한 파일에만 발급한다.
[실험 통신 초안](../command-bridge/spec.md#다음-실험의-통신-계약-초안)에 session 재시작,
응답 유실, EOF/crash, 정상 종료 순서를 명시했다. UI thread에서 동기 IPC 대기를 하지 않는다.

앱 세션 서비스는 특정 방 Scene/Actor/DOM에 소유되지 않는다. Unity의 [persistent root](https://docs.unity3d.com/6000.0/Documentation/ScriptReference/Object.DontDestroyOnLoad.html),
Godot의 [Autoload](https://docs.godotengine.org/en/stable/tutorials/scripting/singletons_autoload.html),
Unreal의 [GameInstance](https://dev.epicgames.com/documentation/en-us/unreal-engine/API/Runtime/Engine/UGameInstance) 계열은 구현 후보지만 어떤 API도 Python job/result
보존을 자동 해결하지 않는다. **room epoch와 job generation을 분리**, Python 결과 registry와
안정 ID의 알림함을 두고 공간은 snapshot 소비자만 된다. 놀이 checkpoint는 장면 자산과 별도로
앱 세션에 남는다. [수명 계약](../command-bridge/spec.md#공간작업결과놀이의-수명)의
알림 복귀·안전한 tick 정지·재개·상한 정책을 구현 검증한다. IPC와 프로세스 분리는 CPU/RAM/열
경쟁의 제거가 아니며 [동시 부하 계획](../command-bridge/spec.md#분석과-게임의-자원-경쟁)으로 확인한다.

배포 실험은 Windows에서 만든 Python **onedir bundle**을 우선 검토한다.
[PyInstaller의 공식 설명](https://pyinstaller.org/en/stable/operating-mode.html)에 따라 대상 OS에서
빌드하며, 현재 `importlib`로 불러오는 pywin32와 numpy/scipy 등의 DLL·데이터·고지를 별도로
확인한다. 엔진 폴더에 Python 런타임이 들어갔다고 원본 ACL/저장 정책이 자동 보장되지는 않는다.
깨끗한 Windows 사용자/폴더에서 에디터와 개발 venv 없이 실행·저장·종료를 검증해야 한다.
기존 `.venv` 복사나 WSL 호출은 배포 구조로 채택하지 않는다.

### WebView 대형 자산과 현재 보안의 양립 조건

현재 [shell CSP](../../src/phalanx/desktop/assets/shell.html)에는 `connect-src 'none'`,
[결과 CSP](../../src/phalanx/portfolio/formation_room/assets/template.html)에는
`font-src 'none'`, `media-src 'none'`까지 있다. 결과 iframe은 `sandbox="allow-scripts"`만
허용하는 `srcdoc`이고, privileged top-level 탐색은 `about:blank`와 정확한 패키지 HTML data URI뿐이다.
HTTP server도 꺼져 있다. 따라서 외부 CDN/임의 `file:`/GLB fetch를 그대로 추가할 수 없다.

[WebView2 로컬 콘텐츠 문서](https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/working-with-local-content)는
NavigateToString의 2 MB 한도와 virtual host mapping을 설명한다. 큰 모델·텍스처를 HTML/base64에
모두 넣는 방식은 적절한 제작 경로가 아니다. 후보 설계는 패키지 소유의 읽기 전용 **자산 전용
origin**과 고정 manifest다. 사용자 JSON/DB·결과·앱 설정 디렉터리는 절대 매핑하지 않는다.

구현 전 origin/CORS/CSP, 허용 MIME·크기·해시·정규화 경로, decoder/WASM/worker, 폰트/음향,
정상/비정상 URL·상대 경로 탈출·GPU context loss를 검사해야 한다. renderer에는 bridge 권한을
주지 않고 허용된 postMessage만 부모가 검증한다. opaque iframe에서 자산 요청을 허용하는
정확한 CORS 방식은 실험할 설계 문제이며 이미 해결됐다고 보지 않는다. `allow-same-origin`이나
전체 로컬 드라이브 접근을 켜서 통과시키지 않는다. [WebView2 보안 원칙](https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/security)에
따라 문서 origin과 메시지 발신자를 검증한다. 현재 JS의 iframe dispose와 별개로 geometry,
texture, render target, mixer, decoder, animation loop의 해제가 필요하다.

## 라이선스·자산·운영 비용

- [Unreal 라이선스 안내](https://www.unrealengine.com/license)와 [EULA](https://www.unrealengine.com/eula/unreal)를
  기준으로 배포·과금 방식에 따른 royalty/seat 적용을 확인한다. 금융 앱이라는 이유만으로
  무조건 seat 또는 무조건 무료라고 결론내리지 않는다. 엔진 계약과 개별 자산의 권리는 별개다.
- [Unity Editor Software Terms](https://unity.com/legal/editor-terms-of-service/software), 2026-06-30 갱신:
  §4는 게임/엔터테인먼트만을 위한 용도가 아닌 경우도 Industry Customer 정의에 포함한다.
  §1.1은 Personal $200,000 및 Industry $1,000,000의 Total Finances 조건과 산정 주체를 구별한다.
  §2.2.1은 Industry Customer의 Runtime 배포에 Unity의 명시적 허가를 요구한다.
  팔랑크스 적용은 **미확인**이다. SF 게임 표현이 있는 금융 앱을 일반 게임 또는 Personal 무료로
  단정하지 않으며 실제 용도·사용 주체/고객 재무·계약/배포권을 확인한 뒤 채택한다.
  엔진과 Asset Store 자산의 라이선스도 별도다. 이번 조사에서 구독·구매·외부 문의를 실행하지 않았다.
- [Godot MIT](https://godotengine.org/license/), [Three.js MIT](https://github.com/mrdoob/three.js/blob/dev/LICENSE),
  [pywebview BSD 3-Clause](https://github.com/r0x0r/pywebview/blob/master/LICENSE) 고지와 제3자 dependency
  고지가 필요하다. 낮은 엔진 라이선스 비용이 인물·모션·UI 제작비를 없애 주지는 않는다.
- 환경 아트, 캐릭터/rig/모션, technical art·조명, 데이터 UI, 음향 검수를 역할로 구분한다.
  같은 사람이 수행할 수 있으나, 현재 인력·외주 예산·자산 조달 기간은 미확정이다.
  특히 사실적 인물의 피부·눈·머리·의복, rig/착석 접점과 함교의 재질/조명을 함께 정제하는
  작업이 병목이다. 기본에서도 매력을 유지할 자산/설정 변형의 제작·검수 비용을 포함한다.

## 다음 결정의 근거와 기록

[단일 실험](../command-bridge/spec.md#6-다음-단일-기술-실험-함교-한-조각)의 기능 / 성능·안정성 /
미술·음향 / 게임 감각을 별도로 판정한다. 처음은 함교 일부·장치 1개·인물 1명·창밖 일부·
작은 선택 놀이·이동 fixture·기존 합성 계산 연결로 제한한다. 이것만으로 엔진/지원 사양을
확정하지 않고 같은 후보에서 첫 방의 대표 자산·인물 수·장치/창밖 동작을 갖춘 동시 부하 검증으로 이어간다.

확정 근거는 **대표 함교와 실제 기존 Python 분석을 함께 실행한 Windows 패키지**다.
기본·고급 각각에서 프레임 시간·입력 응답·RAM/VRAM·계산 시간 악화·원본 저장 일치와
캐릭터/상호작용의 매력을 확인한다. mock 작업, 그래픽만 실행한 수치, 개발 노트북의 성공만으로
확정하지 않는다. 실물 PC를 확인한 뒤 목표를 정하고 측정된 장면·입력·설정 범위로 지원 사양을 기록한다.

실험 후보가 실패하면 자산·통신·렌더링·동시 부하의 원인을 구분해 개선하고, 구조적 제약이나
수용 불가한 계약/배포 조건이 확인될 때 후보 선택을 다시 연다. 캐주얼 전환 또는 초고사양 전용
결정으로 성능/미술 문제를 덮지 않는다. [기본·고급 설계](../command-bridge/spec.md#기본고급-그래픽-설정)의
공통 인물·반응 기준을 유지한다.

engine/RHI/adapter/driver·client/render 픽셀·DPI·전원/열·asset/license revision·Python lock·
backend thread 설정·분석 입력 해시/규모·패키지 해시와 설정별 판정 증거를 남긴다.
미술 방향은 이번에 정했으며 **엔진·지원 사양은 측정 전까지 미확정**이다.

앞선 Windows 조회는 장비/도구 확인이다. PR #25의 Linux/Chromium/native Windows 검증은
기존 금융/데스크톱 기반의 증거이며 새 엔진·함교·성능·실제 청취의 증거가 아니다.
이번 갱신은 문서·경로·범위·보호 자료 해시·공백 검사만 수행하며 제품 코드 변경, 설치,
유료 자산 구매, staging·commit·push·PR은 하지 않는다.
