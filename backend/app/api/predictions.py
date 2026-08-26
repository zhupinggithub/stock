from fastapi import APIRouter,Depends,HTTPException,Query
from backend.app.services.auth_service import require_permission
from backend.app.repositories.query_repository import fetch_all,fetch_one

router=APIRouter(prefix="/predictions",tags=["predictions"],dependencies=[Depends(require_permission("prediction:view"))])

@router.get("")
def runs():return fetch_all("""SELECT id,base_date,model_code,model_version,top_n,backtest_trade_days,
 backtest_sample_count,backtest_up_rate,backtest_avg_return,market_avg_return,excess_return,created_at
 FROM prediction_run ORDER BY base_date DESC,id DESC""")

def _run(run_id:int)->dict:
    value=fetch_one("SELECT id,model_code,base_date,top_n FROM prediction_run WHERE id=:id",{"id":run_id})
    if not value:raise HTTPException(404,"预测批次不存在")
    return value

def _recent_runs(run:dict,limit:int=10)->list[dict]:
    return fetch_all(f"""SELECT id,base_date FROM prediction_run WHERE model_code=:model
      AND (base_date<:base OR (base_date=:base AND id<=:id)) ORDER BY base_date DESC,id DESC LIMIT {int(limit)}""",
      {"model":run["model_code"],"base":run["base_date"],"id":run["id"]})

def _trend(current:int,previous:int|None,history:list[int])->str:
    if previous is None:return "新记录"
    change=previous-current
    if len(history)>=3 and all(history[i]<history[i+1] for i in range(len(history)-1)):return "持续增强"
    if len(history)>=3 and all(history[i]>history[i+1] for i in range(len(history)-1)):return "持续减弱"
    if change>=50:return "快速增强"
    if change<=-50:return "快速减弱"
    if current<=50 and previous<=50:return "高位稳定"
    if current<=30<previous:return "进入Top30"
    return "小幅波动"

@router.get("/ranking-history")
def ranking_history(model_code:str,stock_code:str,limit:int=Query(30,ge=1,le=250)):
    return fetch_all("""SELECT pr.id prediction_run_id,pr.base_date,psr.full_ranking,psr.ranking_percentile,
      psr.score,psr.up_probability,psr.expected_return,psr.is_candidate,psr.candidate_ranking
      FROM prediction_stock_rank psr JOIN prediction_run pr ON pr.id=psr.prediction_run_id
      JOIN stock_master sm ON sm.id=psr.stock_id WHERE pr.model_code=:model AND sm.stock_code=:code
      ORDER BY pr.base_date DESC,pr.id DESC LIMIT :limit""",{"model":model_code,"code":stock_code,"limit":limit})

@router.get("/{run_id}/candidates")
def candidates(run_id:int):
    run=_run(run_id);data=fetch_all("""SELECT pc.id,pc.stock_id,pc.ranking,sm.stock_code,sm.stock_name,sm.market,pc.score,pc.base_close,
      pc.daily_return,pc.return_5d,pc.volume_ratio_20,pc.avg_amount_20,pc.volatility_10,
      pc.up_probability,pc.expected_return,pc.return_low_90,pc.return_high_90,
      pc.target_price,pc.price_low_90,pc.price_high_90,pc.prediction_confidence
      FROM prediction_candidate pc JOIN stock_master sm ON sm.id=pc.stock_id
      WHERE pc.prediction_run_id=:id ORDER BY pc.ranking""",{"id":run_id})
    recent=_recent_runs(run);run_ids=[value["id"] for value in recent]
    candidate_history=fetch_all("""SELECT pc.prediction_run_id,pc.stock_id,pc.ranking,pc.up_probability
      FROM prediction_candidate pc JOIN (SELECT id FROM prediction_run WHERE model_code=:model
      AND (base_date<:base OR (base_date=:base AND id<=:id)) ORDER BY base_date DESC,id DESC LIMIT 10) recent ON recent.id=pc.prediction_run_id""",
      {"model":run["model_code"],"base":run["base_date"],"id":run_id})
    full_history=fetch_all("""SELECT psr.prediction_run_id,psr.stock_id,psr.full_ranking FROM prediction_stock_rank psr
      JOIN (SELECT id FROM prediction_run WHERE model_code=:model AND (base_date<:base OR (base_date=:base AND id<=:id))
      ORDER BY base_date DESC,id DESC LIMIT 10) recent ON recent.id=psr.prediction_run_id""",
      {"model":run["model_code"],"base":run["base_date"],"id":run_id})
    candidates_by_run={value:{} for value in run_ids};ranks_by_run={value:{} for value in run_ids}
    for value in candidate_history:candidates_by_run[value["prediction_run_id"]][value["stock_id"]]=value
    for value in full_history:ranks_by_run[value["prediction_run_id"]][value["stock_id"]]=value["full_ranking"]
    previous_id=run_ids[1] if len(run_ids)>1 else None
    for row in data:
        row["model_code"]=run["model_code"];stock=row["stock_id"];appearances=[stock in candidates_by_run[value] for value in run_ids];streak=0
        for appeared in appearances:
            if not appeared:break
            streak+=1
        previous=candidates_by_run.get(previous_id,{}).get(stock) if previous_id else None
        row.update({"consecutive_count":streak,"recent_5_count":sum(appearances[:5]),"recent_5_periods":min(5,len(appearances)),"recent_10_count":sum(appearances),"recent_10_periods":len(appearances),"previous_ranking":previous["ranking"] if previous else None,"ranking_change":previous["ranking"]-row["ranking"] if previous else None,"previous_probability":previous["up_probability"] if previous else None,"probability_change":row["up_probability"]-previous["up_probability"] if previous and row["up_probability"] is not None and previous["up_probability"] is not None else None})
        rank_values=[ranks_by_run[value][stock] for value in run_ids if stock in ranks_by_run[value]]
        current_full=ranks_by_run.get(run_id,{}).get(stock);previous_full=ranks_by_run.get(previous_id,{}).get(stock) if previous_id else None
        top50=top100=0
        for value in run_ids:
            rank=ranks_by_run[value].get(stock)
            if rank is not None and rank<=50:top50+=1
            else:break
        for value in run_ids:
            rank=ranks_by_run[value].get(stock)
            if rank is not None and rank<=100:top100+=1
            else:break
        row.update({"full_ranking":current_full,"previous_full_ranking":previous_full,"full_ranking_change":previous_full-current_full if current_full and previous_full else None,"consecutive_top_50":top50,"consecutive_top_100":top100,"ranking_trend":_trend(current_full,previous_full,rank_values[:3]) if current_full else None})
    factors=fetch_all("""SELECT factor_code,factor_name,mean_ic,positive_ic_rate,valid_trade_days,model_weight
      FROM prediction_factor WHERE prediction_run_id=:id ORDER BY ABS(model_weight) DESC""",{"id":run_id})
    return {"candidates":data,"factors":factors,"has_full_ranking":bool(full_history)}

@router.get("/{run_id}/rankings")
def rankings(run_id:int,page:int=Query(1,ge=1),page_size:int=Query(50,ge=10,le=200),keyword:str="",market:str="",rank_min:int|None=None,rank_max:int|None=None,probability_min:float|None=None,candidate_only:bool=False,sort:str="full_ranking",order:str="asc"):
    run=_run(run_id);where=["psr.prediction_run_id=:run"];params={"run":run_id,"limit":page_size,"offset":(page-1)*page_size}
    previous=fetch_one("""SELECT pr.id FROM prediction_run pr WHERE pr.model_code=:model AND pr.base_date<:base
      AND EXISTS(SELECT 1 FROM prediction_stock_rank x WHERE x.prediction_run_id=pr.id) ORDER BY pr.base_date DESC,pr.id DESC LIMIT 1""",{"model":run["model_code"],"base":run["base_date"]});params["previous_run"]=previous.get("id",0)
    if keyword:where.append("(sm.stock_code LIKE :keyword OR sm.stock_name LIKE :keyword)");params["keyword"]=f"%{keyword}%"
    if market in ("SH","SZ","BJ"):where.append("sm.market=:market");params["market"]=market
    if rank_min is not None:where.append("psr.full_ranking>=:rank_min");params["rank_min"]=rank_min
    if rank_max is not None:where.append("psr.full_ranking<=:rank_max");params["rank_max"]=rank_max
    if probability_min is not None:where.append("psr.up_probability>=:probability");params["probability"]=probability_min
    if candidate_only:where.append("psr.is_candidate=1")
    clause=" AND ".join(where);sorts={"full_ranking":"psr.full_ranking","score":"psr.score","up_probability":"psr.up_probability","expected_return":"psr.expected_return"};sort_sql=sorts.get(sort,"psr.full_ranking");direction="DESC" if order.lower()=="desc" else "ASC"
    total=fetch_one(f"SELECT COUNT(*) total FROM prediction_stock_rank psr JOIN stock_master sm ON sm.id=psr.stock_id WHERE {clause}",params)["total"]
    items=fetch_all(f"""SELECT psr.id,sm.stock_code,sm.stock_name,sm.market,psr.full_ranking,prev.full_ranking previous_full_ranking,
      (prev.full_ranking-psr.full_ranking) full_ranking_change,psr.ranking_percentile,psr.score,
      psr.up_probability,psr.expected_return,psr.return_low_90,psr.return_high_90,psr.is_candidate,psr.candidate_ranking,
      psr.daily_return,psr.return_5d,psr.volume_ratio_20,psr.avg_amount_20,psr.volatility_10
      FROM prediction_stock_rank psr JOIN stock_master sm ON sm.id=psr.stock_id
      LEFT JOIN prediction_stock_rank prev ON prev.prediction_run_id=:previous_run AND prev.stock_id=psr.stock_id WHERE {clause}
      ORDER BY {sort_sql} {direction},psr.full_ranking ASC LIMIT :limit OFFSET :offset""",params)
    for item in items:item["model_code"]=run["model_code"];item["ranking_trend"]=_trend(item["full_ranking"],item["previous_full_ranking"],[item["full_ranking"],item["previous_full_ranking"]] if item["previous_full_ranking"] else [])
    return {"items":items,"total":total,"page":page,"pages":max(1,(total+page_size-1)//page_size),"has_data":total>0,"model_code":run["model_code"],"base_date":run["base_date"]}
