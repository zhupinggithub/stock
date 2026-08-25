from fastapi import APIRouter,HTTPException,Query
from backend.app.repositories.query_repository import fetch_all

router=APIRouter(prefix="/stocks",tags=["stocks"])

@router.get("")
def stocks(q:str="",market:str="",page:int=Query(1,ge=1),page_size:int=Query(20,ge=5,le=100),
           min_up_streak:int=Query(0,ge=0,le=100),min_down_streak:int=Query(0,ge=0,le=100),
           min_change_pct:float|None=None,max_change_pct:float|None=None):
    where=["1=1"];params={"limit":page_size,"offset":(page-1)*page_size}
    if q: where.append("(stock_code LIKE :q OR stock_name LIKE :q)");params["q"]=f"%{q}%"
    if market: where.append("market=:market");params["market"]=market.upper()
    if min_up_streak: where.append("up_streak>=:min_up");params["min_up"]=min_up_streak
    if min_down_streak: where.append("down_streak>=:min_down");params["min_down"]=min_down_streak
    if min_change_pct is not None: where.append("latest_change_pct>=:min_pct");params["min_pct"]=min_change_pct
    if max_change_pct is not None: where.append("latest_change_pct<=:max_pct");params["max_pct"]=max_change_pct
    cte="""WITH ranked AS (SELECT sd.*,ROW_NUMBER() OVER(PARTITION BY stock_id ORDER BY trade_date DESC) rn FROM stock_daily sd),
    metrics AS (SELECT stock_id,COUNT(*) daily_count,MAX(CASE WHEN rn=1 THEN trade_date END) latest_date,
      MAX(CASE WHEN rn=1 THEN close_price END) latest_close,MAX(CASE WHEN rn=1 THEN change_pct END) latest_change_pct,
      CASE WHEN MAX(CASE WHEN rn=1 AND change_pct>0 THEN 1 ELSE 0 END)=0 THEN 0 ELSE COALESCE(MIN(CASE WHEN change_pct<=0 THEN rn END)-1,COUNT(*)) END up_streak,
      CASE WHEN MAX(CASE WHEN rn=1 AND change_pct<0 THEN 1 ELSE 0 END)=0 THEN 0 ELSE COALESCE(MIN(CASE WHEN change_pct>=0 THEN rn END)-1,COUNT(*)) END down_streak
      FROM ranked GROUP BY stock_id), universe AS (SELECT sm.stock_code,sm.stock_name,sm.market,sm.is_st,m.* FROM stock_master sm LEFT JOIN metrics m ON m.stock_id=sm.id) """
    total=fetch_all(cte+f"SELECT COUNT(*) total FROM universe WHERE {' AND '.join(where)}",params)[0]["total"]
    values=fetch_all(cte+f"""SELECT stock_code,stock_name,market,is_st,latest_date,latest_close,latest_change_pct,
      COALESCE(up_streak,0) up_streak,COALESCE(down_streak,0) down_streak,COALESCE(daily_count,0) daily_count
      FROM universe WHERE {' AND '.join(where)} ORDER BY stock_code LIMIT :limit OFFSET :offset""",params)
    return {"items":values,"page":page,"page_size":page_size,"total":total,"pages":max(1,(total+page_size-1)//page_size)}

@router.get("/{stock_code}/daily")
def daily(stock_code:str,limit:int=Query(120,ge=1,le=1000)):
    values=fetch_all("""SELECT sd.trade_date,sd.open_price,sd.close_price,sd.high_price,sd.low_price,sd.volume,
      sd.amount,sd.change_pct,sd.turnover_pct FROM stock_daily sd JOIN stock_master sm ON sm.id=sd.stock_id
      WHERE sm.stock_code=:code ORDER BY sd.trade_date DESC LIMIT :limit""",{"code":stock_code,"limit":limit})[::-1]
    if not values: raise HTTPException(404,"股票或行情不存在")
    return values
