import json
from datetime import datetime
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from backend.app.services.auth_service import require_permission

ROOT = Path(__file__).resolve().parents[3]
OUTPUT = ROOT / "data" / "predictions" / "limit_up"
INTRADAY_OUTPUT = ROOT / "data" / "predictions" / "intraday"
router = APIRouter(prefix="/limit-up", tags=["limit-up"], dependencies=[Depends(require_permission("prediction:view"))])

@router.get("")
def runs():
    result=[]
    for path in sorted(OUTPUT.glob("limit_up_summary_*.json"), reverse=True):
        value=json.loads(path.read_text(encoding="utf-8"))
        result.append({key:value.get(key) for key in ("base_date","model_version","scope","top_n","universe_count")})
    return result

@router.get("/{label}")
def detail(label:str,candidates_only:bool=True,limit:int=Query(100,ge=1,le=1000)):
    if not label.isdigit() or len(label)!=8: raise HTTPException(422,"日期标签格式不正确")
    summary_path=OUTPUT/f"limit_up_summary_{label}.json";ranking_path=OUTPUT/f"limit_up_rankings_{label}.csv"
    if not summary_path.exists() or not ranking_path.exists(): raise HTTPException(404,"涨停预测批次不存在")
    summary=json.loads(summary_path.read_text(encoding="utf-8"));frame=pd.read_csv(ranking_path,dtype={"股票代码":str})
    if candidates_only: frame=frame[frame["is_candidate"].astype(str).str.lower().isin(("true","1"))]
    frame=frame.head(limit)
    rename={"日期":"base_date","股票代码":"stock_code","名称":"stock_name","收盘":"close","next_limit_price":"limit_price","ret_1":"daily_return","ret_5":"return_5d"}
    columns=["日期","股票代码","名称","ranking","score","收盘","next_limit_price","touch_probability","seal_probability","is_candidate","ret_1","ret_5","amount_ratio_20","volume_ratio_20","turnover","return_rank_change","amount_rank_change","market_up_rate","market_limit_rate"]
    records=frame[columns].rename(columns=rename).to_dict("records")
    latest_ranking=max(OUTPUT.glob('limit_up_rankings_*.csv'),default=None)
    latest_snapshot=max(INTRADAY_OUTPUT.glob('intraday_snapshot_*.csv'),default=None)
    observed_at=None
    if ranking_path==latest_ranking and latest_snapshot:
        snapshot=pd.read_csv(latest_snapshot,dtype={'代码':str})
        snapshot['stock_code']=snapshot['代码'].astype(str).str.extract(r'(\d{6})$',expand=False)
        quotes=snapshot.set_index('stock_code')
        observed_at=datetime.fromtimestamp(latest_snapshot.stat().st_mtime).isoformat(timespec='seconds')
        for row in records:
            quote=quotes.loc[row['stock_code']] if row['stock_code'] in quotes.index else None
            row['current_price']=None if quote is None else quote.get('最新价')
            change_pct=None if quote is None else quote.get('涨跌幅')
            row['current_change_pct']=None if pd.isna(change_pct) else float(change_pct)/100
    for row in records:
        for key,value in list(row.items()):
            if pd.isna(value): row[key]=None
    verification_summary_path=OUTPUT/f"limit_up_verification_{label}.json"
    verification_detail_path=OUTPUT/f"limit_up_verification_{label}.csv"
    verification=None
    if verification_summary_path.exists() and verification_detail_path.exists():
        verification=json.loads(verification_summary_path.read_text(encoding="utf-8"))
        detail_frame=pd.read_csv(verification_detail_path,dtype={"stock_code":str})
        verification["items"]=detail_frame.where(pd.notna(detail_frame),None).to_dict("records")
        for item in verification["items"]:
            for key,value in list(item.items()):
                if pd.isna(value): item[key]=None
    return {"summary":summary,"items":records,"verification":verification,"intraday_observed_at":observed_at}
