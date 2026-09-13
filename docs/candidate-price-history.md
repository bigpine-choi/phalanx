# 시장 후보 일봉 저장·재개 v1

특정 **성공 discovery 실행**의 적격 후보를 고정하고 KIS 수정주가 일봉 OHLCV를 별도 SQLite에 저장한다. CLI와 프로그램은 같은 `HistoryService`를 사용한다. 수동 유니버스·계좌 스냅샷·NAV·연구 입력에는 자동으로 반영하지 않는다.

## 사용법

```bash
# 오프라인 생성: RUN_ID를 사용할 discovery 실행 ID로 바꾼다.
uv run phalanx market-data history create \
  --discovery-run-id RUN_ID \
  --start 2026-01-01 --end 2026-09-11 \
  --code 005930 --code 0001A0

# 위 명령이 출력한 JOB_ID 사용. 1종목의 전체 요청 기간을 수집한다.
uv run phalanx market-data history run JOB_ID --max-symbols 1
# 같은 작업의 남은 종목부터 이어서 처리한다.
uv run phalanx market-data history run JOB_ID
# 실패로 기록된 종목을 재시도하려면 명시한다.
uv run phalanx market-data history run JOB_ID --retry-failed --max-symbols 1

# 두 명령 모두 자격증명·OAuth·네트워크 없이 저장된 결과만 조회한다.
uv run phalanx market-data history status JOB_ID
uv run phalanx market-data history show JOB_ID 0001A0
```

`create`는 반복 가능한 `--code` 또는 `--all-eligible` 중 **정확히 하나**를 요구한다. 중복 `--code`, 지정 실행에 없는 종목·비적격 종목은 오류다. 실행이 없거나 진행 중·부분 성공·실패이면 다른 성공본으로 대체하지 않는다. `--code` 순서를 보존하며 `--all-eligible`은 해당 스냅샷의 시장·레코드 순서를 보존한다. 중복 단축코드로 식별이 모호한 입력도 거부한다.

시작·종료일은 필수이며 포함 범위다. 종료일은 **Asia/Seoul 기준 오늘보다 이전**이어야 한다. 따라서 위 예제는 2026-09-12 이후에 실행할 수 있다. `--max-symbols`는 해당 실행에서 시도할 종목 수의 양의 정수 상한이며, 페이지나 HTTP 요청 수의 상한이 아니다.

기본 저장 위치:

- discovery 입력: `~/.local/share/phalanx/discovery/discovery.sqlite3`
- 일봉 작업·결과: `~/.local/share/phalanx/market-data/history.sqlite3`

`create --discovery-db PATH --history-db PATH`로 두 경로를 지정한다. `run`, `status`, `show`는 `--history-db PATH`만 사용하며 discovery DB를 다시 읽지 않는다. 다른 경로에 생성한 작업을 조회·재개할 때도 같은 `--history-db`를 전달한다.

`run`만 기존 `~/.config/phalanx/credentials.env`와 `~/.cache/phalanx/token-cache/kis-access-token.json`을 사용한다. 처리 대상이 하나도 없으면 `run`도 자격증명에 접근하지 않는다. 주문·현재가·잔고 조회는 수행하지 않는다.

## 저장 계약

스키마 버전은 `1`, 수집 계약은 `whole_symbol_range_v1`이다. 독립 DB의 `jobs`에는 변경하지 않는 작업 JSON, `symbols`에는 순서별 상태·시도 이력·결과 JSON을 저장한다. 생성 시 다음 값을 복사한다.

- JOB_ID, 생성 시각, 요청 기간, 대상의 순서·시장·단축코드·표준코드·이름
- discovery 실행 ID, 수집 시작·완료 시각, 대상별 정책 버전, 시장 원본 ZIP·MST의 파일명·크기·SHA-256
- 공급자 `KIS`, endpoint, TR ID, KRX `J` / 일봉 `D` / 수정주가 `0`

discovery를 나중에 refresh해도 작업 입력은 바뀌지 않는다. 원본 마스터와 자격증명은 일봉 DB에 복사하지 않는다. 단축코드·표준코드·기업 식별자를 서로 대체하지 않는다.

종목별 시도 번호, 상태, timezone-aware 수집 시작·종료 시각, 안전한 오류 코드·설명을 보존한다. 정상 결과는 거래일 오름차순 OHLCV 전체, 행 수, 실제 최초·최종 거래일과 가격 데이터 SHA-256을 포함한다. 가격은 `Decimal`의 십진 문자열로 저장하므로 float 변환이나 반올림이 없다. 해시는 가격·종목코드·거래일·거래량의 정렬된 키/고정 구분자 JSON에 대한 SHA-256이며, 읽을 때 다시 검증한다. 같은 정확한 가격 데이터는 같은 해시를 낸다. 시도 시각은 가격 해시와 별도로 보존한다.

**한 종목의 전체 요청 기간을 조회한 뒤 모든 행과 완료 상태를 한 트랜잭션으로 커밋한다.** 일부 페이지만 저장하거나 다른 수집 시점의 과거 수정주가와 신규 구간을 이어 붙이지 않는다. 완료 결과를 덮어쓰는 갱신은 거부한다. 기간 변경이나 재수집은 새 작업을 생성한다. 서로 다른 작업은 같은 종목·기간이어도 독립적인 수정주가 관측값과 provenance를 갖는다.

Linux 사용자 데이터 경로 규칙을 따르며 새 전용 디렉터리는 `0700`, DB·실행 잠금 파일은 `0600`이다. 기존 부적절한 권한, 심볼릭 링크, 하드 링크, 다른 SQLite 애플리케이션/스키마는 자동 변경하지 않고 거부한다. SQLite rollback journal과 `synchronous=FULL`을 사용한다. 저장 실패는 이전 정상 결과를 지우지 않는다.

## 상태, 재개, 오류

| 상태 | 의미 | 다음 run |
| --- | --- | --- |
| `pending` | 미처리 또는 중단된 시도에서 회복 | 전체 요청 기간 조회 |
| `in_progress` | 종목의 시작 시도를 기록했으나 완료가 미확정 | 실행 잠금을 획득한 뒤 중단 시도로 기록하고 재개 |
| `completed` | API 조회 완료, 1행 이상 저장 | 건너뜀 |
| `empty` | API 정상 조회 완료, 0행 저장 | 건너뜀 |
| `failed` | 공급자·응답 데이터 오류 | `--retry-failed`가 있을 때만 재시도 |
| `unsupported` | 후보 단축코드가 일봉 요청 형식에 부적합 | 호출 없이 사유·건수 표시 |

한 `run`에서 HTTP 클라이언트·토큰 관리자·`KisRequestPacer`를 공유한다. 종목마다 pacer를 초기화하지 않으며 병렬 호출하지 않는다. 기존 클라이언트의 페이지당 최대 100행, 과거 방향 페이지 조회, 중복 제거·충돌 검출, 최대 페이지 제한(100), 토큰 만료 시 1회 재인증, 제한된 KIS 호출 제한 재시도를 재사용한다. 기본 최소 요청 간격은 1.1초, KIS `EGW00201`은 최대 3회 시도하며 시도 사이 61초 대기한다. `max-symbols=1`에서도 한 종목의 페이지·재시도 요청은 여러 번일 수 있다.

페이지 요청의 HTTP 401과 KIS 만료 코드 `EGW00123`은 재인증 1회 한도를 공유한다. 만료 코드는 HTTP 200뿐 아니라 HTTP 500에서도 일반 HTTP 오류 분류 전에 처리한다. 갱신 후 401 또는 만료 코드가 반복되면 현재 종목과 시도에 `AUTHENTICATION_FAILED`를 저장하고 나머지 종목 호출을 중단한다. 만료·호출 제한 코드가 없는 일반 HTTP 500은 기존 HTTP 오류로 기록하고 다음 종목으로 진행한다. 재인증으로 `EGW00201` 호출 제한 시도 횟수가 초기화되지는 않는다.

종목별 API 오류·잘못된 데이터·페이지 충돌·네트워크 오류는 안전한 사유를 저장하고 다음 종목으로 진행한다. OAuth/인증 실패, HTTP 403, KIS 호출 제한 재시도 소진, HTTP 429, 예상하지 못한 공급자 오류는 나머지 종목을 반복 호출하지 않고 중단한다. HTTP 429에 KIS 제한 코드가 없으면 재시도 소진으로 부르지 않고 `HTTP_RATE_LIMIT`으로 중단한다. 저장 실패도 즉시 중단한다. 비밀정보를 제거한 공급자 오류 설명을 보존하며 상세 HTTP 응답 본문·요청 URL·토큰은 저장하지 않는다.

작업별 비차단 OS 파일 잠금은 수집 시작부터 끝까지 유지한다. 같은 DB의 같은 JOB_ID 동시 실행은 `JOB_BUSY`로 실패한다. 잠금 파일은 삭제하지 않으며 프로세스 종료 시 OS가 잠금을 해제한다. DB 쓰기 트랜잭션은 네트워크 요청 동안 유지하지 않는다. 서로 다른 작업/프로세스 전체의 호출 속도를 전역 조정하는 기능은 v1 범위 밖이다.

Ctrl+C는 현재 시도를 `interrupted`로 남기고 종료한다. 강제 종료나 쓰기 실패로 `in_progress`가 남으면 다음 `run`에서 이를 회복한다. 강제 종료의 실제 시각은 알 수 없으므로 `finished_at=null`을 유지하고 회복을 감지한 `recovered_at`을 별도로 기록한다. 중단된 종목은 전체 기간을 다시 조회한다. 네트워크 완료 후 커밋 전에 종료되면 그 종목을 다시 호출할 수 있으나 완료된 결과는 중복 저장하지 않는다. 쓰기 중 종료로 남은 SQLite journal은 다음 `run`의 짧은 쓰기 연결에서 복구한다. 그 복구 전에는 오프라인 읽기가 저장 오류를 보고할 수 있다.

재개하면 종목별 수집 시점이 달라질 수 있다. 모든 종목이 동일 시점의 수정주가 체계를 공유한다고 가정하지 말고 각 시도 시각과 작업 provenance를 확인해야 한다.

종료 코드: 생성/조회 또는 모든 종목 정상 완료 `0`, 제한량 도달로 미완료/실패/미지원 잔존 `2`, 입력·조회·실행 잠금 오류 `65`, 저장 오류 `66`, 작업 시작 시 자격증명·OAuth 오류 `69`, Ctrl+C `130`. 종목 수집 중 공통 인증 오류는 종목 `failed`와 종료 코드 `2`로 표시한다. `status`는 미완료 작업이라도 읽기에 성공하면 `0`이다.

## 식별자와 공식 API 출처

일봉은 `validate_daily_stock_code`와 `DailyBar`에서 **정확한 ASCII 숫자·대문자 6자리**를 허용한다. `005930`, `0001A0`을 문자열 그대로 유지한다. 소문자, 전각 문자, 공백, 잘못된 길이와 정수는 거부하며 자릿수 보정·대문자 변환을 하지 않는다. discovery에 적격이지만 형식 미지원인 식별자가 있으면 대상을 숨기지 않고 `unsupported`로 보존한다.

이는 공급자의 실제 조회 지원을 보장하는 규칙이 아니다. 형식이 맞아도 공급자가 조회를 거부하면 안전한 실제 오류와 `failed` 상태를 남긴다. 공식 예제는 종목번호를 문자열로 받지만 모든 영숫자 종목에 대한 성공을 보장하지 않는다.

기존 숫자 전용 `validate_market_data_stock_code`는 현재가와 계좌 평가 호출자에서 유지한다. 기존 `market-data daily` 실행 경로만 별도 일봉 검증으로 변경했다. `CurrentPriceObservation`, 평가 번들, 수동 `KoreanStock`의 지원 범위를 영숫자로 확장한 것은 아니다.

확인한 한국투자증권 공식 자료:

- [국내주식기간별시세(일/주/월/년) 예제](https://github.com/koreainvestment/open-trading-api/blob/b4e6249714418aa57833d1cbbbced39cbcc5b125/examples_llm/domestic_stock/inquire_daily_itemchartprice/inquire_daily_itemchartprice.py)
- 확인 커밋: `b4e6249714418aa57833d1cbbbced39cbcc5b125` (2026-09-12 확인)
- endpoint: `GET /uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice`, TR ID: `FHKST03010100`
- `FID_COND_MRKT_DIV_CODE=J`는 KRX, `FID_PERIOD_DIV_CODE=D`는 일봉, `FID_ORG_ADJ_PRC=0`은 수정주가. NXT/통합시장, 주봉/월봉, 비수정주가를 이 작업에 섞지 않는다.

## 데이터 한계와 읽기 인터페이스

API 조회 완료는 요청 기간 모든 거래일의 무누락 검증이 아니다. 결과는 항상 `trading_day_completeness=unverified`다. 휴장·거래정지·신규상장 등을 추정해 없는 날짜를 채우지 않는다. 정상 빈 응답은 상장폐지·미지원의 확정 근거가 아니며, 공급자 누락 여부도 확인하지 않는다. 기존 일봉 파서가 거부하는 누락·0/음수 가격·OHLC 관계 오류는 임의 보정하지 않고 해당 종목 실패로 남긴다.

현재 discovery 후보를 과거 요청 기간의 당시 유니버스로 해석하면 생존편향·미래정보 문제가 생긴다. 이 기능은 당시 유니버스를 구성하지 않는다. 수정주가 OHLCV를 배당 포함 총수익률이나 완전한 기업행사 데이터로 표시하지 않는다.

```python
from pathlib import Path
from phalanx.market_data.history.repository import SqliteHistoryRepository

repository = SqliteHistoryRepository(Path("/absolute/private/history.sqlite3"))
view = repository.load("JOB_ID")  # 고정 입력과 모든 종목 진행 상태
job, symbol = repository.show("JOB_ID", "0001A0")
bars = repository.read_bars("JOB_ID", "0001A0")  # tuple[DailyBar, ...], 네트워크 없음
```

정상 빈 결과는 `()`이며 미처리·실패·미지원은 `RESULT_NOT_READY` 오류다. `show` 또는 `load`로 그 차이와 시도 이력을 먼저 확인할 수 있다. CLI `show`도 같은 저장소를 사용하며 가격 문자열·해시·시도·원천 근거를 JSON으로 출력한다.

`show`와 `read_bars`는 같은 읽기 트랜잭션에서 고정 작업 입력을 검증하고 요청 종목의 ordinal을 찾은 뒤, 해당 `job_id`·ordinal의 `state_json` 한 행만 조회·파싱한다. 작업 ID, 상태의 ordinal, 결과의 종목·요청 기간·가격 해시는 계속 검증한다. 다른 종목의 가격 결과는 읽거나 파싱하지 않으며 그 결과의 손상 검사도 수행하지 않는다. 전체 종목의 상태와 결과 검증이 필요하면 `load`를 사용한다. 고정 입력 JSON에는 전체 대상 목록이 있으므로 입력 파싱 비용은 대상 수에 비례한다.

## 자동 검증

`tests/test_history_jobs.py`, `tests/test_history_kis.py`, `tests/test_history_cli.py`는 임시 디렉터리·합성 마스터·MockTransport·가짜 시계를 사용한다. 공유 호출 간격과 페이지 조회, 토큰 갱신, 영숫자 왕복, 명시적 실패 재시도, Ctrl+C/프로세스 종료, 작업 잠금, 실제 SQLite 트리거에 의한 쓰기 실패·원자성, 해시 손상, 오프라인 명령의 HTTP·자격증명 접근 차단을 검증한다. 전체 테스트는 기존 `pytest-socket --disable-socket` 정책을 유지하며 실제 API나 자격증명을 사용하지 않는다.

`tests/test_market_data_client.py`와 `tests/test_history_kis.py`는 HTTP 200/500 만료 응답의 갱신 후 성공·반복 실패, 401과의 공유 재인증 한도, 일반 HTTP 500과 호출 제한 처리, 인증 실패 후 명시적 재시도를 검증한다. `tests/test_history_repository.py`는 여러 종목·작업이 저장된 DB에서 단일 종목 조회의 상태 JSON 파싱과 가격 해시 검증이 대상 종목에만 수행되는지 기록한다. 실행시간 임계치를 사용하지 않으며, 다른 종목의 손상된 결과가 대상 조회에 영향을 주지 않는지와 대상의 작업 ID·ordinal·종목·기간·해시 손상 거부, 정상 빈 결과와 미완료 결과의 구분도 검증한다.

### 제한된 실제 검증 (2026-09-12 UTC)

discovery 실행 `0ccb08f9cf4345c58e234377cb1cc370`은 성공본이며 두 종목 모두 `domestic-common-stock-v2`의 적격 후보임을 먼저 확인했다. 이 실행으로 생성한 작업 `ca82427a79bf4527ab83ffc45aba7c21`의 요청 기간은 `2026-01-01 ~ 2026-09-11`이다. `/tmp/phalanx-candidate-price-history-live/history.sqlite3`에 저장했으며 원본 다운로드나 실제 DB를 저장소에 포함하지 않는다.

| 종목 | 상태 | 행 수 | 실제 최초 거래일 | 실제 최종 거래일 | 시도 |
| --- | --- | ---: | --- | --- | ---: |
| 005930 | completed | 171 | 2026-01-02 | 2026-09-11 | 1 |
| 0001A0 | completed | 151 | 2026-01-30 | 2026-09-11 | 1 |

첫 `run --max-symbols 1`은 005930만 완료하고 종료 코드 `2`, 같은 작업의 두 번째 `run`은 0001A0만 완료하고 종료 코드 `0`이었다. 005930의 시도·수집 시각·결과 해시가 재개 전후 정확히 같음을 확인했다. 이어 자격증명 로더·토큰 조회·HTTP 전송을 실패하도록 교체한 검증에서 CLI `status`, 두 종목 `show`, 완료 작업의 추가 `run` 모두 종료 코드 `0`이었고 저장 내용이 같았다.

이번 영숫자 종목 조회는 성공했지만 모든 영숫자 종목에 일반화하지 않는다. 위 행 수와 최초 거래일은 받은 데이터의 관측 결과이며, 거래일 무누락·상장일의 확정 근거가 아니다. 자동 테스트에 실제 종목 수·응답 행 수를 고정하지 않았고, 전체 적격 후보 수집은 수행하지 않았다.
