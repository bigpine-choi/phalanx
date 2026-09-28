"""One bounded, read-only history request through the existing Phalanx backend.

Run with its WSL virtualenv. Credentials and token handling stay in that backend;
only an allowlisted public OHLCV result crosses into Godot. No account API.
"""
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import json
import os
import sys

CODES = frozenset({'005930', '000660', '005380', '035420', '069500'})


def collect(code, reader, now=None):
    if code not in CODES:
        raise ValueError('unsupported security')
    now = now or datetime.now(ZoneInfo('Asia/Seoul'))
    end = now.date() - timedelta(days=1)
    start = end - timedelta(days=365)
    bars = reader.fetch_daily_bars(code, start, end)
    candles = []
    for bar in bars:
        if bar.stock_code != code or not start <= bar.trade_date <= end:
            raise ValueError('unexpected security/date')
        candles.append({'date': bar.trade_date.isoformat(),
                        'open': float(bar.open_price), 'high': float(bar.high_price),
                        'low': float(bar.low_price), 'close': float(bar.close_price),
                        'volume': bar.volume})
    if not 2 <= len(candles) <= 300:
        raise ValueError('insufficient/excess history')
    return {'provider': 'KIS', 'code': code, 'currency': 'KRW',
            'market': 'KRX', 'adjusted': True, 'fetched_at': int(datetime.now().timestamp()),
            'requested_start': start.isoformat(), 'requested_end': end.isoformat(),
            'candles': candles}


def main():
    if len(sys.argv) != 4 or sys.argv[1] not in CODES:
        return 2
    code, output, request_id = sys.argv[1:]
    try:
        # Existing backend owns private-file validation, token locking,
        # sequential pagination, rate limits, TLS and provider validation.
        from phalanx.market_data.history.application import production_history_reader
        with production_history_reader() as reader:
            result = {'ok': True, 'payload': collect(code, reader)}
    except Exception:
        # Never serialize provider exceptions, credentials, headers or response bodies.
        result = {'ok': False, 'error': 'KIS_READ_FAILED'}
    result.update({'request_id': request_id, 'code': code})
    destination = Path(output)
    temporary = destination.with_suffix('.pending')
    try:
        temporary.write_text(json.dumps(result, ensure_ascii=False, allow_nan=False), encoding='utf-8')
        os.replace(temporary, destination)
    except Exception:
        return 3
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
