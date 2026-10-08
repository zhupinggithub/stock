from datetime import datetime
from pathlib import Path
import pandas as pd
from fastapi import APIRouter,Depends,HTTPException
from backend.app.services.auth_service import require_permission
from backend.app.repositories.query_repository import fetch_all

router=APIRouter(prefix="/intraday",tags=["intraday"],dependencies=[Depends(require_permission("intraday:view"))])
ROOT=Path(__file__).resolve().parents[3]
LIMIT_UP_OUTPUT=ROOT/"data"/"predictions"/"limit_up"
INTRADAY_OUTPUT=ROOT/"data"/"predictions"/"intraday"

def _latest_limit_up_files():
    rankings=sorted(LIMIT_UP_OUTPUT.glob("limit_up_rankings_*.csv"));snapshots=sorted(INTRADAY_OUTPUT.glob("intraday_snapshot_*.csv"))
    return (rankings[-1],snapshots[-1]) if rankings and snapshots else None

def _limit_up_run():
    files=_latest_limit_up_files()
    if not files:return None
    ranking,snapshot=files;label=ranking.stem.removeprefix("limit_up_rankings_")
    return {"id":"limit-up","observed_at":datetime.fromtimestamp(snapshot.stat().st_mtime).isoformat(timespec="seconds"),"data_source":"实时快照","base_date":f"{label[:4]}-{label[4:6]}-{label[6:]}","model_code":"limit_up_intraday","model_version":"1.0.0"}

@router.get("")
def runs():
    values=fetch_all("""SELECT ir.id,ir.observed_at,ir.data_source,ir.candidate_count,ir.valid_candidate_count,
 ir.market_stock_count,ir.market_avg_return,ir.market_up_rate,ir.score_rank_ic,pr.base_date,pr.model_code,pr.model_version
 FROM intraday_run ir JOIN prediction_run pr ON pr.id=ir.prediction_run_id ORDER BY ir.observed_at DESC""")
    limit_up=_limit_up_run()
    if limit_up:values.insert(0,limit_up)
    return values

@router.get("/limit-up")
def limit_up_detail():
    files=_latest_limit_up_files()
    if not files:raise HTTPException(404,"暂无涨停预测盘中数据，请先执行涨停概率预测和获取盘中观察")
    ranking_path,snapshot_path=files
    ranking=pd.read_csv(ranking_path,dtype={"股票代码":str});ranking=ranking[ranking["is_candidate"].astype(str).str.lower().isin(("true","1"))].copy()
    snapshot=pd.read_csv(snapshot_path,dtype={"代码":str});snapshot["股票代码"]=snapshot["代码"].astype(str).str.extract(r"(\d{6})$",expand=False)
    detail=ranking.merge(snapshot,on="股票代码",how="left",suffixes=("","_实时"))
    detail["current_return"]=detail["最新价"]/detail["收盘"]-1;detail["distance_to_limit"]=detail["最新价"]/detail["next_limit_price"]-1
    detail["touched"]=detail["最高"]>=detail["next_limit_price"]-0.001;detail["sealed"]=detail["最新价"]>=detail["next_limit_price"]-0.001;detail["broken"]=detail["touched"]&~detail["sealed"]
    market_return=pd.to_numeric(snapshot["涨跌幅"],errors="coerce").mean()/100;detail["market_excess"]=detail["current_return"]-market_return
    records=[]
    for _,row in detail.sort_values("ranking").iterrows():
        item={"ranking":row["ranking"],"stock_code":row["股票代码"],"stock_name":row["名称"],"market":"SH" if row["股票代码"].startswith("6") else "SZ","score":row["score"],"touch_probability":row["touch_probability"],"seal_probability":row["seal_probability"],"previous_close":row["收盘"],"limit_price":row["next_limit_price"],"current_price":row.get("最新价"),"current_return":row.get("current_return"),"market_excess":row.get("market_excess"),"distance_to_limit":row.get("distance_to_limit"),"touched":bool(row["touched"]),"sealed":bool(row["sealed"]),"broken":bool(row["broken"])}
        records.append({key:(None if pd.isna(value) else value) for key,value in item.items()})
    groups=[]
    for top_n in sorted({min(n,len(detail)) for n in (5,10,20,30) if len(detail)}):
        selected=detail.head(top_n);valid=selected[selected["current_return"].notna()]
        groups.append({"top_n":top_n,"valid_count":len(valid),"up_rate":float((valid["current_return"]>0).mean()) if len(valid) else None,"avg_return":float(valid["current_return"].mean()) if len(valid) else None,"market_avg_return":market_return,"excess_return":float(valid["current_return"].mean()-market_return) if len(valid) else None,"touch_count":int(valid["touched"].sum()),"seal_count":int(valid["sealed"].sum()),"broken_count":int(valid["broken"].sum())})
    return {"groups":groups,"detail":records}

@router.get("/{run_id}")
def detail(run_id:int):
    groups=fetch_all("SELECT * FROM intraday_group_result WHERE intraday_run_id=:id ORDER BY top_n",{"id":run_id})
    values=fetch_all("""SELECT pc.ranking,sm.stock_code,sm.stock_name,sm.market,pc.score,ic.current_price,ic.previous_close,
      ic.current_return,ic.market_excess,ic.is_up FROM intraday_candidate ic
      JOIN prediction_candidate pc ON pc.id=ic.candidate_id JOIN stock_master sm ON sm.id=pc.stock_id
      WHERE ic.intraday_run_id=:id ORDER BY pc.ranking""",{"id":run_id})
    if not groups and not values: raise HTTPException(404,"盘中批次不存在")
    return {"groups":groups,"detail":values}
