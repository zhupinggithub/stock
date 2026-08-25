from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from backend.app.collectors.market_fetcher import main

if __name__ == "__main__":
    try: main()
    except Exception as exc:
        print(f"执行失败：{exc}",file=sys.stderr,flush=True)
        raise SystemExit(1) from exc
