"""Observe direction and executable T+1 candidates against one spot snapshot."""
from __future__ import annotations
import argparse,json
from datetime import datetime
from pathlib import Path
import numpy as np
import pandas as pd
from backend.app.collectors.market_fetcher import CODE_COLUMN,NAME_COLUMN,fetch_stock_list,normalize_code
from backend.app.predictors.multi_factor import CODE,NAME

MODELS={"direction":{"code":"multi_factor_rank","name":"次日方向模型","pattern":"next_day_candidates_*.csv","basis":"昨收","description":"信号日收盘至当前价"},"tradeable":{"code":"tradeable_t1_open","name":"T+1可交易模型","pattern":"tradeable_candidates_*.csv","basis":"今开","description":"当日开盘模拟买入至当前价（持仓浮盈亏）"}}

def latest_files(directory:Path,explicit:Path|None=None)->list[tuple[str,Path]]:
    if explicit:
        key="tradeable" if explicit.name.startswith("tradeable_") else "direction";return [(key,explicit)]
    result=[]
    for key,config in MODELS.items():
        files=sorted(directory.glob(config["pattern"]))
        if files: result.append((key,files[-1]))
    if not result: raise FileNotFoundError(f"没有找到候选文件：{directory}")
    return result

def normalize_spot(snapshot:pd.DataFrame)->pd.DataFrame:
    required={CODE_COLUMN,NAME_COLUMN,"最新价","涨跌幅","涨跌额","昨收","今开"};missing=required.difference(snapshot.columns)
    if missing: raise ValueError(f"实时列表缺少字段：{sorted(missing)}")
    rows=[]
    for _,row in snapshot.iterrows():
        try:
            code,_=normalize_code(row[CODE_COLUMN]);latest=float(row["最新价"]);previous=float(row["昨收"]);open_price=float(row["今开"])
            if min(latest,previous,open_price)<=0:continue
            rows.append({CODE:code,"实时名称":str(row[NAME_COLUMN]),"盘中最新价":latest,"昨收":previous,"今开":open_price,"盘中涨跌幅":float(row["涨跌幅"])/100,"开盘后收益":latest/open_price-1,"盘中涨跌额":float(row["涨跌额"])})
        except (TypeError,ValueError):continue
    if not rows:raise RuntimeError("实时列表没有可用行情")
    return pd.DataFrame(rows).drop_duplicates(CODE,keep="last")

def group_metrics(detail:pd.DataFrame,top_n:int,market_return:float)->dict[str,object]:
    selected=detail.head(top_n);valid=selected[selected["预测期内盘中收益"].notna()]
    if valid.empty:return {"TopN":top_n,"候选数":len(selected),"有效数":0}
    values=valid["预测期内盘中收益"];average=float(values.mean())
    return {"TopN":top_n,"候选数":len(selected),"有效数":len(valid),"当前上涨数":int((values>0).sum()),"当前下跌数":int((values<0).sum()),"当前平盘数":int((values==0).sum()),"当前上涨比例":float((values>0).mean()),"当前平均收益":average,"当前中位收益":float(values.median()),"当前最好收益":float(values.max()),"当前最差收益":float(values.min()),"全市场当前平均涨跌幅":market_return,"当前相对全市场收益":average-market_return}

def observe(key:str,path:Path,spot:pd.DataFrame,now:datetime,source:str,top_groups:list[int],output:Path)->None:
    config=MODELS[key];predictions=pd.read_csv(path,dtype={CODE:str});required={CODE,NAME,"综合评分","收盘","预测基准日"};missing=required.difference(predictions.columns)
    if missing:raise ValueError(f"{path.name} 缺少字段：{sorted(missing)}")
    predictions[CODE]=predictions[CODE].astype(str).str.replace(r"\.0$","",regex=True).str.zfill(6);predictions=predictions.sort_values("综合评分",ascending=False).drop_duplicates(CODE);predictions["预测排名"]=np.arange(1,len(predictions)+1)
    detail=predictions.merge(spot,on=CODE,how="left");detail["观察时间"]=now.isoformat(timespec="seconds");basis=config["basis"]
    detail["参考价"]=detail[basis];detail["预测期内盘中收益"]=detail["盘中最新价"]/detail["参考价"]-1;detail["当前是否上涨"]=detail["预测期内盘中收益"].map(lambda v:pd.NA if pd.isna(v) else bool(v>0))
    market_column="开盘后收益" if key=="tradeable" else "盘中涨跌幅";market_return=float(spot[market_column].mean());detail["当前相对全市场"]=detail["预测期内盘中收益"]-market_return
    valid=detail[detail["预测期内盘中收益"].notna()];rank_ic=valid["综合评分"].rank().corr(valid["预测期内盘中收益"].rank());groups=sorted({min(v,len(detail)) for v in top_groups});metrics=[group_metrics(detail,v,market_return) for v in groups]
    summary={"状态":"盘中临时观察，非正式验证","模型代码":config["code"],"模型名称":config["name"],"收益口径":config["description"],"候选文件":path.name,"预测基准日":str(predictions.iloc[0]["预测基准日"]),"观察时间":now.isoformat(timespec="seconds"),"行情来源":source,"候选总数":len(detail),"有效候选数":len(valid),"全市场有效股票数":len(spot),"全市场当前平均涨跌幅":market_return,"全市场当前上涨比例":float((spot[market_column]>0).mean()),"评分与盘中收益RankIC":None if pd.isna(rank_ic) else float(rank_ic),"分组结果":metrics,"说明":"盘中价格仍会变化；T+1模型结果是不可当日卖出的持仓浮盈亏"}
    stamp=now.strftime("%Y%m%d_%H%M%S");suffix=f"{key}_{stamp}";detail.to_csv(output/f"intraday_detail_{suffix}.csv",index=False,encoding="utf-8-sig");pd.DataFrame(metrics).to_csv(output/f"intraday_groups_{suffix}.csv",index=False,encoding="utf-8-sig");(output/f"intraday_summary_{suffix}.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    top=metrics[-1];print(f"{config['name']}：Top{top['TopN']} 上涨比例={top.get('当前上涨比例',0):.2%}，平均收益={top.get('当前平均收益',0):.2%}")

def main()->None:
    p=argparse.ArgumentParser(description="观察两套预测模型的盘中表现");p.add_argument("--data-dir",type=Path,required=True);p.add_argument("--prediction-file",type=Path);p.add_argument("--source",choices=("auto","eastmoney","sina"),default="sina");p.add_argument("--retries",type=int,default=3);p.add_argument("--top-groups",default="5,10,20,30");args=p.parse_args();groups=[int(v) for v in args.top_groups.split(",") if v.strip()]
    predictions=args.data_dir/"predictions";files=latest_files(predictions,args.prediction_file);now=datetime.now();stamp=now.strftime("%Y%m%d_%H%M%S");output=predictions/"intraday";output.mkdir(parents=True,exist_ok=True)
    snapshot_path=fetch_stock_list(output,retries=args.retries,source=args.source,reuse_on_error=False,filename=f"intraday_snapshot_{stamp}.csv");spot=normalize_spot(pd.read_csv(snapshot_path,dtype={CODE_COLUMN:str}))
    for key,path in files:observe(key,path,spot,now,args.source,groups,output)

if __name__=="__main__":main()
