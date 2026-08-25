"""One command for collection, verification, prediction and MySQL synchronization."""
from __future__ import annotations
import argparse
import os
import subprocess
import sys
from pathlib import Path
from backend.app.repositories.database_repository import engine, import_market_data, import_prediction, import_stock_list, import_verification, init_schema

ROOT = Path(__file__).resolve().parents[3]

def run(*args: str) -> None:
    command = [str(ROOT / args[0]), *args[1:]]
    options={"check":True,"cwd":ROOT}
    if os.name=="nt": options["creationflags"]=subprocess.CREATE_NO_WINDOW
    subprocess.run([sys.executable, *command], **options)

def main() -> None:
    p=argparse.ArgumentParser(description="A股每日采集、验证、预测流水线")
    p.add_argument("--data-dir",type=Path,required=True)
    p.add_argument("--skip-collect",action="store_true",help="不执行当日增量采集")
    p.add_argument("--source",choices=("sina","eastmoney","auto"),default="sina")
    p.add_argument("--top",type=int,default=30)
    args=p.parse_args(); init_schema(); db=engine()
    if not args.skip_collect:
        run("scripts/market_fetcher.py","incremental","--output-dir",str(args.data_dir),"--list-source",args.source)
    import_stock_list(args.data_dir/"list.csv",db)
    print(f"MySQL同步日线：{import_market_data(args.data_dir,db)} 行")
    run("scripts/verify_predictions.py","--data-dir",str(args.data_dir))
    run("scripts/stock_predictor.py","--data-dir",str(args.data_dir),"--top",str(args.top))
    pred=args.data_dir/"predictions"; candidates=sorted(pred.glob("next_day_candidates_*.csv"))[-1]; label=candidates.stem.rsplit("_",1)[-1]
    count=import_prediction(candidates,pred/f"factor_report_{label}.csv",pred/f"model_summary_{label}.json",db)
    vdir=args.data_dir/"predictions"/"verification"
    for s in sorted(vdir.glob("verification_summary_*.json")):
        vlabel=s.stem.rsplit("_",1)[-1]; d=vdir/f"verification_detail_{vlabel}.csv"; g=vdir/f"verification_groups_{vlabel}.csv"
        if d.exists() and g.exists(): import_verification(d,g,s,db)
    print(f"每日流水线完成，最新候选已写入 MySQL：{count} 只")

if __name__ == "__main__": main()
