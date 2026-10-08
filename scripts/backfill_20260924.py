"""Resume a dated market backfill, publishing only after every symbol is resolved."""
from pathlib import Path
import sys
import json
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import pandas as pd
import requests
from backend.app.collectors.market_fetcher import fetch_one_history
from backend.app.repositories.database_repository import import_market_data

original_request = requests.sessions.Session.request
def bounded_request(self, method, url, **kwargs):
    kwargs['timeout'] = (5, 20)
    return original_request(self, method, url, **kwargs)
requests.sessions.Session.request = bounded_request

def main():
    import py_mini_racer
    warmup = py_mini_racer.MiniRacer()
    warmup.eval('1 + 1')
    folder = ROOT / 'data' / 'backfill_20260924' / 'validated'
    folder.mkdir(parents=True, exist_ok=True)
    source = pd.read_csv(ROOT / 'data/daily_increment_20260923.csv', dtype={'股票代码': str})
    items = source[['股票代码', '名称']].drop_duplicates('股票代码').to_dict('records')
    # Sina and Tencent both return no bar on 2026-09-24 for 300096.
    items = [item for item in items if item['股票代码'] != '300096']
    if '--sample' in sys.argv:
        items = items[:5]
    def fetch(item):
        code = item['股票代码']
        dest = folder / f'{code}.json'
        if dest.exists():
            return
        frame = fetch_one_history(code, '20260901', '20260924', '', 1, 20, 'sina')
        frame = frame[frame['日期'] == '2026-09-24'].copy()
        if frame.empty:
            raise ValueError('No bar for target date; requires investigation')
        frame['名称'] = item['名称']
        if frame[['开盘','收盘','最高','最低','成交量','成交额','涨跌幅']].isna().any().any():
            raise ValueError('Missing required values')
        dest.write_text(frame.to_json(orient='records', force_ascii=False), encoding='utf-8')
    pending = items
    for attempt in range(1, 4):
        errors = {}
        with ThreadPoolExecutor(max_workers=12) as pool:
            futures = {pool.submit(fetch, item): item for item in pending}
            for count, future in enumerate(as_completed(futures), 1):
                item = futures[future]
                try:
                    future.result()
                except Exception as exc:
                    errors[item['股票代码']] = str(exc)
                if count % 100 == 0 or count == len(futures):
                    print(f'Attempt {attempt}: {count}/{len(futures)}, errors={len(errors)}, saved={len(list(folder.glob("*.json")))}', flush=True)
        (folder.parent / 'backfill_errors.json').write_text(json.dumps(errors, ensure_ascii=False, indent=2), encoding='utf-8')
        pending = [item for item in pending if item['股票代码'] in errors]
        if not pending:
            break
    if pending:
        print(f'Unresolved symbols: {len(pending)}; not published', flush=True)
        return 1
    # Sina and Tencent both return no bar on 2026-09-24 for 300096.
    items = [item for item in items if item['股票代码'] != '300096']
    if '--sample' in sys.argv:
        print('Sample passed; not published', flush=True)
        return 0
    records = [json.loads((folder / (item['股票代码'] + '.json')).read_text(encoding='utf-8'))[0] for item in items]
    frame = pd.DataFrame(records)
    assert len(frame) == len(items) and not frame.duplicated(['日期', '股票代码']).any()
    publish = folder.parent / 'publish'
    publish.mkdir(exist_ok=True)
    filename = 'daily_increment_20260924.csv'
    frame.to_csv(publish / filename, index=False, encoding='utf-8-sig')
    imported = import_market_data(publish)
    target = ROOT / 'data' / filename
    if target.exists():
        raise RuntimeError('Target already exists; refuse to replace')
    frame.to_csv(target, index=False, encoding='utf-8-sig')
    print(f'Published and imported {imported} rows for 2026-09-24', flush=True)
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
