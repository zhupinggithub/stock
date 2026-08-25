from fastapi import APIRouter,HTTPException
from backend.app.repositories.query_repository import fetch_all

router=APIRouter(prefix="/intraday",tags=["intraday"])

@router.get("")
def runs(): return fetch_all("""SELECT ir.id,ir.observed_at,ir.data_source,ir.candidate_count,ir.valid_candidate_count,
 ir.market_stock_count,ir.market_avg_return,ir.market_up_rate,ir.score_rank_ic,pr.base_date
 FROM intraday_run ir JOIN prediction_run pr ON pr.id=ir.prediction_run_id ORDER BY ir.observed_at DESC""")

@router.get("/{run_id}")
def detail(run_id:int):
    groups=fetch_all("SELECT * FROM intraday_group_result WHERE intraday_run_id=:id ORDER BY top_n",{"id":run_id})
    values=fetch_all("""SELECT pc.ranking,sm.stock_code,sm.stock_name,sm.market,pc.score,ic.current_price,ic.previous_close,
      ic.current_return,ic.market_excess,ic.is_up FROM intraday_candidate ic
      JOIN prediction_candidate pc ON pc.id=ic.candidate_id JOIN stock_master sm ON sm.id=pc.stock_id
      WHERE ic.intraday_run_id=:id ORDER BY pc.ranking""",{"id":run_id})
    if not groups and not values: raise HTTPException(404,"盘中批次不存在")
    return {"groups":groups,"detail":values}
