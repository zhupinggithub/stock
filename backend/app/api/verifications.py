from fastapi import APIRouter,HTTPException
from backend.app.repositories.query_repository import fetch_all

router=APIRouter(prefix="/verifications",tags=["verifications"])

@router.get("")
def runs(): return fetch_all("""SELECT vr.id,pr.base_date,pr.model_code,pr.model_version,vr.actual_trade_date,vr.candidate_count,vr.verified_count,
 vr.unverified_count,vr.market_stock_count,vr.market_avg_return,vr.market_up_rate,vr.score_rank_ic,vr.verified_at
 FROM verification_run vr JOIN prediction_run pr ON pr.id=vr.prediction_run_id ORDER BY vr.actual_trade_date DESC""")

@router.get("/{run_id}")
def detail(run_id:int):
    groups=fetch_all("SELECT * FROM verification_group_result WHERE verification_run_id=:id ORDER BY top_n",{"id":run_id})
    values=fetch_all("""SELECT pc.ranking,sm.stock_code,sm.stock_name,sm.market,pc.score,vd.base_close,vd.actual_close,
      vd.actual_return,vd.market_excess,vd.is_up,vd.verified FROM verification_detail vd
      JOIN prediction_candidate pc ON pc.id=vd.candidate_id JOIN stock_master sm ON sm.id=pc.stock_id
      WHERE vd.verification_run_id=:id ORDER BY pc.ranking""",{"id":run_id})
    if not groups and not values: raise HTTPException(404,"验证批次不存在")
    return {"groups":groups,"detail":values}
