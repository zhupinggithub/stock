"""Isolated walk-forward experiment for T+1 rank/amount challenger.

This script is read-only against MySQL and never imports experimental results into
production prediction tables.
"""
from __future__ import annotations
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
import pandas as pd
from sqlalchemy import text
from backend.app.database import engine
from backend.app.predictors.multi_factor import CODE,DATE,NAME,FEATURES,add_features,estimate_factor_weights

META_FEATURES=["base_rank","rank_change_1","rank_change_3","amount_level","amount_accel_3","amount_persist_3"]

def load_data():
    sql=text("""SELECT sd.trade_date 日期,sm.stock_code 股票代码,sm.stock_name 名称,sd.open_price 开盘,
      sd.close_price 收盘,sd.high_price 最高,sd.low_price 最低,sd.volume 成交量,sd.amount 成交额,
      sd.turnover_pct 换手率 FROM stock_daily sd JOIN stock_master sm ON sm.id=sd.stock_id ORDER BY sm.stock_code,sd.trade_date""")
    with engine().connect() as conn:data=pd.read_sql_query(sql.text,conn.connection)
    data[DATE]=pd.to_datetime(data[DATE]);data[CODE]=data[CODE].astype(str).str.zfill(6)
    for c in ["开盘","收盘","最高","最低","成交量","成交额","换手率"]:data[c]=pd.to_numeric(data[c],errors="coerce")
    return data

def eligible(day,min_history,min_amount):
    return day[(day.history_count>=min_history)&(day.amount_ma20>=min_amount)&(~day[NAME].astype(str).str.upper().str.contains("ST",na=False))].copy()

def factor_score(day,weights):
    score=pd.Series(0.0,index=day.index)
    for feature,weight in weights.items():score+=(day[feature].rank(pct=True).fillna(.5)-.5)*weight
    return score

def meta_weights(train):
    dates=sorted(train.loc[train.tradeable_return.notna(),DATE].unique())[-10:];sample=train[train[DATE].isin(dates)]
    raw={}
    target=sample.groupby(DATE).tradeable_return.rank(pct=True)
    for feature in META_FEATURES:
        fr=sample.groupby(DATE)[feature].rank(pct=True);pairs=pd.DataFrame({DATE:sample[DATE],"x":fr,"y":target}).dropna()
        ics=[g.x.corr(g.y) for _,g in pairs.groupby(DATE) if len(g)>=100]
        raw[feature]=float(np.nanmean(ics)) if ics else 0.0
    denominator=sum(abs(v) for v in raw.values())
    return ({k:v/denominator for k,v in raw.items()} if denominator>1e-12 else None),raw,len(dates)

def metrics(values,market,cost):
    a=np.asarray(values,float);m=np.asarray(market,float);net=a-cost
    return {"samples":int(len(a)),"up_rate":float(np.mean(a>0)),"avg_return":float(np.mean(a)),"median_return":float(np.median(a)),"market_avg_return":float(np.mean(m)),"avg_excess":float(np.mean(a-m)),"net_avg_return":float(np.mean(net)),"worst":float(np.min(a)),"best":float(np.max(a))}

def run(output:Path,top:int=30,min_history:int=25,min_amount:float=20_000_000,cost:float=.0015):
    featured=add_features(load_data());g=featured.groupby(CODE,sort=False)
    featured["amount_accel_3"]=featured.amount_ratio_20-g.amount_ratio_20.shift(3)
    featured["amount_persist_3"]=g.amount_ratio_20.transform(lambda s:s.rolling(3,min_periods=3).mean())
    dates=sorted(featured[DATE].unique());snapshots=[]
    for i,day_value in enumerate(dates):
        if i<2:continue
        cutoff=dates[i-2];known=featured[featured[DATE]<=cutoff]
        if known.loc[known.tradeable_return.notna(),DATE].nunique()<5:continue
        try:weights,_=estimate_factor_weights(known,20,"tradeable_return")
        except RuntimeError:continue
        day=eligible(featured[featured[DATE]==day_value],min_history,min_amount)
        if len(day)<100:continue
        day["base_score"]=factor_score(day,weights);day["base_rank"]=day.base_score.rank(pct=True)
        day["amount_level"]=day.amount_ratio_20
        snapshots.append(day[[DATE,CODE,NAME,"tradeable_return","base_score","base_rank","amount_level","amount_accel_3","amount_persist_3"]])
    if not snapshots:raise RuntimeError("没有足够数据生成实验快照")
    panel=pd.concat(snapshots).sort_values([CODE,DATE]);pg=panel.groupby(CODE,sort=False)
    panel["rank_change_1"]=panel.base_rank-pg.base_rank.shift(1);panel["rank_change_3"]=panel.base_rank-pg.base_rank.shift(3)
    panel=panel.sort_values([DATE,CODE]);daily=[];base_returns=[];challenge_returns=[];markets=[];overlaps=[];blend_returns={"blend_10":[],"blend_20":[],"blend_30":[]};blend_overlaps={key:[] for key in blend_returns}
    for i,day_value in enumerate(sorted(panel[DATE].unique())):
        day=panel[panel[DATE]==day_value].dropna(subset=META_FEATURES+["tradeable_return"]).copy()
        if len(day)<100:continue
        all_dates=dates;di=all_dates.index(day_value)
        if di<2:continue
        cutoff=all_dates[di-2];train=panel[(panel[DATE]<=cutoff)&panel.tradeable_return.notna()].dropna(subset=META_FEATURES)
        if train[DATE].nunique()<5:continue
        weights,raw,train_days=meta_weights(train)
        if not weights:continue
        challenge=pd.Series(0.0,index=day.index)
        for feature,weight in weights.items():challenge+=(day[feature].rank(pct=True).fillna(.5)-.5)*weight
        day["challenge_score"]=challenge
        extra_weights={k:v for k,v in weights.items() if k!="base_rank"};extra_den=sum(abs(v) for v in extra_weights.values()) or 1
        overlay=pd.Series(0.0,index=day.index)
        for feature,weight in extra_weights.items():overlay+=(day[feature].rank(pct=True).fillna(.5)-.5)*(weight/extra_den)
        day["overlay_rank"]=overlay.rank(pct=True)
        for alpha in (.1,.2,.3):day[f"blend_{int(alpha*100)}"]=(1-alpha)*day.base_rank+alpha*day.overlay_rank
        base=day.nlargest(top,"base_score");chall=day.nlargest(top,"challenge_score");market=float(day.tradeable_return.mean())
        br=base.tradeable_return.to_numpy(float);cr=chall.tradeable_return.to_numpy(float)
        overlap=len(set(base[CODE])&set(chall[CODE]))/top
        base_returns.extend(br);challenge_returns.extend(cr);markets.extend([market]*top);overlaps.append(overlap)
        for key in blend_returns:
            selected=day.nlargest(top,key);blend_returns[key].extend(selected.tradeable_return.to_numpy(float));blend_overlaps[key].append(len(set(base[CODE])&set(selected[CODE]))/top)
        daily.append({"signal_date":str(pd.Timestamp(day_value).date()),"train_meta_days":train_days,"universe":len(day),"baseline_avg":float(br.mean()),"challenger_avg":float(cr.mean()),"market_avg":market,"baseline_excess":float(br.mean()-market),"challenger_excess":float(cr.mean()-market),"challenger_minus_baseline":float(cr.mean()-br.mean()),"top30_overlap":overlap,"meta_weights":json.dumps(weights,ensure_ascii=False)})
    if not daily:raise RuntimeError("排名趋势历史不足，无法形成挑战模型样本外日期")
    report={"method":"strict_walk_forward","target":"T+1开盘买入至T+2开盘卖出","production_changed":False,"data":{"first_date":str(featured[DATE].min().date()),"last_date":str(featured[DATE].max().date()),"trade_days":int(featured[DATE].nunique()),"stocks":int(featured[CODE].nunique()),"evaluation_days":len(daily)},"assumed_round_trip_cost":cost,"baseline":metrics(base_returns,markets,cost),"challenger":metrics(challenge_returns,markets,cost),"paired":{"challenger_better_days":int(sum(x["challenger_minus_baseline"]>0 for x in daily)),"baseline_better_days":int(sum(x["challenger_minus_baseline"]<0 for x in daily)),"avg_daily_difference":float(np.mean([x["challenger_minus_baseline"] for x in daily])),"avg_top30_overlap":float(np.mean(overlaps))},"blends":{key:{**metrics(values,markets,cost),"avg_top30_overlap":float(np.mean(blend_overlaps[key]))} for key,values in blend_returns.items()},"features":META_FEATURES,"warning":"历史仅47个交易日，结果属于低置信度探索实验"}
    output.mkdir(parents=True,exist_ok=True);pd.DataFrame(daily).to_csv(output/"t1_rank_amount_daily.csv",index=False,encoding="utf-8-sig");(output/"t1_rank_amount_report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False,indent=2));return report

def main():
    p=argparse.ArgumentParser();p.add_argument("--output",type=Path,default=Path("data/experiments/t1_rank_amount"));p.add_argument("--top",type=int,default=30);args=p.parse_args();run(args.output,args.top)
if __name__=="__main__":main()