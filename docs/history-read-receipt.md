# 저장 일봉의 읽기 확인 영수증

`phalanx market-data history read-receipt`는 완료된 일봉 결과를 **새 SQLite 읽기 트랜잭션**에서 확인한 뒤 별도 JSON 영수증을 만든다. 가격 수집 중 기록한 `finished_at`은 DB 저장 전에 생성된다. 이 영수증은 그보다 늦은 시점에 해당 결과가 로컬 DB에서 읽혔다는 근거를 남긴다. 네트워크 조회나 주문은 수행하지 않는다.

```bash
uv run phalanx market-data history read-receipt JOB_ID \
  --history-db /absolute/private/history.sqlite3 \
  --code 005930 --code 0001A0 \
  --output /absolute/private/history-read-receipt.json

uv run phalanx candidates replay-history \
  --history-db /absolute/private/history.sqlite3 \
  --job-id JOB_ID \
  --as-of 2026-09-11 \
  --decision-at DECISION_AT_WITH_TIMEZONE \
  --code 005930 --code 0001A0 \
  --metric return_60 --top 1 --max-age-days 2 \
  --read-receipt /absolute/private/history-read-receipt.json \
  --output /absolute/private/history-replay.json
```

`JOB_ID`와 `--code`는 두 명령에서 같은 작업과 종목을 가리켜야 한다. `DECISION_AT_WITH_TIMEZONE`에는 시간대가 포함된 판단 시각을 넣는다. 이 시각은 영수증의 읽기 확인 시각 이상이며 재실행 시각 이하여야 한다. `--as-of`는 가격 특성값에 사용할 마지막 거래일이며 판단 시각과 별개다.

종목은 중복 없이 1~25개를 지정하고 두 명령에서 같은 순서로 전달한다. 영수증 파일은 최대 1 MB까지만 재실행 입력으로 읽는다. 현재 저장소와 루트 CLI의 실행 환경은 Linux다. 잘못된 영수증 내용은 종료 코드 65, 영수증 파일을 읽을 수 없거나 출력 파일이 이미 있는 경우는 종료 코드 66으로 구분한다.

영수증에는 작업·종목별 저장 상태와 결과를 식별하는 해시, 마지막 완료 시도, 읽기 확인 시각이 담긴다. `replay-history --read-receipt`는 제공한 영수증과 현재 DB의 선택 종목을 다시 대조한다. 작업이나 종목이 다르거나 저장 상태·가격 결과가 달라졌거나 읽기 확인 시각이 `decision_at`보다 늦으면 거부한다. 영수증 작성이 실패했거나 기존 작업에 영수증이 없다면 과거 판단 시각의 읽기 근거를 소급해 만들 수 없다. 나중에 영수증을 생성하더라도 실제로 다시 읽은 시각만 기록된다.

재실행 결과는 `local_snapshot_read_before_decision_confirmed=true`와 `receipt_check=local_committed_snapshot_read_before_decision`으로 추가 검사의 적용을 표시한다. `read_receipt_sha256`은 전달한 파일의 원본 바이트 해시이고 `read_receipt_content_sha256`은 결과 안에 포함된 영수증 내용의 정규화 해시다. 해시 자체는 외부 서명이 아니다. 영수증이 없는 기존 실행은 수집 완료 시각 검사만 수행하고 이 확인값을 `false`로 남긴다.

영수증은 기존 파일을 덮어쓰지 않는 별도 파일이다. DB의 SQLite 백업이나 Windows용 내보내기를 다른 기기로 옮길 때 이 JSON도 함께 보관하고, 재실행에서 `--read-receipt`로 명시해야 한다. DB만 옮기면 읽기 확인 시각의 근거가 따라오지 않는다. 영수증을 생성한 뒤에도 DB와 파일의 무결성을 함께 보관해야 한다.

## 검증 범위

읽기 확인 시각이 판단 시각 이하라면, **로컬 프로그램의 시계에 따르면** 영수증과 일치하는 결과가 그 시각까지 DB에서 읽혔음을 확인할 수 있다. 이 시각은 SQLite 커밋의 정확한 순간이 아니다. 영수증 파일이 저장된 시각이나 과거 판단 결과가 실제로 계산된 시각도 뜻하지 않는다.

로컬 시계와 파일은 외부에서 잘못 설정하거나 변조할 수 있으며, 해시는 공급자의 서명이 아니다. KIS 과거 수정주가의 행별 최초 공표 시각과 수정 버전도 제공되지 않는다. 따라서 공급자가 과거 판단 시각에 같은 가격을 제공했는지, 당시 후보군에 생존편향이 없었는지, 거래일이 빠지지 않았는지는 이 영수증으로 증명할 수 없다. 결과의 `point_in_time_backtest_guaranteed=false`는 유지된다.
