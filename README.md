# Phalanx

Phalanx는 한국 주식 포트폴리오 운용 프로그램입니다. 한국투자증권 실전계좌의 예수금 총액과 국내주식 잔고를 읽어 불변 JSON 스냅샷으로 저장하며, 사람이 직접 관리하는 로컬 투자 후보 유니버스를 제공합니다.

## 현재 마일스톤의 안전 경계

- 한국투자증권 실전투자 환경만 지원합니다. 모의투자 URL, 모의계좌, 실전·모의 분기 로직은 구현하지 않습니다.
- 계좌 조회는 **READ ONLY**입니다. 주문·정정·취소 API와 주문용 POST 요청을 구현하지 않습니다.
- OAuth 접근토큰 발급 POST와 국내주식 잔고조회 GET만 이 마일스톤의 네트워크 범위에 포함됩니다.
- `dnca_tot_amt`는 **예수금 총액**으로만 취급합니다. 가용현금, 주문가능현금 또는 Phalanx 투자예산을 의미하지 않습니다.
- `orderable_cash`는 이번 마일스톤에서 제공되지 않아 `None`/`null`로 유지하고 터미널에는 `미제공`으로 표시합니다. 향후 매매계획 단계에서 매수가능조회 API의 `nrcvb_buy_amt`를 별도로 확인합니다.
- API 키, 앱 시크릿, 계좌번호와 접근토큰은 Git에 포함하지 않습니다. `runtime/` 제외 규칙은 방어 목적으로 유지합니다.

현재 브랜치는 외부 자격증명, OAuth 토큰 캐시, 국내주식 잔고 파싱·연속조회, 불변 스냅샷 저장과 read-only CLI 오케스트레이션까지 구성합니다. 실제 자격증명과 실제 KIS API는 자동 테스트에서 사용하지 않습니다.

## 개발 환경

Python 3.12와 [uv](https://docs.astral.sh/uv/)를 사용합니다.

```bash
uv sync --all-groups
uv run pytest
uv run ruff check .
uv run mypy src
```

단위테스트는 합성된 KIS 실전 API 응답을 Mock으로 사용하며 `pytest-socket`으로 실제 네트워크를 차단합니다. 자동 테스트와 CI에서는 실제 한국투자증권 API를 호출하지 않습니다.

## 로컬 자격증명

실제 KIS 자격증명은 저장소 외부의 다음 파일에만 저장합니다.

```text
~/.config/phalanx/credentials.env
```

프로젝트 루트의 `.env` 파일은 저장하거나 읽지 않습니다. `.env.example`은 필요한 변수명과 설명을 확인하기 위한 템플릿일 뿐이며 실제 값을 입력하거나 루트 `.env`로 복사하지 않습니다.

자격증명 파일이 아직 없을 때만 다음 명령으로 저장소 외부에 안전하게 준비합니다. 두 번째 명령은 기존 파일을 덮어쓸 수 있으므로 이미 만든 자격증명 파일에는 다시 실행하지 않습니다.

```bash
install -d -m 700 "$HOME/.config/phalanx"
install -m 600 .env.example "$HOME/.config/phalanx/credentials.env"
stat -c '%a %n' ~/.config/phalanx ~/.config/phalanx/credentials.env
```

`install`은 디렉터리와 파일을 처음부터 각각 `0700`, `0600` 권한으로 만듭니다. 마지막 명령으로 권한을 확인한 뒤 사용자가 저장소 외부의 `credentials.env`를 직접 편집합니다.

필요한 변수는 다음 세 가지입니다.

- `PHALANX_KIS_APP_KEY`
- `PHALANX_KIS_APP_SECRET`
- `PHALANX_KIS_ACCOUNT_NUMBER` (`8자리-2자리`)

프로그램은 이 파일이 없거나, 일반 파일이 아니거나, 심볼릭 링크이거나, 현재 사용자의 소유가 아니거나, 권한이 정확히 `0600`이 아니면 파일을 생성·수정하지 않고 안전한 설정 방법만 안내한 뒤 실패합니다. 상위 디렉터리도 현재 사용자 소유와 정확한 `0700` 권한을 요구합니다.

실제 값을 프로젝트 루트, 문서, 테스트 fixture, 커밋 메시지 또는 터미널 캡처에 기록하지 않습니다.

## OAuth 토큰 캐시

KIS 접근토큰 캐시의 기본 운영 위치도 저장소 외부로 고정합니다.

```text
~/.cache/phalanx/token-cache/kis-access-token.json
```

프로그램은 `~/.cache/phalanx`와 그 아래 `token-cache`를 필요할 때 생성하며 두 디렉터리를 생성 순간부터 `0700`으로 보호합니다. 기존 `~/.cache`의 권한은 변경하지 않습니다. 캐시 JSON, 잠금 파일과 원자 교체용 임시파일은 생성 순간부터 `0600`입니다.

두 application-owned 디렉터리가 심볼릭 링크이거나, 현재 사용자 소유가 아니거나, 권한이 정확히 `0700`이 아니면 자동 복구나 `chmod` 없이 실패합니다. 현재 작업 디렉터리, 프로젝트의 `runtime/token-cache`, `.env`, `XDG_CACHE_HOME`을 기본 캐시 위치로 사용하지 않습니다. `runtime/` Git 제외 규칙은 방어 목적으로 유지합니다.

## 스냅샷 저장 위치

완성된 계좌 스냅샷의 기본 운영 위치는 저장소 외부로 고정합니다.

```text
~/.local/share/phalanx/snapshots/
```

경로는 실행 시점의 `Path.home()`을 기준으로 결정하며 현재 작업 디렉터리와 `XDG_DATA_HOME`을 사용하지 않습니다. 기존 `~/.local/share`의 권한은 변경하지 않고, 프로그램이 관리하는 `phalanx`와 `snapshots` 디렉터리는 생성·검증 시 각각 정확한 `0700`을 요구합니다. 최종 JSON과 원자 저장용 임시파일은 생성 순간부터 `0600`입니다. 저장소 내부 `runtime/`은 production 저장 위치로 사용하지 않습니다.

스냅샷 JSON 안의 timezone-aware 절대시각은 변환하지 않고 보존합니다. 사용자가 보는 파일명에는 조회 완료시각을 한국시간으로 변환한 `+0900`을 사용합니다.

## 투자 후보 유니버스

투자 후보 유니버스는 사용자가 직접 등록한 한국 주식의 종목코드, 종목명, 시장, 활성화 여부와 선택적 메모를 로컬 JSON 파일에 저장합니다. 이 기능은 KIS API나 다른 네트워크에 접속하지 않으며 시세 조회, 최적화, 주문 기능을 포함하지 않습니다. 계좌 스냅샷의 **READ ONLY** 경계에도 영향을 주지 않습니다.

현재 MVP의 로컬 유니버스 저장소는 POSIX 파일 권한과 디렉터리 파일 디스크립터를 사용하는 **Linux와 WSL만 지원**합니다. 기본 저장 위치는 다음과 같습니다.

```text
~/.local/share/phalanx/universe.json
```

저장 디렉터리와 JSON/잠금 파일은 각각 `0700`, `0600` 권한으로 보호합니다. 저장은 같은 디렉터리의 private 임시파일을 디스크에 동기화한 뒤 원자 교체하므로 쓰기 실패 시 기존 파일을 보존합니다. 손상되거나 지원하지 않는 JSON은 자동 초기화하거나 덮어쓰지 않고 명확한 오류로 보고합니다.

macOS와 네이티브 Windows에서는 이 저장소를 시작하지 않고 미지원 플랫폼 오류를 반환합니다. 네이티브 Windows 지원은 향후 GUI·패키징 단계에서 운영체제에 맞는 별도 저장소 구현으로 제공합니다.

종목은 등록 시 기본적으로 활성화됩니다. 종목코드는 공백 없는 6자리 숫자이고 시장은 `KOSPI` 또는 `KOSDAQ`이어야 합니다.

```bash
uv run phalanx universe add 005930 삼성전자 --market KOSPI --note "반도체 대형주"
uv run phalanx universe add 035720 카카오 --market KOSPI
uv run phalanx universe list
uv run phalanx universe disable 035720
uv run phalanx universe enable 035720
uv run phalanx universe remove 035720
```

종목코드와 실제 상장 시장의 일치 여부를 네트워크로 조회하거나 검증하지 않으므로 사용자가 올바른 값을 입력해야 합니다. CLI는 저장소를 직접 다루지 않고 유니버스 서비스 계층을 호출합니다. 향후 GUI도 같은 서비스 계층을 사용할 수 있습니다.

## CLI 계약

기본 명령만으로 즉시 실전계좌 read-only 스냅샷을 수행합니다.

```bash
uv run phalanx
```

다음 명시적 별칭도 같은 동작을 제공합니다.

```bash
uv run phalanx account snapshot
```

모듈 진입점도 동일한 명령을 실행합니다.

```bash
uv run python -m phalanx account snapshot
```

CLI에는 환경 선택 옵션이 없으며 모의투자 모드도 제공하지 않습니다.

조회 시작·완료시각은 터미널에서 한국시간 `YYYY-MM-DD HH:MM:SS KST` 형식으로 표시합니다. 자산 대사를 돕기 위해 다음 두 값을 표시 계층에서 `Decimal`로 역산합니다.

- 기타 자산·결제조정 = 총자산 - 예수금 총액 - 주식평가액
- 부채 등 차감액 = 총자산 - 순자산

두 값은 KIS가 별도 필드로 직접 제공한 금액이 아니라 익일정산금액, 가수도정산금액, 금일매매금액 같은 결제·정산 요소가 반영된 계정 차이를 이해하기 위한 표시용 역산값입니다. 양수·0·음수가 모두 가능하며, 오류로 단정하거나 현금·가용현금·주문가능현금·투자예산으로 해석하지 않습니다. 스냅샷 JSON schema에는 이 파생값을 추가하지 않습니다. 향후 기준가 계산에는 총자산이나 이 파생값이 아니라 `net_assets`인 순자산금액을 사용합니다.

종료 코드는 정상 `0`, 설정 `10`, 인증 `20`, 잔고조회 `30`, 스냅샷 저장 `40`, 예기치 않은 오류 `70`, 사용자 중단 `130`으로 구분합니다. 예상 오류와 예기치 않은 오류 모두 원본 HTTP 요청·응답이나 Python traceback을 출력하지 않습니다.

## 실제 계좌 read-only 스모크 테스트 절차

이 절차는 KIS 인증·잔고조회 구현이 완료된 뒤 개발자가 로컬에서 명시적으로 수행하는 수동 검증입니다. 자동화 테스트나 CI 절차에 추가하지 않습니다.

1. KIS Developers에서 발급한 실전투자 앱 키·앱 시크릿과 실전계좌 번호를 `~/.config/phalanx/credentials.env`에 설정합니다.
2. `stat -c '%a %n' ~/.config/phalanx ~/.config/phalanx/credentials.env`로 각각 `700`, `600`인지 확인합니다.
3. 프로젝트 루트에 `.env` 또는 실제 자격증명 파일이 없는지 확인합니다.
4. 작업 트리에 실제 비밀정보가 없는지 확인합니다. 비밀값 자체를 검색 명령 인자로 넘기거나 출력하지 않습니다.
5. `uv run phalanx`를 한 번 실행합니다.
6. 터미널에 `실전계좌 · READ ONLY` 표시, 마스킹된 계좌번호, 예수금 총액, 주식평가액, 총자산, 종목별 잔고가 출력되는지 확인합니다.
7. 주문가능현금은 `미제공`으로 표시되고 예수금 총액이 그 값으로 복사되지 않았는지 확인합니다.
8. `~/.local/share/phalanx/snapshots/`에 JSON 한 개가 생성되고 원본 계좌번호·앱 키·앱 시크릿·접근토큰이 포함되지 않았는지 확인합니다.
9. 연속조회 대상 계좌라면 HTS의 보유종목 수와 스냅샷의 실제 보유종목 수를 비교합니다. 보유수량 0인 잔고는 별도 목록인지 확인합니다.
10. 실행 전후 미체결·체결 내역에 변화가 없음을 확인합니다. 이 절차에서는 주문·정정·취소 호출을 절대 수행하지 않습니다.

상세 구현 계획은 [`docs/plans/kis-account-snapshot.md`](docs/plans/kis-account-snapshot.md)에 있습니다.
