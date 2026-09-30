# NH투자증권 NHPLUG 현재가 연결

팔랑크스 리서치 화면의 **NH 현재가** 버튼은 선택한 국내 종목의 KRX 현재가를 별도로 조회한다. 기존 KIS 수정주가 일봉 차트와 계좌·배분 값은 그대로 두며, 서로 다른 조회 시각과 가격 기준을 한 값처럼 합치지 않는다. 이 연결은 `currentPrice` 시세 조회만 호출한다. 주문·계좌 API는 호출하지 않는다.

## 한 번만 설정하기

게임에 키를 붙여넣지 않는다. 현재 Windows 게임은 WSL의 Python 연결 프로그램을 실행하고, [NH 공식 Python SDK](https://github.com/PLUG-OpenAPI/nhplug-sdk)가 WSL 사용자 홈의 `~/.nhplug/.env`를 자동으로 읽는다. 이 PC의 기본 WSL 사용자라면 파일은 `/home/hansol/.nhplug/.env`다. 키 값은 이 파일에만 둔다.

WSL 터미널에서 다음을 **최초 1회** 실행한다. 편집기가 열리면 아래 네 줄의 예시를 실제 발급값으로 바꿔 저장한다. 셸 명령 인수에 키를 직접 적지 않으므로 명령 기록에 남기지 않는다.

```sh
mkdir -p ~/.nhplug && chmod 700 ~/.nhplug
umask 077 && nano ~/.nhplug/.env
chmod 600 ~/.nhplug/.env
/home/hansol/projects/phalanx/.venv/bin/python -m pip install nhplug
```

이 Python 환경에 `pip`가 없다면 `uv pip install --python /home/hansol/projects/phalanx/.venv/bin/python nhplug`로 설치할 수 있다. 이후 게임에서 키를 다시 입력할 필요는 없다.

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

공식 SDK 호출은 `POST /krstock/quote/v1/currentPrice`의 `iem_cd`와 `market_cd=KRX`를 사용하고, 응답 `Output_0.stck_prpr`가 양의 원화 정수일 때만 화면에 표시한다. `currentPrice`는 정규장 기준 필드도 제공하지만, 이번 화면에서는 현재가를 별도 값으로만 보여 준다. 실제 NH 키를 사용한 호출 검증은 키 파일 설정 후에만 가능하다. 코드·테스트에는 키를 넣지 않는다.
