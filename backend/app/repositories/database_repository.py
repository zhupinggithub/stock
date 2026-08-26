"""MySQL persistence for market, prediction, intraday and verification files."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from backend.app.config import settings

FACTOR_COLUMNS = {
    "因子分位_1日动量": "ret_1", "因子分位_3日动量": "ret_3", "因子分位_5日动量": "ret_5",
    "因子分位_均线趋势(MA5/MA20)": "trend_5_20", "因子分位_量比(当日/20日)": "volume_ratio_20",
    "因子分位_成交额比(当日/20日)": "amount_ratio_20", "因子分位_20日价格位置": "position_20",
    "因子分位_10日波动率": "volatility_10", "因子分位_开盘缺口": "gap",
}

def engine() -> Engine:
    return create_engine(
        f"mysql+pymysql://{settings.db_user}:{settings.db_password}@{settings.db_host}:"
        f"{settings.db_port}/{settings.db_name}?charset=utf8mb4", pool_pre_ping=True
    )

def init_schema(db: Engine | None = None) -> None:
    db = db or engine()
    sql = (Path(__file__).parents[2] / "migrations" / "schema.sql").read_text(encoding="utf-8")
    with db.begin() as conn:
        for statement in sql.split(";"):
            if statement.strip(): conn.execute(text(statement))
        existing={row[0] for row in conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='prediction_candidate'"))}
        additions={
            "up_probability":"DECIMAL(14,10)","expected_return":"DECIMAL(14,10)",
            "return_low_90":"DECIMAL(14,10)","return_high_90":"DECIMAL(14,10)",
            "target_price":"DECIMAL(12,4)","price_low_90":"DECIMAL(12,4)","price_high_90":"DECIMAL(12,4)",
            "prediction_confidence":"DECIMAL(14,10)",
        }
        for column,column_type in additions.items():
            if column not in existing: conn.execute(text(f"ALTER TABLE prediction_candidate ADD COLUMN {column} {column_type} NULL"))

def clean(value: Any) -> Any:
    return None if pd.isna(value) else value

def normalize_code(value: Any) -> str:
    digits = re.sub(r"\D", "", str(value).replace(".0", ""))
    return digits.zfill(6)

def market_for(code: str) -> str:
    return "BJ" if code.startswith(("4", "8", "920")) else ("SH" if code.startswith(("5", "6", "9")) else "SZ")

def upsert_stocks(rows: list[dict[str, Any]], conn) -> dict[str, int]:
    values = []
    for row in rows:
        code = normalize_code(row.get("股票代码", row.get("代码")))
        name = str(row.get("名称", ""))
        market = market_for(code)
        values.append({"code": code, "market": market, "name": name, "full": market.lower() + code, "st": int("ST" in name.upper())})
    if values:
        conn.execute(text("""INSERT INTO stock_master(stock_code,market,stock_name,full_code,is_st) VALUES
          (:code,:market,:name,:full,:st) ON DUPLICATE KEY UPDATE stock_name=VALUES(stock_name),market=VALUES(market),full_code=VALUES(full_code),is_st=VALUES(is_st),is_active=1"""), values)
    codes = sorted({v["code"] for v in values})
    if not codes: return {}
    result = conn.execute(text("SELECT id,stock_code FROM stock_master WHERE stock_code IN :codes").bindparams(codes=tuple(codes)))
    return {row.stock_code: row.id for row in result}

def import_stock_list(list_path: Path, db: Engine | None = None) -> int:
    if not list_path.exists(): return 0
    frame=pd.read_csv(list_path,dtype={"代码":str})
    with (db or engine()).begin() as conn: upsert_stocks(frame.to_dict("records"),conn)
    return len(frame)

def import_market_data(data_dir: Path, db: Engine | None = None) -> int:
    db = db or engine(); files = sorted(data_dir.glob("a_stock_daily*.csv")) + sorted(data_dir.glob("daily_increment_*.csv"))
    frames = [pd.read_csv(f, dtype={"股票代码": str}) for f in files]
    if not frames: return 0
    frame = pd.concat(frames, ignore_index=True).drop_duplicates(["股票代码", "日期"], keep="last")
    records = frame.to_dict("records")
    with db.begin() as conn:
        ids = upsert_stocks(records, conn)
        sql = text("""INSERT INTO stock_daily(stock_id,trade_date,open_price,close_price,high_price,low_price,volume,amount,amplitude_pct,change_pct,change_amount,turnover_pct,data_source)
          VALUES(:stock_id,:date,:open,:close,:high,:low,:volume,:amount,:amplitude,:change_pct,:change_amount,:turnover,'file')
          ON DUPLICATE KEY UPDATE open_price=VALUES(open_price),close_price=VALUES(close_price),high_price=VALUES(high_price),low_price=VALUES(low_price),volume=VALUES(volume),amount=VALUES(amount),amplitude_pct=VALUES(amplitude_pct),change_pct=VALUES(change_pct),change_amount=VALUES(change_amount),turnover_pct=VALUES(turnover_pct),updated_at=CURRENT_TIMESTAMP""")
        batch=[]
        for r in records:
            code=normalize_code(r["股票代码"])
            batch.append({"stock_id":ids[code],"date":r["日期"],"open":clean(r.get("开盘")),"close":clean(r.get("收盘")),"high":clean(r.get("最高")),"low":clean(r.get("最低")),"volume":clean(r.get("成交量")),"amount":clean(r.get("成交额")),"amplitude":clean(r.get("振幅")),"change_pct":clean(r.get("涨跌幅")),"change_amount":clean(r.get("涨跌额")),"turnover":clean(r.get("换手率"))})
            if len(batch)>=2000: conn.execute(sql,batch); batch=[]
        if batch: conn.execute(sql,batch)
    return len(records)

def import_prediction(candidate_path: Path, factor_path: Path, summary_path: Path, db: Engine | None = None) -> int:
    db=db or engine(); candidates=pd.read_csv(candidate_path,dtype={"股票代码":str}); factors=pd.read_csv(factor_path); summary=json.loads(summary_path.read_text(encoding="utf-8")); base=str(candidates.iloc[0]["预测基准日"])
    model_code=summary.get("模型代码","multi_factor_rank"); model_version=summary.get("模型版本","1.0.0")
    with db.begin() as conn:
        ids=upsert_stocks(candidates.to_dict("records"),conn)
        conn.execute(text("""INSERT INTO prediction_run(model_code,model_version,base_date,top_n,backtest_trade_days,backtest_sample_count,backtest_up_rate,backtest_avg_return,market_avg_return,excess_return)
          VALUES(:model,:version,:base,:top,:days,:samples,:up,:avg,:market,:excess)
          ON DUPLICATE KEY UPDATE top_n=VALUES(top_n),backtest_trade_days=VALUES(backtest_trade_days),backtest_sample_count=VALUES(backtest_sample_count),backtest_up_rate=VALUES(backtest_up_rate),backtest_avg_return=VALUES(backtest_avg_return),market_avg_return=VALUES(market_avg_return),excess_return=VALUES(excess_return)"""),
          {"model":model_code,"version":model_version,"base":base,"top":len(candidates),"days":summary.get("样本内检验交易日"),"samples":summary.get("候选样本数"),"up":summary.get("候选次日上涨比例"),"avg":summary.get("候选平均次日收益"),"market":summary.get("全市场平均次日收益"),"excess":summary.get("候选相对收益")})
        run_id=conn.execute(text("SELECT id FROM prediction_run WHERE model_code=:model AND model_version=:version AND base_date=:base"),{"model":model_code,"version":model_version,"base":base}).scalar_one()
        conn.execute(text("DELETE FROM prediction_factor WHERE prediction_run_id=:id"),{"id":run_id})
        for _,r in factors.iterrows(): conn.execute(text("INSERT INTO prediction_factor(prediction_run_id,factor_code,factor_name,mean_ic,positive_ic_rate,valid_trade_days,model_weight) VALUES(:run,:code,:name,:ic,:positive,:days,:weight)"),{"run":run_id,"code":r["因子"],"name":r["含义"],"ic":clean(r["平均IC"]),"positive":clean(r["IC为正比例"]),"days":int(r["有效交易日"]),"weight":clean(r["模型权重"])})
        for rank,(_,r) in enumerate(candidates.iterrows(),1):
            code=normalize_code(r["股票代码"]); conn.execute(text("""INSERT INTO prediction_candidate(prediction_run_id,stock_id,ranking,score,base_close,daily_return,return_5d,volume_ratio_20,avg_amount_20,volatility_10,up_probability,expected_return,return_low_90,return_high_90,target_price,price_low_90,price_high_90,prediction_confidence)
              VALUES(:run,:stock,:rank,:score,:close,:daily,:r5,:vr,:amount,:vol,:prob,:expected,:ret_low,:ret_high,:target,:price_low,:price_high,:confidence)
              ON DUPLICATE KEY UPDATE ranking=VALUES(ranking),score=VALUES(score),base_close=VALUES(base_close),daily_return=VALUES(daily_return),return_5d=VALUES(return_5d),volume_ratio_20=VALUES(volume_ratio_20),avg_amount_20=VALUES(avg_amount_20),volatility_10=VALUES(volatility_10),up_probability=VALUES(up_probability),expected_return=VALUES(expected_return),return_low_90=VALUES(return_low_90),return_high_90=VALUES(return_high_90),target_price=VALUES(target_price),price_low_90=VALUES(price_low_90),price_high_90=VALUES(price_high_90),prediction_confidence=VALUES(prediction_confidence)"""),{"run":run_id,"stock":ids[code],"rank":rank,"score":clean(r["综合评分"]),"close":clean(r["收盘"]),"daily":clean(r["当日涨跌幅"])/100,"r5":clean(r["近5日涨跌幅"])/100,"vr":clean(r["量比20日"]),"amount":clean(r["近20日平均成交额"]),"vol":clean(r["波动率10日"]),"prob":clean(r.get("上涨概率")),"expected":clean(r.get("预计次日收益")),"ret_low":clean(r.get("预计收益下限90")),"ret_high":clean(r.get("预计收益上限90")),"target":clean(r.get("预计目标价格")),"price_low":clean(r.get("预计价格下限90")),"price_high":clean(r.get("预计价格上限90")),"confidence":clean(r.get("预测置信度"))}); cid=conn.execute(text("SELECT id FROM prediction_candidate WHERE prediction_run_id=:run AND stock_id=:stock"),{"run":run_id,"stock":ids[code]}).scalar_one()
            vals=[{"cid":cid,"code":code_,"value":clean(r.get(col))} for col,code_ in FACTOR_COLUMNS.items()]
            conn.execute(text("INSERT INTO candidate_factor(candidate_id,factor_code,percentile) VALUES(:cid,:code,:value) ON DUPLICATE KEY UPDATE percentile=VALUES(percentile)"),vals)
    return len(candidates)

def import_intraday(detail_path: Path, group_path: Path, summary_path: Path, db: Engine | None = None) -> int:
    db=db or engine(); detail=pd.read_csv(detail_path,dtype={"股票代码":str}); groups=pd.read_csv(group_path); s=json.loads(summary_path.read_text(encoding="utf-8")); base=s["预测基准日"]
    with db.begin() as conn:
        run=conn.execute(text("SELECT id FROM prediction_run WHERE base_date=:base AND model_code=:model ORDER BY id DESC LIMIT 1"),{"base":base,"model":s.get("模型代码","multi_factor_rank")}).scalar_one()
        conn.execute(text("""INSERT INTO intraday_run(prediction_run_id,observed_at,data_source,candidate_count,valid_candidate_count,market_stock_count,market_avg_return,market_up_rate,score_rank_ic) VALUES(:run,:at,:source,:count,:valid,:market_count,:market,:up,:ic) ON DUPLICATE KEY UPDATE id=LAST_INSERT_ID(id),market_avg_return=VALUES(market_avg_return),market_up_rate=VALUES(market_up_rate),score_rank_ic=VALUES(score_rank_ic)"""),{"run":run,"at":s["观察时间"],"source":s["行情来源"],"count":s["候选总数"],"valid":s["有效候选数"],"market_count":s["全市场有效股票数"],"market":s["全市场当前平均涨跌幅"],"up":s["全市场当前上涨比例"],"ic":s["评分与盘中收益RankIC"]}); intraday_id=conn.execute(text("SELECT id FROM intraday_run WHERE prediction_run_id=:run AND observed_at=:at"),{"run":run,"at":s["观察时间"]}).scalar_one()
        conn.execute(text("DELETE FROM intraday_candidate WHERE intraday_run_id=:id"),{"id":intraday_id}); conn.execute(text("DELETE FROM intraday_group_result WHERE intraday_run_id=:id"),{"id":intraday_id})
        for _,r in detail.iterrows():
            cid=conn.execute(text("SELECT pc.id FROM prediction_candidate pc JOIN stock_master sm ON sm.id=pc.stock_id WHERE pc.prediction_run_id=:run AND sm.stock_code=:code"),{"run":run,"code":normalize_code(r["股票代码"])}).scalar_one()
            conn.execute(text("INSERT INTO intraday_candidate(intraday_run_id,candidate_id,current_price,previous_close,current_return,market_excess,is_up) VALUES(:ir,:cid,:price,:prev,:ret,:excess,:up)"),{"ir":intraday_id,"cid":cid,"price":clean(r.get("盘中最新价")),"prev":clean(r.get("参考价",r.get("昨收"))),"ret":clean(r.get("预测期内盘中收益")),"excess":clean(r.get("当前相对全市场")),"up":None if pd.isna(r.get("当前是否上涨")) else int(bool(r.get("当前是否上涨")))})
        for _,r in groups.iterrows(): conn.execute(text("INSERT INTO intraday_group_result(intraday_run_id,top_n,candidate_count,valid_count,up_count,down_count,flat_count,up_rate,avg_return,median_return,best_return,worst_return,market_avg_return,excess_return) VALUES(:id,:top,:count,:valid,:upc,:down,:flat,:rate,:avg,:median,:best,:worst,:market,:excess)"),{"id":intraday_id,"top":int(r["TopN"]),"count":int(r["候选数"]),"valid":int(r["有效数"]),"upc":int(r.get("当前上涨数",0)),"down":int(r.get("当前下跌数",0)),"flat":int(r.get("当前平盘数",0)),"rate":clean(r.get("当前上涨比例")),"avg":clean(r.get("当前平均收益")),"median":clean(r.get("当前中位收益")),"best":clean(r.get("当前最好收益")),"worst":clean(r.get("当前最差收益")),"market":clean(r.get("全市场当前平均涨跌幅")),"excess":clean(r.get("当前相对全市场收益"))})
    return len(detail)

def import_verification(detail_path: Path, group_path: Path, summary_path: Path, db: Engine | None = None) -> int:
    db=db or engine(); detail=pd.read_csv(detail_path,dtype={"股票代码":str}); groups=pd.read_csv(group_path); s=json.loads(summary_path.read_text(encoding="utf-8"))
    with db.begin() as conn:
        run=conn.execute(text("SELECT id FROM prediction_run WHERE base_date=:base AND model_code=:model ORDER BY id DESC LIMIT 1"),{"base":s["预测基准日"],"model":s.get("模型代码","multi_factor_rank")}).scalar_one()
        conn.execute(text("""INSERT INTO verification_run(prediction_run_id,actual_trade_date,candidate_count,verified_count,unverified_count,market_stock_count,market_avg_return,market_up_rate,score_rank_ic)
          VALUES(:run,:date,:count,:verified,:missing,:market_count,:market,:up,:ic)
          ON DUPLICATE KEY UPDATE id=LAST_INSERT_ID(id),candidate_count=VALUES(candidate_count),verified_count=VALUES(verified_count),unverified_count=VALUES(unverified_count),market_stock_count=VALUES(market_stock_count),market_avg_return=VALUES(market_avg_return),market_up_rate=VALUES(market_up_rate),score_rank_ic=VALUES(score_rank_ic),verified_at=CURRENT_TIMESTAMP"""),{"run":run,"date":s["实际交易日"],"count":s["候选总数"],"verified":s["已验证候选数"],"missing":s["未验证候选数"],"market_count":s["全市场可比较股票数"],"market":s["全市场平均收益"],"up":s["全市场上涨比例"],"ic":s["评分与实际收益RankIC"]})
        verification_id=conn.execute(text("SELECT id FROM verification_run WHERE prediction_run_id=:run AND actual_trade_date=:date"),{"run":run,"date":s["实际交易日"]}).scalar_one()
        conn.execute(text("DELETE FROM verification_detail WHERE verification_run_id=:id"),{"id":verification_id}); conn.execute(text("DELETE FROM verification_group_result WHERE verification_run_id=:id"),{"id":verification_id})
        for _,r in detail.iterrows():
            cid=conn.execute(text("SELECT pc.id FROM prediction_candidate pc JOIN stock_master sm ON sm.id=pc.stock_id WHERE pc.prediction_run_id=:run AND sm.stock_code=:code"),{"run":run,"code":normalize_code(r["股票代码"])}).scalar_one()
            actual=clean(r.get("实际次日收益")); conn.execute(text("INSERT INTO verification_detail(verification_run_id,candidate_id,base_close,actual_close,actual_return,market_excess,is_up,verified) VALUES(:vr,:cid,:base,:actual_close,:ret,:excess,:up,:verified)"),{"vr":verification_id,"cid":cid,"base":clean(r.get("基准收盘")),"actual_close":clean(r.get("实际次日收盘")),"ret":actual,"excess":clean(r.get("相对全市场收益")),"up":None if actual is None else int(actual>0),"verified":int(actual is not None)})
        for _,r in groups.iterrows(): conn.execute(text("INSERT INTO verification_group_result(verification_run_id,top_n,candidate_count,verified_count,up_count,down_count,flat_count,up_rate,avg_return,median_return,best_return,worst_return,market_avg_return,excess_return) VALUES(:id,:top,:count,:verified,:upc,:down,:flat,:rate,:avg,:median,:best,:worst,:market,:excess)"),{"id":verification_id,"top":int(r["TopN"]),"count":int(r["候选数"]),"verified":int(r["已验证数"]),"upc":int(r.get("上涨数量",0)),"down":int(r.get("下跌数量",0)),"flat":int(r.get("平盘数量",0)),"rate":clean(r.get("上涨比例")),"avg":clean(r.get("平均收益")),"median":clean(r.get("中位收益")),"best":clean(r.get("最好收益")),"worst":clean(r.get("最差收益")),"market":clean(r.get("全市场平均收益")),"excess":clean(r.get("相对全市场收益"))})
    return len(detail)
