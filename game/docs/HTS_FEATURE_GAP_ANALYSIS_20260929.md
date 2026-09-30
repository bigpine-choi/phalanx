팔랑크스 — 상용 HTS 기능 격차와 다음 개발 제안
분석 기준: 2026-09-29

**판단**

다음 개발은 **전 종목 검색 + 관심종목 표 + 장중 현재가 갱신**을 묶은 시장 관제 화면을 권한다. 현재 팔랑크스는 실계좌 잔고, 일봉 리서치, 배분 시뮬레이션, AI 참모, 작전 기록을 갖췄지만, 장중 시세·호가·뉴스·거래 내역을 지속적으로 관찰하는 HTS 기능은 비어 있다.

아래 26개는 국내 주식 HTS의 일반적인 기능군과 비교한 격차다. 증권사별 세부 제공 범위는 다르며, 모든 HTS가 동일한 화면·지표·데이터를 제공한다는 뜻은 아니다. 고급 자산배분 알고리즘과 대화형 AI는 공통 HTS 필수 기능에 포함하지 않았다.

**분석 범위와 검증 방법**

- GitHub 원격 브랜치와 커밋을 조회하고 내려받아 소스·개발 문서와 대조했다.
- 게임: feature/camp-art-pass-b, **35c4921**. 분석 당시 로컬 HEAD와 GitHub 원격 커밋이 일치했다.
- Python: main, **de77b6b**. 로컬 design/command-bridge-spec의 **82ff591**은 main과 src/tests 내용이 같고 추가 차이는 설계 문서다.
- 계좌 성과·배분·formation 관련 원격 브랜치의 파일 차이도 확인했다. 기능 존재 여부는 브랜치 이름이나 커밋 포함 관계가 아니라 현재 소스로 판단했다.
- docs/product-vision-20260929의 **193cd24**는 제품 방향 문서로 참고했다. 문서의 계획을 구현된 기능으로 세지 않았다.
- Godot 화면·저장·차트·계좌·리서치·AI·시뮬레이터 코드와 Python의 KIS 클라이언트, 종목 마스터, 후보 선정, 성과/NAV, 배분 코드를 검토했다.
- 이번 평가는 정적 코드 분석이다. 앱을 새로 실행하거나 실계좌/API를 재호출해 기능을 검증한 결과는 아니다.
- 실제 잔고 금액이나 인증정보는 분석에 필요하지 않아 읽지 않았다. 개발 코드는 변경하지 않았다.

**이미 있는 기능 — 누락으로 세면 안 되는 것**

| 기능 | 구현 범위 |
|---|---|
| 실제 계좌 조회 | 순자산·예수금·주식평가액·평가손익, 보유종목·수량·비중. 조회 시점의 관측값이다. |
| 보유종목과 리서치 연결 | 보유종목을 시장/리서치 목록에 합치고 해당 종목의 차트·참모·배분 화면으로 연결한다. 초기 5종목만 지원하는 상태는 아니다. |
| 가격 차트 | 전일까지의 KRX 수정주가 일봉, 봉/선 차트, 거래량, 20일 이동평균, 마우스 위치의 OHLC. 22/66/252개 일봉 범위. |
| 재무 리서치 | 일부 기업의 연간 연결 재무, DART 조회 경로, 출처가 붙은 삼성전자 고정 자료. |
| 관심종목·메모·작전 기록 | 기기 내 저장과 복구 처리가 있다. 기록은 사용자가 작성/봉인한 계획이며 증권사 체결 내역과는 성격이 다르다. |
| 포트폴리오 시뮬레이터 | 현재 보유종목 간 목표 비중, 정수 주식 수량과 매수/매도 계획, 사용자 가정 현금, 참모 검토. 실제 주문은 전송하지 않는다. |
| AI 참모 | OpenAI 기반 브리핑·반론·작전 검토, 근거 연결, 앱 내 API 키 설정. 대화형 검색 도구나 자동 뉴스 감시는 아직 아니다. |
| Python 분석 자산 | 전체 종목 마스터 수집, 일봉 저장, 후보 순위, 과거 성과·상관관계, 계좌 기간 성과, 일별 NAV, 배분/백테스트와 별도 Windows 화면이 존재한다. |

근거: [게임 사령부][G1], [차트][G2], [리서치 모델][G3], [계좌 연결][G4], [시뮬레이터][G5], [Python README][P0].

**상태 표시**

- **미구현**: 검토한 현재 소스에 해당 사용 흐름과 데이터 연결을 확인하지 못했다.
- **부분 구현**: 관련 화면이나 값이 있지만 상용 HTS에서 기대하는 범위가 빠져 있다.
- **Python 기반 있음**: 재사용할 계산/수집 코드가 있다. 게임 연결만으로 끝나는지, 새 데이터가 필요한지는 설명에 구분했다.
- 우선순위 **1**은 다음 개발 묶음, **2**는 뒤이은 확장, **3**은 선행 데이터와 제품 범위를 정한 뒤 개발할 항목이다.

**시장 탐색·시세**

| 번호 | 상용 HTS의 기능 | 팔랑크스의 현재 상태와 빠진 부분 | 우선순위 / 근거 |
|---|---|---|---|
| 1 | 전 종목 검색·자동완성 | **Python 기반 있음.** 게임 검색은 초기 목록·저장한 관심종목·실제 보유종목 안에서 필터링한다. 미보유 종목을 시장 전체에서 이름/코드로 찾아 추가하는 화면이 없다. KOSPI/KOSDAQ 마스터 수집을 재사용할 수 있다. | 1 · [G1][G1], [P1][P1] |
| 2 | 관심종목 그룹·정렬 가능한 시세표 | **부분 구현.** 즐겨찾기와 저장은 있다. 여러 그룹, 열 선택, 등락률/거래대금 정렬, 여러 종목 시세의 동시 비교가 없다. | 1 · [G1][G1], [G6][G6] |
| 3 | 장중 현재가·등락률·거래량 갱신 | **Python 기반 있음.** KIS REST 현재가 조회는 있지만 게임의 지속 갱신 경로가 없다. 현재 모델은 가격과 관측 시간 중심이라 등락률·거래량 등 필드 확장이 필요하다. 실시간 구독도 별도 구현 대상이다. | 1 · [G7][G7], [P2][P2], [P3][P3] |
| 4 | 호가창·시간별 체결 내역 | **미구현.** 매수/매도 호가 잔량, 호가 차이, 체결 시각·가격·수량을 수신하고 그리는 기능이 없다. | 2 · [G1][G1], [P3][P3] |
| 5 | 장 상태·시장 구분 | **부분 구현.** 일봉 출처와 조회 시점은 표시한다. 휴장/장중/시간외 상태, 시장별 세션과 시세 선택 UI가 없다. Python에 NXT/통합 enum은 있으나 현재 운영 조회 경로는 KRX로 고정돼 있다. | 1은 출처·갱신상태, 2는 세션 확장 · [P2][P2], [P4][P4] |
| 6 | 주요 지수·업종·환율 시장판 | **미구현.** 현재 시장 화면 상단은 계좌 요약이다. KOSPI/KOSDAQ·업종 등락·시장 전체 흐름을 보여주는 데이터판이 없다. | 2 · [G1][G1] |
| 7 | 등락률·거래량·거래대금 순위 | **Python 기반 일부 있음.** 기존 후보 선정은 과거 일봉의 수익률·변동성·낙폭 순위다. 당일 시장 전체 급등/급락·거래대금 순위와는 다르며 별도 데이터 연결이 필요하다. | 2 · [P5][P5], [P6][P6] |
| 8 | 외국인·기관·개인 수급 | **미구현.** 종목별/시장별 순매수, 투자자별 추이, 프로그램 매매 등을 수집·표시하는 경로가 없다. | 2 · [G7][G7], [P3][P3] |

비교 기준: [미래에셋 현재가 화면](https://securities.miraeasset.com/oms/omsclient.do?n=0101), [키움 주식호가](https://download.kiwoom.com/hero4_help_new/0111.htm), [카이로스 전체 구성](https://securities.miraeasset.com/kairos/a001.htm), [삼성 POP HTS 가이드](https://www.samsungpop.com/download/customer/hts/samsungpopHTS_guide_2.pdf).

**차트·기업 정보·종목 발굴**

| 번호 | 상용 HTS의 기능 | 팔랑크스의 현재 상태와 빠진 부분 | 우선순위 / 근거 |
|---|---|---|---|
| 9 | 분봉·틱·주봉·월봉과 과거 구간 탐색 | **부분 구현.** 일봉의 표시 개수만 바꾼다. 당일 분봉·틱 수집, 주/月 집계, 확대·이동·과거 추가 로딩이 없다. 주봉/월봉은 일봉 재활용이 가능하지만 장기 자료 범위도 늘려야 한다. | 2 · [G2][G2], [G8][G8] |
| 10 | 기술지표·추세선·차트 설정 저장 | **부분 구현.** MA20과 거래량만 있다. 다중 이동평균, RSI/MACD/볼린저밴드, 추세선·수평선 작도, 개인 차트 설정 저장이 없다. | 2 · [G2][G2], [G6][G6] |
| 11 | 종목·지수 수익률 비교 차트 | **Python 기반 있음.** 과거 종목별 성과·상관관계 계산은 있다. 게임에서 기준일을 맞춰 여러 종목/지수를 겹쳐 비교하는 기능이 없다. 지수 데이터는 별도 연결이 필요하다. | 2 · [P7][P7], [G2][G2] |
| 12 | 종목별 뉴스·공시 피드 | **미구현.** DART 연간 재무 조회와 외부 링크는 있어도 최신 공시/뉴스 목록, 검색, 새 소식 표시, 종목별 연결은 없다. | 2 · [G3][G3], [G7][G7] |
| 13 | 폭넓은 기업 재무·투자지표 | **부분 구현.** 기업 매핑은 4개, 재무는 연간 연결 중심이다. 전 종목 기업 매핑, 분기/반기, PER/PBR 등 투자지표와 컨센서스가 빠져 있다. 실제 화면에도 미포함으로 명시돼 있다. | 2 · [G3][G3], [G9][G9] |
| 14 | 배당·실적·권리·증시 일정 | **미구현.** 배당락/지급, 실적 발표, 유무상증자 등 종목 사건과 일정을 조회·연결하는 화면이 없다. | 2 · [G7][G7] |
| 15 | 저장 가능한 조건검색 | **Python 기반 일부 있음.** 8가지 과거 가격 지표 중 하나로 후보를 순위화할 수 있다. 가격·거래량·재무조건의 AND/OR 조합, 조건 저장, 실시간 편입/이탈 감시가 없다. | 2 · [P5][P5], [P6][P6] |
| 16 | 가격·변동·공시 알림 | **미구현.** 목표 가격/등락률/새 공시 조건을 저장하고 감시하는 엔진, 알림 목록·확인·중복 억제가 없다. AI를 수동 요청하는 기능과 별도다. | 2 · [G1][G1], [G6][G6], [G7][G7] |

비교 기준: [키움 종합차트](https://download.kiwoom.com/hero4_help_new/0600.htm), [재무차트](https://download.kiwoom.com/hero4_help_new/0604.htm), [조건검색](https://download.kiwoom.com/hero4_help_new/0150.htm), [테마수익률 비교](https://download.kiwoom.com/hero4_help_new/0652.htm), [카이로스 신호 모니터링](https://securities.miraeasset.com/kairos/a001.htm). 컨센서스는 DART 원문만으로 채울 수 없으므로 별도 데이터 공급 범위를 정해야 한다.

**계좌·주문·기록·작업 환경**

| 번호 | 상용 HTS의 기능 | 팔랑크스의 현재 상태와 빠진 부분 | 우선순위 / 근거 |
|---|---|---|---|
| 17 | 평균 매입가·평가손익률 | **Python 기반 있음.** 게임은 수량·평가액·평가손익·비중을 보여준다. Python 계좌 모델에는 매입금액이 있지만 연결부에서 게임에 전달하지 않는다. 이를 연결하고 기준을 명시하면 평균 매입가·손익률 표시를 확장할 수 있다. | 1 · [G4][G4], [P8][P8] |
| 18 | 주문가능금액·출금가능금액·결제 예정금 | **부분 구현.** 예수금 총액만 있다. orderable_cash는 명시적으로 None이며 시뮬레이터 현금도 사용자 가정이다. 주문가능 조회와 D+1/D+2 등 증권사 제공 결제·출금 정보를 연결해야 한다. | 2 · [G4][G4], [P8][P8], [P0][P0] |
| 19 | 실제 매수·매도 주문 | **미구현, 의도된 읽기 전용 범위.** 주문 유형·가격·수량을 전송하고 접수 결과를 관리하는 경로가 없다. 작전 확정/봉인/시뮬레이터 적용은 주문 전송이 아니다. | 3 · [P0][P0], [G5][G5] |
| 20 | 미체결 조회·정정·취소·주문 상태 | **미구현.** 접수/부분 체결/잔량/취소/거절을 추적할 주문 상태 관리가 없다. 실제 주문 도입 시 19번과 함께 설계할 기능이다. | 3 · [P0][P0], [G5][G5] |
| 21 | 실제 매매 내역·실현손익·비용 | **미구현.** 증권사 체결 내역과 실현손익을 조회하지 않는다. 현재 작전 기록은 거래 원장이 아니다. 시뮬레이터는 수수료·세금·체결 오차를 제외한다. | 2 · [G5][G5], [G6][G6] |
| 22 | 일별/기간별 계좌 성적표 | **Python 기반 있음.** 두 계좌 스냅샷과 외부 현금 흐름으로 기간 성과를 계산하고, 정규화한 원장으로 일별 NAV를 계산할 수 있다. 자동 원장 수집과 게임의 수익률/손익 추이 화면이 빠져 있다. | 2 · [P9][P9], [P10][P10] |
| 23 | 입출금·배당·수수료 등의 거래 원장 | **Python 기반 일부 있음.** NAV 엔진은 입출금·매매·배당·이자·수수료·세금 이벤트를 처리한다. 증권사 자료를 자동 수집하거나 HTS 파일을 변환하는 사용 흐름은 없다. 액면분할 등 권리 변동도 추가 모델링 대상이다. | 2 · [P10][P10], [P11][P11] |
| 24 | 여러 계좌 선택·계좌별 구분 | **미구현.** 게임은 현재 설정된 계좌의 단일 스냅샷을 공유한다. 계좌 선택, 계좌별 관심/계획 구분, 여러 계좌 합산 화면이 없다. 여러 증권사 통합은 이보다 별도 확장 범위다. | 3 · [G4][G4], [G1][G1] |
| 25 | 사용자 화면 배치·복수 차트·독립 창 | **부분 구현.** 고정 탭, 반응형 배치와 일부 단축키는 있다. 자유 패널 배치, 여러 종목 창, 연결 그룹, 저장된 작업공간·다중 모니터 구성이 없다. | 3 · [G1][G1], [G6][G6] |
| 26 | 표 데이터 내보내기 | **부분 구현.** Python에 JSON/HTML 결과 저장과 DB 백업은 있다. 게임의 잔고·관심종목·거래 내역을 CSV/Excel 등으로 내보내는 기능은 없다. | 3 · [G6][G6], [P0][P0] |

비교 기준: [카이로스 복수종목 주문·잔고·미체결](https://securities.miraeasset.com/kairos/0606.htm), [키움 예수금 상세](https://download.kiwoom.com/hero4_help_new/0362.htm), [일별 실현손익](https://download.kiwoom.com/hero4_help_new/0329.htm), [연도별 계좌수익률](https://download.kiwoom.com/hero4_help_new/1893.htm), [삼성 POP HTS 계좌·업무 안내](https://www.samsungpop.com/download/customer/hts/samsungpopHTS_guide_2.pdf), [키움 재무 데이터 Excel 저장](https://download.kiwoom.com/hero4_help_new/0604.htm).

**다음 개발 묶음: 시장 관제 화면**

목표 사용 흐름은 “아직 보유하지 않은 종목 검색 → 관심 그룹에 추가 → 현재 가격 확인 → 일봉/재무/참모로 이동”이다. 이 흐름이 갖춰지면 게임을 켜서 시장을 살펴보는 이유가 생긴다.

1. **시장 전체 종목 검색.** Python discovery의 마스터를 게임에서 검색할 수 있게 연결한다. 종목 이름·코드·시장·종류를 통일한다. 투자 후보 정책에서 제외된 ETF/우선주라도 검색 카탈로그에서 사라지게 해서는 안 된다.
2. **관심 그룹과 표.** “보유”, “관심”, 사용자 그룹으로 나누고 이름·현재가·등락률·거래량·조회 시각을 표시한다. 정렬과 그룹 저장을 지원한다.
3. **현재가 조회와 주기 갱신.** 기존 KIS REST 조회를 재사용하되 필요한 표시 항목을 확장한다. 첫 버전의 주기 조회와 이후의 실시간 구독을 구분하고, 실제 제공 방식대로 표시한다. 종목 수·공급자 호출 제한을 확인한 뒤 갱신 정책을 정한다.
4. **시세 상태 표시.** 가격 출처, 데이터 시점, 갱신 중/실패/오래된 값 상태를 보여준다. 장중 현재가와 전일 확정 일봉을 같은 값처럼 취급하지 않는다.
5. **계좌 표 보강.** 누락된 매입금액을 전달해 평단·평가손익률을 표시한다. 기존 계좌의 평가손익과 새로운 계산값이 어떤 비용 기준인지 확인한다.

완료 기준은 미보유 종목 검색/추가, 재시작 뒤 그룹 유지, 여러 종목 시세 정렬·갱신, 조회 실패 시 이전 값과 시각 보존, 선택 종목이 기존 차트/참모로 일관되게 연결되는 것이다. 미보유 종목을 배분 시뮬레이터에 편입하는 것은 별도 확장이다. 현재 엔진은 보유종목과 목표 종목 집합이 정확히 같아야 한다.

**후속 순서와 Python 연결**

| 순서 | 사용자에게 생기는 기능 | 기존 코드 활용 / 필요한 신규 연결 |
|---|---|---|
| 1 | 시장 관제 화면 | discovery + KIS REST 현재가 + 계좌 매입금액. Godot에는 검색/관심 표/갱신 상태 추가. |
| 2 | 정보실과 알림 | 종목별 공시·뉴스·이벤트를 수집하고 ID/시각/출처를 저장. 조건 감시를 만든 뒤 AI가 “무슨 사건이고 보유종목과 어떤 관련이 있는지” 설명하게 한다. |
| 3 | 계좌 성적표 | 실제 거래·입출금 자료 수집 및 대사 → 기존 account_performance/nav → 게임 성과 화면. 입금으로 늘어난 잔고를 투자 수익으로 오인하지 않게 한다. |
| 4 | 전술 분석 확장 | 분봉·기술지표·비교 차트, 조건검색, 수급. 데이터 수집 범위에 맞춰 단계적으로 연결. |
| 5 | 주문 기능 | 주문가능 조회, 주문/체결 상태와 원장 기반을 갖춘 뒤 실제 주문·정정·취소 연결. |

역할은 **Python이 데이터 수집·정규화·계산·저장**, **Godot이 화면·조작·연출**, **AI가 확인된 근거의 설명**을 담당하도록 유지하는 편이 현재 구조와 맞는다. 기능마다 화면에서 개별 계산을 복제하지 말고 기존 연결부를 확장한다.

초기 REST 주기 갱신에는 기존 프로세스 호출 구조를 재사용할 수 있다. 다만 다종목 고빈도 조회나 실시간 구독까지 확장할 때는 매번 프로세스를 새로 띄우는 방식의 한계를 점검하고 지속 실행 서비스/구독 관리로 발전시키는 편이 적절하다. 이는 이번 코드 검토에 따른 설계 제안이며 구현 완료 상태는 아니다.

계좌 성적표의 수익률 산식, 비교 지수, 배당 반영 범위는 화면에 명확히 표시해야 한다. Python의 기간 성과는 Modified Dietz 추정 방식이고, NAV 엔진은 원장·가격·벤치마크 등 입력의 완전성을 전제로 한다. HTS 화면에 나온 수익률과 무조건 동일하다고 가정할 수 없다.

**HTS 기본 격차와 구분할 팔랑크스의 차별화 과제**

- 배분안 비교: 기존 equal-weight/inverse-volatility/Constrained ERC·백테스트를 게임에 연결할 수 있다. 새 알고리즘부터 만들 필요는 없다.
- 시뮬레이터 확장: 미보유 종목 편입, 비용·체결 오차 가정, 상관관계·위험 기여도 비교가 빠져 있다. 이는 일반 HTS 공통 기본 기능이라기보다 팔랑크스의 핵심 차별화에 가깝다.
- 대화형 AI 참모: 현재 버튼형 보고서에서 검색·질문·근거 재조회·대화 기록으로 확장할 여지가 있다. 먼저 실제 뉴스·공시·시세가 연결돼야 활용 범위가 넓어진다.
- 사건의 게임 연출: 가격/공시/계좌 사건을 알림 엔진이 판정하고, 사령부의 보고서 도착·참모 호출로 표현할 수 있다. 시장 변동 자체를 게임 재화로 과장하는 대신 확인된 사건을 중심으로 연출한다.

해외주식·환전, ETF 구성/NAV 상세, 선물옵션, 신용·대출, 청약·이체 등도 현재 범위에서 빠져 있다. 다만 국내 주식 관찰·분석이라는 초기 범위를 크게 넓히므로 위 26개와 별도로 제품 범위를 정한 뒤 추진하는 것이 적절하다.

**코드 근거 — 조사 시점으로 고정한 GitHub 링크**

[G1]: https://github.com/bigpine-choi/phalanx/blob/35c49215820e88c0d395c11c5361b5be0fc1c05a/scripts/headquarters.gd
[G2]: https://github.com/bigpine-choi/phalanx/blob/35c49215820e88c0d395c11c5361b5be0fc1c05a/scripts/price_chart.gd
[G3]: https://github.com/bigpine-choi/phalanx/blob/35c49215820e88c0d395c11c5361b5be0fc1c05a/scripts/research_model.gd
[G4]: https://github.com/bigpine-choi/phalanx/blob/35c49215820e88c0d395c11c5361b5be0fc1c05a/tools/account_bridge.py
[G5]: https://github.com/bigpine-choi/phalanx/blob/35c49215820e88c0d395c11c5361b5be0fc1c05a/tools/portfolio_engine.py
[G6]: https://github.com/bigpine-choi/phalanx/blob/35c49215820e88c0d395c11c5361b5be0fc1c05a/scripts/workspace_store.gd
[G7]: https://github.com/bigpine-choi/phalanx/blob/35c49215820e88c0d395c11c5361b5be0fc1c05a/scripts/research_gateway.gd
[G8]: https://github.com/bigpine-choi/phalanx/blob/35c49215820e88c0d395c11c5361b5be0fc1c05a/tools/kis_research_bridge.py
[G9]: https://github.com/bigpine-choi/phalanx/blob/35c49215820e88c0d395c11c5361b5be0fc1c05a/scripts/research_detail.gd
[P0]: https://github.com/bigpine-choi/phalanx/blob/de77b6b41fde2a82753d70cf78eaef11a28449df/README.md
[P1]: https://github.com/bigpine-choi/phalanx/blob/de77b6b41fde2a82753d70cf78eaef11a28449df/src/phalanx/discovery/service.py
[P2]: https://github.com/bigpine-choi/phalanx/blob/de77b6b41fde2a82753d70cf78eaef11a28449df/src/phalanx/market_data/application.py
[P3]: https://github.com/bigpine-choi/phalanx/blob/de77b6b41fde2a82753d70cf78eaef11a28449df/src/phalanx/kis/market_data_client.py
[P4]: https://github.com/bigpine-choi/phalanx/blob/de77b6b41fde2a82753d70cf78eaef11a28449df/src/phalanx/domain/market_data.py
[P5]: https://github.com/bigpine-choi/phalanx/blob/de77b6b41fde2a82753d70cf78eaef11a28449df/src/phalanx/selection/engine.py
[P6]: https://github.com/bigpine-choi/phalanx/blob/de77b6b41fde2a82753d70cf78eaef11a28449df/src/phalanx/domain/candidate_selection.py
[P7]: https://github.com/bigpine-choi/phalanx/blob/de77b6b41fde2a82753d70cf78eaef11a28449df/src/phalanx/portfolio/performance.py
[P8]: https://github.com/bigpine-choi/phalanx/blob/de77b6b41fde2a82753d70cf78eaef11a28449df/src/phalanx/domain/account.py
[P9]: https://github.com/bigpine-choi/phalanx/blob/de77b6b41fde2a82753d70cf78eaef11a28449df/src/phalanx/account_performance.py
[P10]: https://github.com/bigpine-choi/phalanx/blob/de77b6b41fde2a82753d70cf78eaef11a28449df/src/phalanx/nav/engine.py
[P11]: https://github.com/bigpine-choi/phalanx/blob/de77b6b41fde2a82753d70cf78eaef11a28449df/src/phalanx/nav/models.py

- 게임에서 [일봉·계좌 시점과 자동 갱신 부재를 표시하는 부분](https://github.com/bigpine-choi/phalanx/blob/35c49215820e88c0d395c11c5361b5be0fc1c05a/scripts/headquarters.gd#L212).
- 게임의 [검색 대상 필터](https://github.com/bigpine-choi/phalanx/blob/35c49215820e88c0d395c11c5361b5be0fc1c05a/scripts/headquarters.gd#L541).
- 일봉의 [종료일·기간 설정](https://github.com/bigpine-choi/phalanx/blob/35c49215820e88c0d395c11c5361b5be0fc1c05a/tools/kis_research_bridge.py#L22).
- 차트의 [입력 및 표시 범위](https://github.com/bigpine-choi/phalanx/blob/35c49215820e88c0d395c11c5361b5be0fc1c05a/scripts/price_chart.gd#L24).
- 재무의 [4개 기업 매핑](https://github.com/bigpine-choi/phalanx/blob/35c49215820e88c0d395c11c5361b5be0fc1c05a/scripts/research_model.gd#L5)과 [미포함 지표 안내](https://github.com/bigpine-choi/phalanx/blob/35c49215820e88c0d395c11c5361b5be0fc1c05a/scripts/research_detail.gd#L183).
- 계좌 연결부의 [주문가능금액과 전달 필드](https://github.com/bigpine-choi/phalanx/blob/35c49215820e88c0d395c11c5361b5be0fc1c05a/tools/account_bridge.py#L22).
- Python에 이미 있는 [종목별 매입금액](https://github.com/bigpine-choi/phalanx/blob/de77b6b41fde2a82753d70cf78eaef11a28449df/src/phalanx/domain/account.py#L57).
- 시뮬레이터의 [대상 종목 집합 제한](https://github.com/bigpine-choi/phalanx/blob/35c49215820e88c0d395c11c5361b5be0fc1c05a/tools/portfolio_engine.py#L45)과 [비용 제외 안내](https://github.com/bigpine-choi/phalanx/blob/35c49215820e88c0d395c11c5361b5be0fc1c05a/tools/portfolio_engine.py#L118).
- 기존 [KRX REST 현재가 조회](https://github.com/bigpine-choi/phalanx/blob/de77b6b41fde2a82753d70cf78eaef11a28449df/src/phalanx/market_data/application.py#L93).
- 기존 [후보 선정 엔진](https://github.com/bigpine-choi/phalanx/blob/de77b6b41fde2a82753d70cf78eaef11a28449df/src/phalanx/selection/engine.py#L103).
- 기존 [과거 성과·상관관계 분석](https://github.com/bigpine-choi/phalanx/blob/de77b6b41fde2a82753d70cf78eaef11a28449df/src/phalanx/portfolio/performance.py#L26).
- 기존 [기간 계좌 성과](https://github.com/bigpine-choi/phalanx/blob/de77b6b41fde2a82753d70cf78eaef11a28449df/src/phalanx/account_performance.py#L77)와 [일별 NAV](https://github.com/bigpine-choi/phalanx/blob/de77b6b41fde2a82753d70cf78eaef11a28449df/src/phalanx/nav/engine.py#L191).
