from fastapi import APIRouter,Depends,HTTPException
from backend.app.services.auth_service import require_permission
from backend.app.repositories.query_repository import fetch_all,fetch_one

router=APIRouter(prefix="/predictions",tags=["predictions"],dependencies=[Depends(require_permission("prediction:view"))])

@router.get("")
def runs(): return fetch_all("""SELECT id,base_date,model_code,model_version,top_n,backtest_trade_days,
 backtest_sample_count,backtest_up_rate,backtest_avg_return,market_avg_return,excess_return,created_at
 FROM prediction_run ORDER BY base_date DESC,id DESC""")

@router.get("/{run_id}/candidates")
def candidates(run_id:int):
    run=fetch_one("SELECT id,model_code,base_date FROM prediction_run WHERE id=:id",{"id":run_id})
    if not run: raise HTTPException(404,"预测批次不存在")
    data=fetch_all("""SELECT pc.id,pc.stock_id,pc.ranking,sm.stock_code,sm.stock_name,sm.market,pc.score,pc.base_close,
      pc.daily_return,pc.return_5d,pc.volume_ratio_20,pc.avg_amount_20,pc.volatility_10,
      pc.up_probability,pc.expected_return,pc.return_low_90,pc.return_high_90,
      pc.target_price,pc.price_low_90,pc.price_high_90,pc.prediction_confidence
      FROM prediction_candidate pc JOIN stock_master sm ON sm.id=pc.stock_id
      WHERE pc.prediction_run_id=:id ORDER BY pc.ranking""",{"id":run_id})
    recent_runs=fetch_all("""SELECT id,base_date FROM prediction_run
      WHERE model_code=:model AND (base_date<:base OR (base_date=:base AND id<=:id))
      ORDER BY base_date DESC,id DESC LIMIT 10""",{"model":run["model_code"],"base":run["base_date"],"id":run_id})
    run_ids=[value["id"] for value in recent_runs]
    history=fetch_all("""SELECT pc.prediction_run_id,pc.stock_id,pc.ranking,pc.up_probability
      FROM prediction_candidate pc JOIN (SELECT id FROM prediction_run
        WHERE model_code=:model AND (base_date<:base OR (base_date=:base AND id<=:id))
        ORDER BY base_date DESC,id DESC LIMIT 10) recent ON recent.id=pc.prediction_run_id""",
      {"model":run["model_code"],"base":run["base_date"],"id":run_id}) if run_ids else []
    by_run={value["id"]:{} for value in recent_runs}
    for value in history:by_run[value["prediction_run_id"]][value["stock_id"]]=value
    previous_id=run_ids[1] if len(run_ids)>1 else None
    for row in data:
        stock_id=row["stock_id"]
        appearances=[stock_id in by_run[value] for value in run_ids]
        streak=0
        for appeared in appearances:
            if not appeared:break
            streak+=1
        previous=by_run.get(previous_id,{}).get(stock_id) if previous_id else None
        row["consecutive_count"]=streak
        row["recent_5_count"]=sum(appearances[:5]);row["recent_5_periods"]=min(5,len(appearances))
        row["recent_10_count"]=sum(appearances[:10]);row["recent_10_periods"]=min(10,len(appearances))
        row["previous_ranking"]=previous["ranking"] if previous else None
        row["ranking_change"]=(previous["ranking"]-row["ranking"]) if previous else None
        row["previous_probability"]=previous["up_probability"] if previous else None
        row["probability_change"]=(row["up_probability"]-previous["up_probability"]) if previous and row["up_probability"] is not None and previous["up_probability"] is not None else None
    factors=fetch_all("""SELECT factor_code,factor_name,mean_ic,positive_ic_rate,valid_trade_days,model_weight
      FROM prediction_factor WHERE prediction_run_id=:id ORDER BY ABS(model_weight) DESC""",{"id":run_id})
    return {"candidates":data,"factors":factors}
