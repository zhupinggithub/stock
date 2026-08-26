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
    if not fetch_one("SELECT id FROM prediction_run WHERE id=:id",{"id":run_id}): raise HTTPException(404,"预测批次不存在")
    data=fetch_all("""SELECT pc.id,pc.ranking,sm.stock_code,sm.stock_name,sm.market,pc.score,pc.base_close,
      pc.daily_return,pc.return_5d,pc.volume_ratio_20,pc.avg_amount_20,pc.volatility_10,
      pc.up_probability,pc.expected_return,pc.return_low_90,pc.return_high_90,
      pc.target_price,pc.price_low_90,pc.price_high_90,pc.prediction_confidence
      FROM prediction_candidate pc JOIN stock_master sm ON sm.id=pc.stock_id
      WHERE pc.prediction_run_id=:id ORDER BY pc.ranking""",{"id":run_id})
    factors=fetch_all("""SELECT factor_code,factor_name,mean_ic,positive_ic_rate,valid_trade_days,model_weight
      FROM prediction_factor WHERE prediction_run_id=:id ORDER BY ABS(model_weight) DESC""",{"id":run_id})
    return {"candidates":data,"factors":factors}
