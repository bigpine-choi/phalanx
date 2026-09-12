# 시장 후보 자동 발굴 1단계

`market-candidate-discovery`는 한국투자증권의 공개 KOSPI·KOSDAQ 마스터를 수집하고,
각 원본 레코드를 정규화한 뒤 `eligible`, `excluded`, `unknown`으로 판정한다.
수동 `universe.json`, 계좌 자료, 일별 NAV 이력은 읽거나 변경하지 않는다.
AI 순위모형, 비중 산출, 주문, GUI는 이 단계에 포함하지 않는다.

## 사용법

```bash
uv run phalanx discovery refresh
uv run phalanx discovery list --status eligible
uv run phalanx discovery list --status excluded
uv run phalanx discovery list --status unknown
uv run phalanx discovery show 005930
```

`refresh`만 네트워크에 접속한다. 계좌 설정·API 키·OAuth 토큰이 필요하지 않다.
`list`와 `show`는 저장된 결과만 읽는다. `--status` 생략 시 모든 상태를 조회한다.
`show`의 인자는 **단축코드**이며 선행 0을 포함한 문자열로 비교한다.
중복 식별자가 있는 부분 결과에서는 모든 해당 행을 표시한다.

기본 저장소는 Linux/WSL 사용자 데이터 경로
`~/.local/share/phalanx/discovery/discovery.sqlite3`이다.
모든 명령에서 `--db <경로>`로 별도 저장소를 사용할 수 있다.
테스트·실험용 저장소 예:

```bash
uv run phalanx discovery refresh --db /tmp/phalanx-discovery/discovery.sqlite3
uv run phalanx discovery show 005930 --db /tmp/phalanx-discovery/discovery.sqlite3
```

새 디렉터리와 DB 권한은 각각 `0700`, `0600`이다. 기존 경로의 권한을 자동 변경하지
않으며 심볼릭 링크·공유 파일·다른 앱의 DB를 거부한다. 기존 상위 사용자 디렉터리는
그대로 둔다. 프로젝트 루트의 파일이나 환경설정에서 계좌 정보를 찾지 않는다.

| 종료코드 | 의미 |
| --- | --- |
| 0 | 두 시장 다운로드·전 행 파싱 성공, 또는 정상 스냅샷의 오프라인 조회 |
| 1 | 부분 수집·수집 실패·미완료 시도, 이전 결과 조회, 저장 결과 없음, 종목 없음 |
| 2 | CLI 인자 오류 (`--status` 미지원 값 등) |
| 65 | 도메인·공급자 오류가 애플리케이션 경계까지 전파된 경우 |
| 66 | 저장소 읽기·쓰기 오류 |
| 130 | 사용자 중단 |

`eligible`가 0건이어도 두 시장의 파일 처리가 정상이라면 수집 성공이다.
수집 성공과 적격 건수, 시장 전체 완전성은 서로 다른 개념이다.

## 공식 자료와 고정 버전

2026-09-12에 다음 공식 저장소의 커밋
`b4e6249714418aa57833d1cbbbced39cbcc5b125`를 확인했다.

- [공식 stocks_info 디렉터리](https://github.com/koreainvestment/open-trading-api/tree/b4e6249714418aa57833d1cbbbced39cbcc5b125/stocks_info)
- [kis_kospi_code_mst.py](https://github.com/koreainvestment/open-trading-api/blob/b4e6249714418aa57833d1cbbbced39cbcc5b125/stocks_info/kis_kospi_code_mst.py)
- [kis_kosdaq_code_mst.py](https://github.com/koreainvestment/open-trading-api/blob/b4e6249714418aa57833d1cbbbced39cbcc5b125/stocks_info/kis_kosdaq_code_mst.py)
- [종목마스터정보(코스피).h](https://github.com/koreainvestment/open-trading-api/blob/b4e6249714418aa57833d1cbbbced39cbcc5b125/stocks_info/종목마스터정보%28코스피%29.h)
- [종목마스터정보(코스닥).h](https://github.com/koreainvestment/open-trading-api/blob/b4e6249714418aa57833d1cbbbced39cbcc5b125/stocks_info/종목마스터정보%28코스닥%29.h)
- [KOSPI 공개 ZIP](https://new.real.download.dws.co.kr/common/master/kospi_code.mst.zip)
- [KOSDAQ 공개 ZIP](https://new.real.download.dws.co.kr/common/master/kosdaq_code.mst.zip)

스키마 버전은 `kis-master-b4e6249714418aa57833d1cbbbced39cbcc5b125`,
파서 버전은 `kis-master-parser-v1`, 현재 정책 버전은 `domestic-common-stock-v2`이다.
SQLite 스키마 버전은 `PRAGMA user_version=1`로 별도 관리한다.

공식 예제의 필드 폭과 C 헤더를 교차 확인했다. suffix는 KOSPI 227바이트,
KOSDAQ 221바이트다. 공식 예제는 단축코드 9·표준코드 12 이후부터 suffix 전까지를
한글명으로 읽는다. 헤더의 `SZ_KORNAME` 숫자는 해당 파일에 직접 정의되어 있지 않다.
실제 두 공개 마스터의 한글명 필드는 40바이트로 확인됐으며 v1은 이를 명시적으로
고정한다. 개행 제외 전체 길이는 각각 288·282바이트다. 길이가 바뀌면 추정하지 않고
구조 오류로 기록하므로 공급자 스키마 변경 시 검토·파서 버전 갱신이 필요하다.

파서는 디코딩한 문자열 길이가 아닌 **바이트 위치**로 필드를 자르고 한글명만 CP949,
나머지를 ASCII로 디코딩한다. LF·CRLF·마지막 개행 없음에 같은 결과를 내며, 끝의
필드 공백을 통째로 `strip`하지 않는다. 원천 필드에는 공백도 그대로 남긴다.
중간 빈 줄·잘린 행·잘못된 인코딩·제어문자는 행 번호와 오류 코드로 남는다.
필드 폭에 맞는 빈값·미지원 코드는 파싱 오류가 아닌 판정 미확인으로 처리한다.

## 초기 후보 정책 v2

최종 투자정책이 아닌 초기 후보 발굴 정책이다. 국내 일반 보통주만 초기 대상이다.

| 필수 확인 | 통과 값 | 명시적 제외 / 미확인 |
| --- | --- | --- |
| 증권그룹 `scrt_grp_cls_code` | `ST` 주권 | 공식 정의의 다른 그룹은 제외, 미지원·빈값은 미확인 |
| 우선주 `prst_cls_code` | `0` 보통주 | `1` 구형·`2` 신형 우선주 제외, 나머지는 미확인 |
| ETP `etp_prod_cls_code` | `0`, 또는 ST의 독립 근거가 있는 공백 | KOSPI `1`~`5`, KOSDAQ `1`~`4` 제외, 미지원 비공백은 미확인; ST 이외 공백도 미확인 사유 보존 |
| SPAC `etpr_undt_objt_co_yn` | `N` | `Y` 제외, 나머지는 미확인 |
| 거래정지 `trht_yn` | `N` | `Y` 제외, 나머지는 미확인 |
| 정리매매 `sltr_yn` | `N` | `Y` 제외, 나머지는 미확인 |
| 관리종목 `mang_issu_yn` | `N` | `Y` 제외, 나머지는 미확인 |
| 단축·표준코드·명칭 | 제공되고 형식 유효 | 누락·미지원 값·중복·충돌은 미확인 |

공식 정의된 비대상 그룹은 `MF`(증권투자회사), `RT`(부동산투자회사), `SC`(선박투자회사),
`IF`(사회간접자본투융자회사), `DR`(주식예탁증서), `EW`(ELW), `EF`(ETF),
`SW`(신주인수권증권), `SR`(신주인수권증서), `BC`(수익증권), `FE`(해외ETF),
`FS`(외국주권)이다. ETP `1`·`2`는 투자회사형·수익증권형, `3`·`4`는 ETN·손실제한ETN,
KOSPI `5`는 상장형수익증권이다. 헤더에서 정의하지 않은 코드를 경험칙으로 추가하지 않는다.

종목명에 `우`, `스팩`이 있다는 이유로 분류하지 않는다. 단축코드는 숫자로 변환하지
않으며, 시장 전체의 9자리 펀드 코드나 영문이 섞인 코드도 보존한다. `standard_code`는
표준 종목코드이며 기업 식별자가 아니다. `grp_code`도 기업집단 코드이므로
`issuer_id`는 제공되지 않은 값인 `null`로 둔다.

모든 조건을 확인한 경우 `eligible`, 명시적인 제외 사유가 하나라도 있으면 `excluded`,
제외 사유는 없지만 필수 정보가 불충분하면 `unknown`이다. 제외 사유가 우선하더라도
다른 누락·미지원·충돌 사유를 버리지 않는다. ST와 ETP 상품 분류의 충돌, ETF 그룹과
ETP 0의 충돌, 같은 식별자에 연결된 상이한 행을 명시적으로 기록한다.
동일 행 중복도 임의로 하나를 선택하지 않고 모든 행을 보존하며 정상본 승격을 막는다.

### ETP 적용 범위와 버전 변경 근거

v1은 모든 레코드에서 ETP `0`을 필수로 요구했다. 원본 대조 결과 ST의 공백이 실제 값임을
확인했고, v2에서는 **공식 증권그룹 분류가 주권임을 확정하면 비ETP 판정의 독립 근거로
충분하다**고 정의한다. 공식 헤더는 ST 주권, EF ETF, FE 해외ETF 등을 별도 그룹으로
정의하며, ETP 필드는 상품 형태를 추가로 구분한다. 따라서 ST + 공백에서 ETP 세부값을
반드시 요구하지 않는다. ST만으로 최종 적격이 되는 것은 아니며 우선주·SPAC·거래 상태와
식별자 등 나머지 필수 조건은 모두 확인한다.

이는 공식 범주 정의에 근거한 **Phalanx 정책의 판단**이다. 공식 헤더가 공백을 `0`이라고
정의하거나 필드의 mandatory 여부를 명시했다고 주장하지 않는다. 관측 빈도만으로
공백 의미를 추정한 것도 아니다. 원시 `" "`, 정규화 `null`과 파서 버전은 그대로 유지한다.
ST 이외의 그룹에 이 예외를 넓히지 않는다. ETP의 명시적 양성·미지원 비공백·충돌은
ST가 있어도 무시하지 않는다. 알려진 제외 사유가 있으면 제외하고 미확인 사유도 남긴다.

v2는 `NON_ETP_BY_ST_GROUP`을 `evidence` 종류로 기록한다. 이 근거는 제외·미확인 결과에도
함께 남을 수 있고, 이 근거만으로 적격 결과를 만들 수 없다. `V2_PASSED`는 전체 조건을
통과했을 때만 생성한다. 기존 `domestic-common-stock-v1` 결과와 `V1_PASSED`는 저장된
그대로 읽는다. 정책 교체를 이유로 기존 스냅샷을 자동 재평가·수정하지 않는다.

기계용 사유 코드:

- `V2_PASSED`: v2의 모든 필수 조건 확인 (`V1_PASSED`는 이전 저장 결과에 남음).
- `NON_ETP_BY_ST_GROUP`: 공백을 보존한 채 ST 그룹을 비ETP의 독립 근거로 사용.
- `NON_DOMESTIC_ORDINARY_EQUITY`, `PREFERRED_STOCK`, `ETP`, `SPAC`,
  `TRADING_HALTED`, `LIQUIDATION_TRADING`, `MANAGED_ISSUE`: 명시적 제외.
- `MISSING_REQUIRED_FIELD`, `UNSUPPORTED_CODE`, `CLASSIFICATION_CONFLICT`,
  `DUPLICATE_RECORD`, `RECORD_CONFLICT`: 미확인 사항.

각 사유에는 한국어 설명과 종류(`pass`/`exclude`/`unknown`/`evidence`), 관련 필드가 있다.
시장경고 `00`~`03`(해당 없음·투자주의·투자경고·투자위험), 경고예고, 투자주의환기,
단기과열, 공매도과열 등 나머지 정보는 `raw_fields`에 보존하며 제외 조건으로
추가하지 않는다. 시가총액·거래대금·상장기간 숫자 기준도 추가하지 않는다.

## 저장과 실패 처리

`runs`에는 실행 ID, timezone-aware 시작·완료 시각, 실행 상태와 시장별 스냅샷 JSON을
저장한다. 실행 ID가 스냅샷 ID 역할도 한다. 시장별로 공급자·URL·버전·다운로드 상태·
파싱 상태·원본 행 수·정규화 레코드·판정·행별 오류를 보존한다. 정규화되지 못한 행은
판정 상태 건수에 포함하지 않으며, 전체 행 수와 정규화 건수를 따로 출력한다.

`source_files`에는 `(run_id, market, filename)` 키로 **원본 ZIP과 MST의 정확한 바이트**를
SQLite BLOB으로 저장한다. 원래 파일명·바이트 수·SHA-256은 시장 메타데이터에도 있다.
파일시스템에 압축을 풀지 않는다. `SqliteDiscoveryRepository.read_source()`로 원본을
복원할 수 있고 읽을 때 해시를 확인한다. 손상 ZIP도 다운로드가 끝났다면 보존하며,
파싱 실패 MST도 원문을 보존한다. 전송 도중 끊긴 다운로드는 완성된 원본으로 저장하지 않는다.

쓰기 시작 전에 `in_progress` 실행 저널을 먼저 커밋한다. 두 시장을 독립적으로 처리한 후
모든 원본·정규화·판정·완료 상태를 **하나의 SQLite 트랜잭션**으로 커밋한다.
저장 실패 시 전체 결과가 롤백되고 가능한 경우 `storage_failed`를 별도 기록한다.
디스크 장애로 이 상태 기록마저 불가능하면 이전 `in_progress`가 남아 정상 성공으로
오인되지 않는다. 시작 저널조차 저장할 수 없으면 다운로드를 시작하지 않는다.

조회는 가장 최근에 시작한 정상 실행을 선택한다. 그 뒤의 실패·부분 수집·미완료 시도가
있으면 표시 스냅샷의 수집 시점, 최근 시도 ID·상태 및 시장별 오류를 함께 표시하고
종료코드 1을 반환한다. 정상본이 한 번도 없으면 저장된 최근 부분·실패 결과를 명시적으로
표시한다. 신규 성공에서 빠진 종목은 이전 실행 기록에 남으며 상장폐지로 확정하지 않는다.
동시 수집은 각기 별도 ID로 보존하고 SQLite 쓰기 잠금으로 결과를 직렬화한다.

스냅샷 조회는 SQLite 읽기 트랜잭션과 `mode=ro`를 사용한다. 원본 파일 내용과 정책·파서가
같으면 정규화와 판정은 동일하며 실행 ID·수집 시각만 달라진다. 보존·삭제 정책은 아직
없으므로 반복 수집할수록 DB 크기는 증가한다. 파일 검사는 같은 OS 사용자 권한의 악성
프로세스까지 격리하지 않는다.

## 다운로드 제한과 자료 시점

httpx HTTPS에서 TLS 인증서 검증을 유지한다. 연결 제한은 5초, 개별 읽기·쓰기·풀 대기는
15초다. 요청 시작부터 60초 기한을 계산하여 헤더 수신 직후, 본문 수신 조각마다,
수신 종료 시 검사한다. 추가 HTTP 압축을 거부한 상태에서 `iter_bytes()`에 `chunk_size`를
지정하지 않아 작은 조각을 64 KiB까지 합쳐 기다리지 않는다.
이는 60초에 진행 중 I/O를 강제로 취소하는 절대 시간 제한은 아니다. 기한 직전에 시작한
개별 네트워크 읽기는 별도 15초 타임아웃까지 대기할 수 있으며, 수신이 반환되면 즉시
기한을 검사한다. 읽기 타임아웃도 `DOWNLOAD_TIMEOUT`으로 처리하고 응답을 닫는다.
ZIP 다운로드 최대 8 MiB, 압축 해제 최대 32 MiB다. Content-Length와 실제 수신량을
검사하고 예상한 MST 파일 하나만 읽는다. 경로 탈출·다른 파일·중복 멤버·암호화 ZIP을
거부하며 실제 압축 해제 읽기 크기도 제한한다. 리다이렉트와 HTTP 추가 압축은 허용하지
않는다. 공식 예제의 인증서 검증 해제, `extractall`, pandas 사용은 도입하지 않았다.

`provider_as_of`는 공식 자료에서 마스터 전체 기준시점을 확인할 수 없어 `null`이다.
수집 시각, HTTP Last-Modified, 개별 재무필드 `base_date`는 각각 보존하지만 이를
마스터 전체 기준시점으로 대체하지 않는다. 파일 다운로드·모든 행 파싱 성공은 공급자의
전 시장 무누락 보장이 아니므로 `market_completeness`는 항상 `unverified`다.
현재 목록을 과거 백테스트의 당시 유니버스로 사용할 수 없다.

## 구현 구조와 검증

- `domain/discovery.py`: 수동 KoreanStock과 독립된 레코드·판정·실행 모델.
- `kis/master_schema.py`, `master_parsing.py`, `master_client.py`: 공급자 스키마·파싱·전송.
- `discovery/policy.py`, `provider.py`: 명시적 버전 정책과 공급자 인터페이스.
- `discovery/repository.py`: 별도 저장소와 원본 보존·원자적 완료 처리.
- `discovery/service.py`, `application.py`: CLI와 미래 GUI가 공유하는 수집·조회 서비스.
- `discovery/cli.py`: 명령 인자·한국어 출력·종료코드.

자동 테스트는 기존 `pytest-socket --disable-socket` 정책을 유지한다.
HTTP는 MockTransport, 저장은 임시 디렉터리를 사용한다. fixture는 공식 헤더의 절대
위치를 별도로 지정한 합성 바이트이며 파서의 필드 배열로 생성하지 않는다.
`tests/fixtures/discovery/README.md`에 위치 표와 기대값 작성 방식을 기록했다.
네트워크 오류·손상 ZIP·CRC·크기 제한·빈 결과·잘린 행·혼합 개행·미지원 값·식별자 충돌·
마지막 UPDATE 실패 후 롤백·원본 해시·재조회·수동 유니버스 보존·CLI를 검증한다.

최초 v1 실제 검증: 2026-09-12 13:14:44~13:14:45 UTC(22:14 KST),
실행 ID `2078ec373f4441d9993834a14e10a090`, 임시 저장소
`/tmp/phalanx-discovery-live/discovery.sqlite3`에서 구현된 `refresh`로 수집하고
`show 005930`, `list --status eligible`로 오프라인 재조회했다.

| 시장 | 전체 / 정규화 | eligible | excluded | unknown | 다운로드 / 파싱 |
| --- | --- | --- | --- | --- | --- |
| KOSPI | 2,580 / 2,580 | 0 | 1,807 | 773 | success / success |
| KOSDAQ | 1,823 / 1,823 | 0 | 241 | 1,582 | success / success |

두 시장의 처리 상태는 성공이며 공급자 누락 여부는 미검증이다. v1에서 삼성전자
`005930`도 ETP 공백 때문에 `unknown`이었다. 다음 독립 검증을 거쳐 판정 정책만 v2로
변경했다. 실제 다운로드 원본은 프로젝트/Git 안에 저장하지 않았다.

## 독립 위치 검증과 같은 원본 재평가

보존된 SQLite를 `mode=ro`로 읽었다. 재다운로드하지 않았으며 원본 ZIP·MST의 SHA-256과
SQLite 파일 자체의 검증 전후 해시가 일치한다. 비교 기준은 위 v1 실행 ID이며 새 다운로드의
자료 변화가 포함되지 않는다. 재평가 시각은 별도 보고서의 `reevaluated_at`으로 기록하고
원래 수집 시각이나 공급자 기준시점을 바꾸지 않았다. 기존 v1 DB에 쓰지 않고
`/tmp/phalanx-discovery-policy-v2-evaluation.json`에 비교 결과를 별도로 저장했다.

### 파서와 독립적인 확인 절차

1. 공식 C 헤더의 `char name[width]`를 순서대로 누적했다. Phalanx의 `FIELDS`나 파서는
   이 위치 계산에 사용하지 않았다.
2. 공식 Python 예제를 실행하지 않고 AST에서 `field_specs` 숫자 배열만 읽어 헤더의
   모든 폭과 일치하는지 비교했다. 꼬리 길이는 각각 227·221바이트였다.
3. 원본의 단축코드 9·표준코드 12·한글명 40바이트와 꼬리 시작 61바이트를 대조했다.
   한글명 폭은 [한국투자증권 Expert 공식 참고서](https://new.real.download.dws.co.kr/download/expert_manual.pdf)의
   인쇄 페이지 263·266(2026-09-12 확인)에도 40으로 기재돼 있다. 이 문서는 구형 Expert
   계약이며 일부 필드명·Y/N 설명이 현재 헤더와 다르므로, 현재 플래그 의미나 ETP 코드
   집합을 덮어쓰는 근거로 사용하지 않았다. 현재 레이아웃은 고정 커밋의 두 헤더를 따른다.
4. 이 독립 위치로 원본 4,403행의 일곱 필드를 직접 잘라 저장 원천값·정규화값과 대조했다.
   표본도 종목명 추론 없이 공식 필드값으로 골랐다(005930만 요청에 따라 별도 선택).
5. 선택된 값·위치·기대 정규화·기대 판정을 `field_audit.json`에 고정했다. 자동 테스트는
   이 사실을 합성 레코드에 넣고 LF·CRLF·마지막 개행 없음 각각을 검증한다. 실제 다운로드
   전체나 원본 레코드 파일은 fixture에 넣지 않았다. 최신 시장 전체 건수도 테스트에 고정하지 않는다.

| 원본 필드 (0부터 시작한 바이트 위치) | KOSPI 위치·폭 | KOSDAQ 위치·폭 |
| --- | --- | --- |
| 증권그룹 | 61·2 | 61·2 |
| 우선주 | 219·1 | 214·1 |
| ETP | 83·1 | 79·1 |
| SPAC | 90·1 | 85·1 |
| 거래정지 | 121·1 | 116·1 |
| 정리매매 | 122·1 | 117·1 |
| 관리종목 | 123·1 | 118·1 |

원본은 모두 LF 및 마지막 개행이 있는 288/282바이트 행이다. 005930은 CP949 디코딩 후
284문자이고 원본은 288바이트다. KOSDAQ 표본 0001A0은 277문자/282바이트다.
문자 수를 바이트 위치로 혼용하면 밀릴 수 있지만 현재 파서는 바이트로 자른다.
독립 대조와 개행 변형 회귀 테스트에서 밀림은 발견되지 않았고 파서 코드는 변경하지 않았다.

### 같은 원본의 v1 → v2 결과

| 시장 | 전체 | 적격 | 제외 | 미확인 |
| --- | --- | --- | --- | --- |
| KOSPI | 2,580 | 0 → 759 | 1,807 → 1,807 | 773 → 14 |
| KOSDAQ | 1,823 | 0 → 1,581 | 241 → 241 | 1,582 → 1 |

적격으로 바뀐 모든 행의 v1 미확인 사유는 ETP 공백 하나뿐이었다. 기존 제외는 모두
유지됐다. 남은 미확인은 KOSPI의 우선주 코드 `9` 12건, 미지원 그룹 `EN` 및 ETP `9`
2건, KOSDAQ 우선주 코드 `9` 1건이다. 최신 공식 코드 정의를 추가로 확인하기 전까지
이를 보통주나 정상 ETP로 추정하지 않는다.

| 표본 | 그룹 | 우선주 | ETP 원시값 | SPAC | 정지/정리/관리 | v2 판정·주요 사유 |
| --- | --- | --- | --- | --- | --- | --- |
| KOSPI 005930 | ST | 0 | `" "` | N | N/N/N | eligible, NON_ETP_BY_ST_GROUP + V2_PASSED |
| KOSDAQ 0001A0 | ST | 0 | `" "` | N | N/N/N | eligible, NON_ETP_BY_ST_GROUP + V2_PASSED |
| KOSPI 000087 | ST | 2 | `" "` | N | N/N/N | excluded, PREFERRED_STOCK |
| KOSPI 0000D0 | EF | 0 | `"2"` | N | N/N/N | excluded, ETP + 비대상 그룹 |
| KOSPI Q500061 | EN | 0 | `"3"` | N | N/N/N | excluded, ETP + 미지원 그룹 사유 보존 |
| KOSDAQ 0004Y0 | ST | 0 | `" "` | Y | N/N/N | excluded, SPAC |
| KOSPI F70101B96 | BC | 0 | `" "` | N | Y/N/N | excluded, TRADING_HALTED + 비대상 그룹 + ETP 누락 |
| KOSPI 006380 | ST | 0 | `" "` | N | N/Y/N | excluded, LIQUIDATION_TRADING |
| KOSPI 000040 | ST | 0 | `" "` | N | N/N/Y | excluded, MANAGED_ISSUE |
| KOSPI 00781K | ST | 9 | `" "` | N | N/N/N | unknown, 미지원 우선주 코드 |
| KOSPI Q520100 | EN | 0 | `"9"` | N | N/N/N | unknown, 미지원 그룹·ETP 코드 |
| KOSDAQ 03481K | ST | 9 | `" "` | N | N/N/N | unknown, 미지원 우선주 코드 |

ETP 공백의 정규화값은 모든 표본에서 `null`이다. 나머지 코드 필드는 문자열,
Y/N 상태는 각각 true/false다. 005930의 최종 판정은 ST·우선주 0·SPAC N·거래 상태
N/N/N과 별도로 기록된 ST 비ETP 근거에 따른 것이며, 종목명이나 적격 목표 건수는
정책 입력으로 사용하지 않았다. 공백 예외가 다른 누락·충돌을 가리는지, 대표 제외가
유지되는지, v1 저장 결과를 v2 실행이 덮어쓰지 않는지도 회귀 테스트로 검증한다.

## 변경 범위와 검증 환경

이번 작업의 무관한 포맷 변경 8개는 각각 기준 `046c3c3`의 Ruff 포맷 결과와 정확히
일치하는지, AST·주석이 동일한지 확인한 뒤 해당 포맷 변경만 되돌렸다. 대상은
`domain/volatility_overlay.py`, `portfolio/self_financing.py`, 그리고
`test_account_performance_application.py`, `test_allocation_backtest.py`,
`test_current_price_client.py`, `test_self_financing.py`, `test_valuation_price_service.py`,
`test_volatility_overlay_research.py`다. 사용자 작업은 제거하지 않았다.

CI의 `uv run mypy src`는 `mypy_path` 없이 동일한 소스 80개를 검사하고 통과한다.
이전에 추가했던 `mypy_path = "src"`를 제거해 `pyproject.toml`은 기준과 동일해졌다.
인자가 없는 `uv run mypy`는 기존 설정에서 설치 패키지의 `py.typed`가 없어 실패하지만,
현재 CI가 쓰는 명령은 `mypy src`이며 검사 범위·strict 옵션을 줄이지 않았다.

CI와 같은 uv 0.12.5·Python 3.12 계열(로컬 3.12.3)에서
`uv sync --locked --group dev --python 3.12`로 잠금 의존성을 확인했다. CI는 패치 버전을
고정하지 않으므로 실행 시점의 CI 패치 버전까지 동일하다고 주장하지 않는다.
검사는 `uv run ruff check .`, `uv run mypy src`, `uv run pytest -q`, `git diff --check`다.
`UV_NO_ENV_FILE=1`, `UV_NO_SYNC=1`, `_TYPER_FORCE_DISABLE_TERMINAL=1`은 CI와 같으며
쓰기 제한으로 `UV_CACHE_DIR=/tmp/phalanx-uv-cache`를 추가했다. 포맷 검사는 discovery
소스·테스트·CLI에 한정한다. 전체 포맷 검사에 남는 8개 파일의 문제는 기준 main에도
존재하며 이를 통과시키려고 무관한 파일을 수정하지 않는다.

최종 결과: Ruff 통과, `mypy src` 80개 소스 통과, 전체 테스트 1,737개 통과,
`git diff --check` 통과, 기능 관련 Python 19개 파일 포맷 통과.
전체 포맷 검사는 위 기준 파일 8개 때문에 종료코드 1이며, 기능 변경에서 발생한
포맷 문제와 구분한다. 비교 보고서와 독립 검증 스크립트는 검토용 ZIP의 `review/`에
포함하며, 실제 SQLite·ZIP·MST 다운로드와 계좌·자격증명·reports·research는 포함하지 않는다.
