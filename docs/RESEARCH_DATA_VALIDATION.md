# 종목 분석 · KIS 일봉과 공식 재무자료 · 2026-09-29

현재 시장·리서치는 같은 KIS 일봉을 공유한다. 보유종목 전체와 관심종목으로 범위를 확장했고, 예시 가격·지수와 샘플 계좌는 제거했다. 최신 동작은 [시장 연결 안내](LIVE_MARKET_WORKSPACE.md)를 참고한다. 아래 검증 결과와 화면 갤러리는 초기 연결 당시의 기록이다.

## 데이터 범위

| 항목 | 구현/기준 |
| --- | --- |
| 가격 | 실제 보유종목과 관심종목. 초기 관심목록은 삼성전자, SK하이닉스, 현대차, NAVER, KODEX 200. 한국투자증권 KRX 수정주가 일봉, 전일까지 최근 365일 요청. 당일 현재가/실시간 스트리밍 아님 |
| 차트 | 22/66/252거래일, 캔들/라인, 온전한 20거래일 평균, 실제 거래량·거래일·OHLC 호버. 월/연 버튼은 거래일 수로 근사 |
| 재무 | 삼성전자 2023–2025 연결·연간 매출, 영업이익, 영업활동 순현금흐름, 같은 기간 매출 기준 영업이익률 |
| 다른 기업 | 공식 자료를 아직 연결하지 않아 ‘자료 없음’. ETF에는 기업 재무제표 적용 안 함 |
| 미포함 | 분기/반기 추이, PER/PBR/컨센서스, 공시 알림, 실제 계좌 평가·주문 |
| 상태 | 조회 중·완료·캐시·실패 구분. 출처, 거래일, 실제 수신 KST 시각, 수정주가 기준 표시. 실패 시 이전 종목 데이터나 가상 가격으로 대체하지 않음 |

공식 재무는 **자동 갱신이 아닌 출처 확인본**이다. OpenDART 키를 발급받지 않았다는 사용자 확인에 따라 현재 사용하지 않는다. 키가 있을 때 `company.json`으로 종목/기업 식별자를 확인한 뒤 연간 CFS 보고서만 조회하는 경로는 준비했지만, 실제 OpenDART 인증·응답 검증은 미수행이다. 모의 응답 파싱 검사를 실서비스 통과로 해석하지 않는다.

## 기존 KIS 연동 재사용

이미 사용 중이던 WSL Ubuntu-24.04의 `/home/hansol/projects/phalanx/.venv/bin/python`과 `phalanx.market_data.history.application.production_history_reader`를 호출한다. 이 백엔드의 코드/계좌 데이터는 변경하지 않았다.

기존 인증 파일: `/home/hansol/.config/phalanx/credentials.env` (0600). 토큰 캐시: `/home/hansol/.cache/phalanx/token-cache/kis-access-token.json` (0600). 인증값·계좌번호는 출력하거나 Windows 코드/캐시/인수에 복사하지 않았다. 채팅에 제공된 키를 소스에 입력하지 않고 기존 설정을 재사용했다.

Godot은 키를 보유하지 않는다. `tools/kis_research_bridge.py`를 WSL에서 실행하고 비밀값 없는 OHLCV JSON만 읽는다. 기존 백엔드가 인증·토큰 캐시/잠금·TLS·페이지 처리·속도 제한을 담당한다. 한 Godot 실행에서 한 조회만 진행하고 빠른 종목 전환은 마지막 대기 요청으로 합친다. 응답의 요청 번호/종목과 현재 세대를 모두 검사한다. 자식 호출은 50초, 화면 측은 55초 한도이며 UI를 정지시키지 않는다. 종료 시 Windows 실행 프로세스를 중단하며 WSL 내부 작업은 최대 50초 제한으로 종료된다.

환경이 다르면 `PHALANX_KIS_WSL_DISTRO`, `PHALANX_KIS_WSL_PYTHON`으로 지정한다. 현재 구현은 이 PC의 Windows+WSL 개발 환경용이며 내보낸 게임의 배포용 독립 백엔드 패키지는 아니다. 외부 HTTP 서버, 주문·잔고 API, 새 인증 발급은 추가하지 않았다.

## 출처와 수치

- [한국투자증권 공식 일봉 예제](https://github.com/koreainvestment/open-trading-api/tree/main/examples_llm/domestic_stock/inquire_daily_itemchartprice): `/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice`, `FHKST03010100`, KRX `J`, 일봉 `D`, 수정주가 `0`. 백엔드의 기존 구현을 재사용한다. 거래일 무누락이나 배당 포함 총수익률은 보장하지 않는다.
- [삼성전자 공식 연결 재무자료](https://www.samsung.com/global/ir/financial-information/audited-financial-statements/): K-IFRS 연결 기준. 2023은 2024 보고서 비교 열, 2024/2025는 2025 보고서 열을 사용했다. 확인일 2026-09-28.
- [2025 연결 손익](https://images.samsung.com/is/content/samsung/assets/global/ir/docs/2025_con_quarter04_soi.pdf) · [2025 연결 현금흐름](https://images.samsung.com/is/content/samsung/assets/global/ir/docs/2025_con_quarter04_cf.pdf)
- [2024 연결 손익](https://images.samsung.com/is/content/samsung/assets/global/ir/docs/2024_con_quarter04_soi.pdf) · [2024 연결 현금흐름](https://images.samsung.com/is/content/samsung/assets/global/ir/docs/2024_con_quarter04_cf.pdf)
- [OpenDART 전체 재무제표 안내](https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS003&apiId=2019020): 향후 연결용. 연간 `11011`, 연결 `CFS`, 당기 금액 사용. 현재 키 없음.

원문은 **백만원**, 아래 원문 수치에 1,000,000을 곱해 원으로 보관하고 UI는 조원으로 표시한다. 현금흐름은 세전 현금창출액이 아니라 **Net cash provided by operating activities**다.

| 연도 | 매출액(백만원) | 영업이익(백만원) | 영업현금흐름(백만원) |
| --- | ---: | ---: | ---: |
| 2023 | 258,935,494 | 6,566,976 | 44,137,427 |
| 2024 | 300,870,903 | 32,725,961 | 72,982,621 |
| 2025 | 333,605,938 | 43,601,051 | 85,315,148 |

없는 항목은 null/‘자료 없음’으로 유지한다. 보고된 0, 적자, 공시 부재를 구분하고 분기 금액과 연간 금액을 섞지 않는다. 원문 링크에는 실제 보고서 연도를 표시한다.

## 저장과 실패

`user://research_cache/kis_<종목코드>.json`에는 공개 일봉·조회 시각만 저장한다. 작은 임시 파일을 완성한 뒤 교체하고 종목·통화·시장·수정주가·날짜 순서·OHLC·거래량을 다시 검증해 복원한다. 재무 IR 확인본은 코드에 출처와 함께 있으며 선택적 DART 결과는 현재 실행 메모리에만 보관한다.

시세 오류는 이전 정상 자료를 ‘이전 일봉’ 상태로 유지하며, 첫 조회 실패에는 가격을 만들지 않는다. 재무가 없어도 노트와 가격 차트를 사용할 수 있다. 종목 변경 후 늦은 응답은 폐기한다. 캐시 쓰기 실패는 화면에 표시한다. `PHALANX_RESEARCH_OFFLINE=1`은 네트워크 없이 저장 자료만 확인한다. 테스트는 별도 `PHALANX_RESEARCH_CACHE`와 `PHALANX_WORKSPACE_PATH`를 사용했다.

## 검증 결과

| 검증 | 결과 |
| --- | --- |
| 새 데이터 계약 | `research_data_test.gd` 55 검사 PASS: 잘못된 종목/시장/단위/미래 시각/날짜/OHLC/거래량, 결측·적자·0, 연간 공시 식별, 공식 수치 환산, 캐시·오류·늦은 응답·ETF |
| Python 연결 경계 | `test_kis_research_bridge.py` 4 테스트 PASS: 조회 범위, 일봉만 직렬화, 허용 종목, 빈 응답·다른 종목 거부. 실제 인증을 쓰지 않는 테스트 |
| 실제 KIS | 통합 GPU 화면에서 5개 종목 각각 241개 일봉 조회 성공. 거래일 2025-09-29~2026-09-28. 수신 2026-09-29 00:10 KST 전후. `provider-verification.json`에 종목별 시각/행 수 기록 |
| 독립 실행·오프라인 | 앱 종료 후 다른 프로세스에서 같은 5개 종목 캐시 복원 성공. 원래 수신 시각 유지. 테스트 노트도 파일에서 복원 |
| 기존 회귀 | 워크스페이스 43, 저장 45, 대시보드 smoke PASS. 야영지↔대시보드 Headless 157 / GPU 162 PASS |
| 실제 Windows 창 | 1280×720에서 Computer Use로 삼성전자↔SK하이닉스, 1년/라인, 새로고침 완료·수신 시각, 한국어 노트 입력, 재무 없음 스크롤, Esc 사령부 복귀·지도 재진입·노트 보존 확인 |
| 화면 크기 | 1440×960 / 1280×720 / 900×680 GPU 캡처 확인. 긴 재무/노트는 세로 스크롤. 900 폭은 한 열 |
| 보존 | `demo_data.gd`, `workspace_store.gd`는 시작 사본과 SHA-256 동일. 게임 미술 파일 변경 없음. 테스트 메모는 사용자 프로필과 분리 |

격리 테스트 실행에서 Windows 루트 인증서 저장소 읽기 경고가 있었으나 데이터/흐름 검사 PASS였다. 실제 권한으로 실행한 KIS 연동과 실제 창 로그에는 이 오류나 스크립트 파싱 오류가 없었다. TLS 검증을 끄지 않았다.

자동 입력/자동 화면 준비, Computer Use 운영체제 입력, 사람의 직접 조작은 구분한다. 사람의 직접 검수, Alt+Tab 반복, 장기간 네트워크 장애·토큰 만료 시점, 실제 OpenDART 응답은 이번에 검증하지 않았다. 캐시 장애와 늦은 응답은 격리된 자동 검사로 확인했다.

[최종 화면 갤러리](review/research_data_20260929/review.html). 최초 live 캡처와 최종 offline 복원 캡처를 구분했다. 최종 캡처에 나타난 ‘오프라인’은 실제 수신 일봉의 캐시 복원 검증 상태다.

## 변경 파일

- `scripts/research_model.gd`: 수치 검증·정규화·공식 IR 출처 확인본.
- `scripts/research_gateway.gd`, `kis_research_process.gd`, `tools/kis_research_bridge.py`: 비동기 KIS 읽기, 안전한 결과 수신, 캐시·상태와 선택적 DART 경로.
- `scripts/research_detail.gd`, `financial_trend.gd`: 분석 화면, 연간 비교, 출처·기준일·자료 없음, 기존 노트 연결.
- `scripts/headquarters.gd`, `price_chart.gd`: 탭 연결과 가상 요약 분리, 실제 일봉/거래량/온전한 20일 평균.
- 새 `tests/research_data_test.gd`, `research_data_review.gd`, `test_kis_research_bridge.py`.
- 기존 테스트 6개는 오프라인/임시 캐시를 기본으로 지정해 회귀 검사 중 실제 API가 호출되지 않게 했다. `terminal_review.gd`에 리서치 준비 옵션 추가.
- `README.md`, `SESSION_HANDOFF.md`, 이 문서와 화면 기록.

브랜치 `feature/camp-art-pass-b`, HEAD `344b8aa` 유지. commit·stage·merge·push·reset 수행 안 함.
