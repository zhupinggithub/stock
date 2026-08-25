from fastapi import APIRouter
from backend.app.repositories.query_repository import fetch_all, fetch_one

router=APIRouter(prefix="/dashboard",tags=["dashboard"])

@router.get("")
def dashboard():
    stats=fetch_one("""SELECT (SELECT COUNT(*) FROM stock_master) stock_count,
      (SELECT COUNT(*) FROM stock_daily) daily_count,(SELECT MIN(trade_date) FROM stock_daily) first_date,
      (SELECT MAX(trade_date) FROM stock_daily) latest_date,(SELECT COUNT(*) FROM prediction_run) prediction_runs,
      (SELECT COUNT(*) FROM verification_run) verification_runs""")
    latest=fetch_one("""SELECT id,base_date,model_code,model_version,top_n,backtest_up_rate,
      backtest_avg_return,market_avg_return,excess_return FROM prediction_run ORDER BY base_date DESC,id DESC LIMIT 1""")
    groups=fetch_all("""SELECT g.top_n,g.up_rate,g.avg_return,g.market_avg_return,g.excess_return,r.observed_at
      FROM intraday_group_result g JOIN intraday_run r ON r.id=g.intraday_run_id
      WHERE r.id=(SELECT id FROM intraday_run ORDER BY observed_at DESC LIMIT 1) ORDER BY g.top_n""")
    market=fetch_all("""SELECT trade_date,AVG(change_pct)/100 avg_return,AVG(change_pct>0) up_rate
      FROM stock_daily GROUP BY trade_date ORDER BY trade_date DESC LIMIT 20""")[::-1]
    return {"stats":stats,"latest_prediction":latest,"latest_intraday_groups":groups,"market_history":market}
