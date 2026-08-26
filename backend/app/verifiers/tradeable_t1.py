"""Verify the executable A-share T+1 model: next open entry, following open exit."""
from __future__ import annotations
import argparse,json
from pathlib import Path
import numpy as np
import pandas as pd
from backend.app.predictors.multi_factor import CODE,DATE,NAME,load_market_data
from backend.app.verifiers.next_day import calculate_group_metrics,prediction_date_from_file,safe_float

def verify_one(path:Path,market:pd.DataFrame,output:Path,top_groups:list[int]):
    predictions=pd.read_csv(path,dtype={CODE:str}); predictions[CODE]=predictions[CODE].astype(str).str.replace(r"\.0$","",regex=True).str.zfill(6)
    predictions=predictions.sort_values("综合评分",ascending=False).drop_duplicates(CODE); predictions["预测排名"]=np.arange(1,len(predictions)+1)
    base_date=prediction_date_from_file(path,predictions); later=sorted(market.loc[market[DATE]>base_date,DATE].unique())
    if len(later)<2: return "pending",{"预测基准日":base_date.strftime("%Y-%m-%d")}
    entry_date=pd.Timestamp(later[0]); exit_date=pd.Timestamp(later[1]); label=base_date.strftime("%Y%m%d")
    entry=market[market[DATE]==entry_date][[CODE,"开盘"]].rename(columns={"开盘":"基准收盘"})
    exit_=market[market[DATE]==exit_date][[CODE,"开盘"]].rename(columns={"开盘":"实际次日收盘"})
    pair=entry.merge(exit_,on=CODE); pair["实际次日收益"]=pair["实际次日收盘"]/pair["基准收盘"]-1
    benchmark=float(pair["实际次日收益"].mean()); detail=predictions.merge(pair,on=CODE,how="left")
    detail["预测基准日"]=base_date.strftime("%Y-%m-%d"); detail["实际交易日"]=exit_date.strftime("%Y-%m-%d"); detail["是否上涨"]=detail["实际次日收益"].map(lambda v:pd.NA if pd.isna(v) else bool(v>0)); detail["相对全市场收益"]=detail["实际次日收益"]-benchmark
    verified=detail[detail["实际次日收益"].notna()]; rank_ic=verified["综合评分"].rank().corr(verified["实际次日收益"].rank())
    groups=sorted({min(v,len(detail)) for v in top_groups if v>0}); metrics=[calculate_group_metrics(detail,benchmark,v) for v in groups]
    summary={"模型代码":"tradeable_t1_open","模型名称":"T+1可交易模型","预测文件":path.name,"预测基准日":base_date.strftime("%Y-%m-%d"),"模拟买入日":entry_date.strftime("%Y-%m-%d"),"实际交易日":exit_date.strftime("%Y-%m-%d"),"收益口径":"下一交易日开盘买入，再下一交易日开盘卖出","候选总数":len(detail),"已验证候选数":len(verified),"未验证候选数":int(detail["实际次日收益"].isna().sum()),"全市场可比较股票数":len(pair),"全市场平均收益":benchmark,"全市场上涨比例":float((pair["实际次日收益"]>0).mean()),"评分与实际收益RankIC":safe_float(rank_ic),"分组结果":metrics}
    output.mkdir(parents=True,exist_ok=True); detail.to_csv(output/f"tradeable_verification_detail_{label}.csv",index=False,encoding="utf-8-sig"); pd.DataFrame(metrics).to_csv(output/f"tradeable_verification_groups_{label}.csv",index=False,encoding="utf-8-sig"); (output/f"tradeable_verification_summary_{label}.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    return "verified",summary

def main():
    p=argparse.ArgumentParser(description="验证T+1可交易模型");p.add_argument("--data-dir",type=Path,required=True);p.add_argument("--top-groups",default="5,10,20,30");args=p.parse_args()
    pred=args.data_dir/"predictions"; files=sorted(pred.glob("tradeable_candidates_*.csv")); market=load_market_data(args.data_dir); output=pred/"verification"; verified=pending=0
    for path in files:
        status,summary=verify_one(path,market,output,[int(v) for v in args.top_groups.split(",")]); verified+=status=="verified";pending+=status=="pending"
    print(f"T+1可交易验证：完成 {verified} 个，等待行情 {pending} 个")
