from __future__ import annotations
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))

from backend.app.repositories.database_repository import engine, import_intraday, import_market_data, import_prediction, import_stock_list, import_verification, init_schema

def main():
    p=argparse.ArgumentParser(description="初始化MySQL并导入现有股票数据")
    p.add_argument("--data-dir",type=Path,required=True)
    args=p.parse_args(); db=engine(); init_schema(db)
    stocks=import_stock_list(args.data_dir/"list.csv",db); market=import_market_data(args.data_dir,db)
    pred=args.data_dir/"predictions"; candidates=0; intraday=0
    for c in sorted(pred.glob("next_day_candidates_*.csv")):
        label=c.stem.rsplit("_",1)[-1]; f=pred/f"factor_report_{label}.csv"; s=pred/f"model_summary_{label}.json"
        if f.exists() and s.exists(): candidates += import_prediction(c,f,s,db)
    for c in sorted(pred.glob("tradeable_candidates_*.csv")):
        label=c.stem.rsplit("_",1)[-1]; f=pred/f"tradeable_factor_report_{label}.csv"; s=pred/f"tradeable_model_summary_{label}.json"
        if f.exists() and s.exists(): candidates += import_prediction(c,f,s,db)
    idir=pred/"intraday"
    for s in sorted(idir.glob("intraday_summary_*.json")):
        suffix=s.stem.removeprefix("intraday_summary_"); d=idir/f"intraday_detail_{suffix}.csv"; g=idir/f"intraday_groups_{suffix}.csv"
        if d.exists() and g.exists(): intraday += import_intraday(d,g,s,db)
    verified=0; vdir=pred/"verification"
    for s in sorted(vdir.glob("verification_summary_*.json")):
        label=s.stem.rsplit("_",1)[-1]; d=vdir/f"verification_detail_{label}.csv"; g=vdir/f"verification_groups_{label}.csv"
        if d.exists() and g.exists(): verified += import_verification(d,g,s,db)
    for s in sorted(vdir.glob("tradeable_verification_summary_*.json")):
        label=s.stem.rsplit("_",1)[-1]; d=vdir/f"tradeable_verification_detail_{label}.csv"; g=vdir/f"tradeable_verification_groups_{label}.csv"
        if d.exists() and g.exists(): verified += import_verification(d,g,s,db)
    print(f"导入完成：股票 {stocks} 只，日线 {market} 行，候选 {candidates} 行，盘中明细 {intraday} 行，验证明细 {verified} 行")

if __name__ == "__main__": main()
