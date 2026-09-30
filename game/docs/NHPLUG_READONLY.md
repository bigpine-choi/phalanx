# NH투자증권 NHPLUG 현재가 연결

팔랑크스 리서치 화면의 **NH 현재가**와 관심그룹 표의 **표시 종목 시세 갱신 · 최대 20**은 국내 종목의 KRX 현재가를 별도로 조회한다. 두 화면은 하나의 순차 조회 큐와 별도 시세 캐시를 공유한다. KIS 수정주가 일봉·계좌·배분과 출처·시각을 구분한다. 이 연결은 `currentPrice` 시세 조회만 호출하며 주문·계좌 API는 호출하지 않는다.

표 갱신은 현재 그룹·검색·정렬 결과의 첫 20개 적격 코드가 대상이다. 중단하거나 표를 닫으면 대기 요청을 취소하고 진행 중인 한 건만 원래 코드에 반영한다. 실패해도 이전 가격과 수신 시각을 유지한다. 수신 시각은 유효 응답 뒤 기록하며 거래소 체결 시각이 아니다. 5분을 초과하면 오래된 시세로 표시한다.

## 한 번만 설정하기

게임에 키를 붙여넣지 않는다. 현재 Windows 게임은 WSL의 Python 연결 프로그램을 실행하고, [NH 공식 Python SDK](https://github.com/PLUG-OpenAPI/nhplug-sdk)가 WSL 사용자 홈의 `~/.nhplug/.env`를 자동으로 읽는다. 이 PC의 기본 WSL 사용자라면 파일은 `/home/hansol/.nhplug/.env`다. 키 값은 이 파일에만 둔다.

WSL 터미널에서 다음을 **최초 1회** 실행한다. 편집기가 열리면 아래 네 줄의 예시를 실제 발급값으로 바꿔 저장한다. 셸 명령 인수에 키를 직접 적지 않으므로 명령 기록에 남기지 않는다.

```sh
mkdir -p ~/.nhplug && chmod 700 ~/.nhplug
umask 077 && nano ~/.nhplug/.env
chmod 600 ~/.nhplug/.env
uv pip install --python /home/hansol/projects/phalanx/.venv/bin/python nhplug
```

이 PC의 Python 가상환경에는 `pip`가 없어 `uv`로 설치했다. 설치와 실제 현재가 조회를 확인했으며 이후 게임에서 키를 다시 입력할 필요는 없다. 다른 환경에서 `uv`가 없다면 해당 Python 환경의 패키지 설치 방법을 먼저 확인한다.

```text
NHPLUG_APP_KEY=발급받은_앱키
NHPLUG_APP_SECRET=발급받은_앱시크릿
NHPLUG_BASE_URL=https://api.nhplug.com:8443
NHPLUG_AUTH_URL=https://api.nhplug.com:8443
```

폴더는 사용자만 접근하도록 `0700`, 파일은 `0600`으로 설정한다. 키 파일은 Git 저장소와 Godot `user://` 폴더에 두지 않는다. `NHPLUG_ENV_FILE`을 설정하면 SDK가 지정한 다른 파일을 먼저 읽는다. SDK의 순서는 실제 환경변수 → `NHPLUG_ENV_FILE` → 프로젝트 `.env` → `~/.nhplug/.env`다. 따라서 키를 바꿀 때에도 게임 UI 입력은 필요 없다.

NH SDK(`nhplug`)를 WSL의 게임 연결용 Python 환경에 한 번 설치해야 한다. 기본 실행기는 기존 KIS와 같은 `/home/hansol/projects/phalanx/.venv/bin/python`이며, 다른 실행기는 Windows 환경변수 `PHALANX_NH_WSL_PYTHON`으로 지정할 수 있다. WSL 배포판은 `PHALANX_NH_WSL_DISTRO`로 지정하며, 값이 없으면 기존 KIS 설정을 사용한다. 앱키만 있고 앱시크릿이 빠졌거나 SDK가 설치되지 않았다면 화면에 설정 안내만 표시한다. 키·토큰·원문 오류는 게임 결과 파일에 쓰지 않는다.

N2 계정은 [공식 설정 안내](https://github.com/PLUG-OpenAPI/nhplug-sdk#설정--파일-하나만-관리하면-됩니다)에 따라 `NHPLUG_BASE_URL`, `NHPLUG_AUTH_URL`, `NHPLUG_INSTRUMENTS_BASE`를 모두 `n2plug.com` 주소로 맞춘다.

## 연결 범위와 다음 활용

NHPLUG는 [국내·해외 주식, 파생, 채권, 금현물의 시세·계좌·주문 API](https://github.com/PLUG-OpenAPI)를 제공한다. 공식 SDK가 인증, 24시간 토큰 캐시, REST 호출과 속도 제한을 처리한다. 이번 연결에서는 출처와 시각이 표시되는 **국내주식 KRX 현재가**만 추가했다. 향후 KIS와 NH의 같은 시각·같은 시장 기준 시세를 비교하거나 종목 마스터를 교차 검증하는 용도로 확장할 수 있다. NH의 `currentDaily`를 KIS의 1년 수정주가와 바로 섞으면 조회 기간·정규장/전체장·수정주가 기준이 달라질 수 있어 이번에는 사용하지 않는다.

공식 SDK 호출은 `POST /krstock/quote/v1/currentPrice`의 `iem_cd`와 `market_cd=KRX`를 사용하고, 응답 `Output_0.stck_prpr`가 양의 원화 정수일 때만 화면에 표시한다. 이 화면에서는 현재가를 별도 값으로 보여 준다. 2026-09-30 23:27:57–58 KST에 기능 브랜치 F5 게임에서 `005930`·`005935`·`069500`의 3종목 갱신을 한 번 실행해 모두 성공했다. 보통주·우선주·ETF의 표 값·수신 시각과 선택 종목의 리서치 연결을 확인했다. 수신 시각은 응답 완료 후 기록하며 요청 시작 시각이 아니다. 코드·테스트에는 키를 넣지 않는다. 부분 실패는 모의 응답으로 확인했으며 실제 서비스 장애·다종목 장시간 운용·다른 PC 환경은 미검증이다.

`PHALANX_NH_QUOTE_CACHE`는 시세 캐시 디렉터리, `PHALANX_NH_OFFLINE=1`은 NH 네트워크 차단 설정이다. 테스트는 프로필·리서치·NH 캐시를 임시 경로로 분리한다. 검증 기록과 직접 확인 순서는 [WATCHLIST_QUOTES_CHART_VALIDATION.md](WATCHLIST_QUOTES_CHART_VALIDATION.md)를 따른다.

2026-10-01 main 통합본은 같은 공유 큐와 브리지를 사용한다. 이번 통합 F5 검수는 격리된 합성 가격과 일봉, NH 오프라인 모드로 수행했다. 이전 가격·시각 유지, 정렬 후 선택, 차트 조작과 종료·재실행 복원을 확인했으며 실제 NH API를 재호출하지 않았다. [통합 검증 기록](WATCHLIST_MAIN_INTEGRATION_VALIDATION.md)
