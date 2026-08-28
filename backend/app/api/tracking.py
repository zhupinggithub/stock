from __future__ import annotations
from collections import defaultdict
from datetime import date,datetime
from fastapi import APIRouter,Depends,HTTPException,Request
from pydantic import BaseModel,Field
from sqlalchemy import text
from backend.app.repositories.query_repository import fetch_all,fetch_one
from backend.app.database import engine
from backend.app.services.auth_service import audit,current_auth,require_permission

router=APIRouter(prefix="/tracking",tags=["tracking"],dependencies=[Depends(require_permission("prediction:view"))])
MODEL_CODE="tradeable_t1_open"

class PositionBody(BaseModel):
    stock_code:str
    buy_date:date
    buy_price:float=Field(gt=0)
    quantity:float=Field(gt=0)
    status:str="open"
    sell_date:date|None=None
    sell_price:float|None=Field(default=None,gt=0)
    note:str|None=Field(default=None,max_length=500)
    source_candidate_id:int|None=None

def _csrf(request:Request,user:dict):
    if request.headers.get("x-csrf-token")!=user["csrf_token"]:raise HTTPException(403,"安全令牌无效")

def _validate_position(body:PositionBody):
    if body.status not in ("open","closed"):raise HTTPException(422,"持仓状态无效")
    if body.status=="closed" and (not body.sell_date or body.sell_price is None):raise HTTPException(422,"平仓时必须填写卖出日期和卖出价格")
    if body.sell_date and body.sell_date<body.buy_date:raise HTTPException(422,"卖出日期不能早于买入日期")

def _day(value):
    if not value:return None
    return date.fromisoformat(str(value)[:10])

def _round(value,digits=4):
    return None if value is None else round(float(value),digits)

@router.get("")
def runs():
    return fetch_all("""SELECT pr.id,pr.base_date,pr.model_version,pr.top_n,COUNT(pc.id) candidate_count
      FROM prediction_run pr LEFT JOIN prediction_candidate pc ON pc.prediction_run_id=pr.id
      WHERE pr.model_code=:model AND pr.status='success'
      GROUP BY pr.id,pr.base_date,pr.model_version,pr.top_n ORDER BY pr.base_date DESC,pr.id DESC LIMIT 60""",{"model":MODEL_CODE})

@router.get("/positions")
def positions(user:dict=Depends(current_auth)):
    values=fetch_all("""SELECT ap.id,ap.source_candidate_id,ap.buy_date,ap.buy_price,ap.quantity,ap.status,ap.sell_date,ap.sell_price,ap.note,
      ap.created_at,ap.updated_at,sm.stock_code,sm.stock_name,sm.market,
      (SELECT sd.trade_date FROM stock_daily sd WHERE sd.stock_id=ap.stock_id ORDER BY sd.trade_date DESC LIMIT 1) latest_date,
      (SELECT sd.close_price FROM stock_daily sd WHERE sd.stock_id=ap.stock_id ORDER BY sd.trade_date DESC LIMIT 1) latest_close
      FROM actual_position ap JOIN stock_master sm ON sm.id=ap.stock_id WHERE ap.user_id=:uid ORDER BY ap.status,ap.buy_date DESC,ap.id DESC""",{"uid":user["id"]})
    for row in values:
        valuation=row["sell_price"] if row["status"]=="closed" else row["latest_close"]
        row["valuation_price"]=valuation
        row["return_rate"]=None if valuation is None else float(valuation)/float(row["buy_price"])-1
        row["profit_amount"]=None if valuation is None else (float(valuation)-float(row["buy_price"]))*float(row["quantity"])
        row["market_value"]=None if valuation is None else float(valuation)*float(row["quantity"])
    return values

@router.post("/positions",status_code=201)
def add_position(body:PositionBody,request:Request,user:dict=Depends(current_auth)):
    _csrf(request,user);_validate_position(body)
    with engine().begin() as conn:
        stock=conn.execute(text("SELECT id FROM stock_master WHERE stock_code=:code"),{"code":body.stock_code.zfill(6)}).scalar()
        if not stock:raise HTTPException(404,"股票不存在")
        result=conn.execute(text("""INSERT INTO actual_position(user_id,stock_id,source_candidate_id,buy_date,buy_price,quantity,status,sell_date,sell_price,note)
          VALUES(:uid,:stock,:candidate,:buy_date,:buy_price,:quantity,:status,:sell_date,:sell_price,:note)"""),{"uid":user["id"],"stock":stock,"candidate":body.source_candidate_id,"buy_date":body.buy_date,"buy_price":body.buy_price,"quantity":body.quantity,"status":body.status,"sell_date":body.sell_date,"sell_price":body.sell_price,"note":body.note or None});position_id=int(result.lastrowid)
    audit("position.create",request,user,resource_type="position",resource_id=position_id,detail={"stock_code":body.stock_code});return {"id":position_id}

@router.put("/positions/{position_id}")
def edit_position(position_id:int,body:PositionBody,request:Request,user:dict=Depends(current_auth)):
    _csrf(request,user);_validate_position(body)
    with engine().begin() as conn:
        stock=conn.execute(text("SELECT id FROM stock_master WHERE stock_code=:code"),{"code":body.stock_code.zfill(6)}).scalar()
        if not stock:raise HTTPException(404,"股票不存在")
        result=conn.execute(text("""UPDATE actual_position SET stock_id=:stock,source_candidate_id=:candidate,buy_date=:buy_date,buy_price=:buy_price,quantity=:quantity,status=:status,sell_date=:sell_date,sell_price=:sell_price,note=:note
          WHERE id=:id AND user_id=:uid"""),{"id":position_id,"uid":user["id"],"stock":stock,"candidate":body.source_candidate_id,"buy_date":body.buy_date,"buy_price":body.buy_price,"quantity":body.quantity,"status":body.status,"sell_date":body.sell_date,"sell_price":body.sell_price,"note":body.note or None})
        if not result.rowcount:raise HTTPException(404,"持仓记录不存在")
    audit("position.update",request,user,resource_type="position",resource_id=position_id);return {"ok":True}

@router.delete("/positions/{position_id}")
def delete_position(position_id:int,request:Request,user:dict=Depends(current_auth)):
    _csrf(request,user)
    with engine().begin() as conn:
        result=conn.execute(text("DELETE FROM actual_position WHERE id=:id AND user_id=:uid"),{"id":position_id,"uid":user["id"]})
        if not result.rowcount:raise HTTPException(404,"持仓记录不存在")
    audit("position.delete",request,user,resource_type="position",resource_id=position_id);return {"ok":True}
@router.get("/{run_id}")
def detail(run_id:int):
    run=fetch_one("SELECT id,base_date,model_code,model_version FROM prediction_run WHERE id=:id",{"id":run_id})
    if not run or run["model_code"]!=MODEL_CODE:raise HTTPException(404,"T+1跟踪批次不存在")
    values=fetch_all("""SELECT pc.id candidate_id,pc.ranking,pc.score,pc.up_probability,pc.expected_return,pc.volatility_10,
      sm.stock_code,sm.stock_name,sm.market,sd.trade_date,sd.open_price,sd.close_price,sd.high_price,sd.low_price
      FROM prediction_candidate pc JOIN stock_master sm ON sm.id=pc.stock_id
      LEFT JOIN stock_daily sd ON sd.stock_id=pc.stock_id AND sd.trade_date>:base
      WHERE pc.prediction_run_id=:id ORDER BY pc.ranking,sd.trade_date""",{"id":run_id,"base":run["base_date"]})
    latest_intraday=fetch_one("SELECT id,observed_at FROM intraday_run WHERE prediction_run_id=:id ORDER BY observed_at DESC LIMIT 1",{"id":run_id})
    intraday={}
    if latest_intraday:
        intraday={row["candidate_id"]:row for row in fetch_all("SELECT candidate_id,current_price,previous_close FROM intraday_candidate WHERE intraday_run_id=:id",{"id":latest_intraday["id"]})}
    grouped=defaultdict(list);meta={}
    for row in values:
        cid=row["candidate_id"];meta[cid]=row
        if row["trade_date"]:grouped[cid].append(row)
    items=[]
    for cid,row in sorted(meta.items(),key=lambda item:item[1]["ranking"]):
        days=grouped[cid];entry=days[0] if days else None;snapshot=intraday.get(cid);observed_at=latest_intraday.get("observed_at") if latest_intraday else None
        entry_price=float(entry["open_price"]) if entry and entry["open_price"] else None;entry_date=entry["trade_date"] if entry else None
        if entry_price is None and snapshot and snapshot["previous_close"] is not None:
            entry_price=float(snapshot["previous_close"]);entry_date=_day(observed_at).isoformat()
        latest=days[-1] if days else None;current_price=float(latest["close_price"]) if latest and latest["close_price"] else None
        current_date=_day(latest["trade_date"]) if latest else None;price_source="收盘日线" if latest else None
        if snapshot and snapshot["current_price"] is not None and (not current_date or _day(observed_at)>=current_date):
            current_price=float(snapshot["current_price"]);current_date=_day(observed_at);price_source=f"盘中快照 {str(observed_at)[11:16]}"
        volatility=float(row["volatility_10"] or 0);risk_distance=min(.08,max(.025,volatility*1.5));risk_price=entry_price*(1-risk_distance) if entry_price else None
        expected=float(row["expected_return"]) if row["expected_return"] is not None else None
        target_price=entry_price*(1+expected) if entry_price and expected is not None and expected>0 else None
        highs=[float(day["high_price"]) for day in days if day["high_price"] is not None]
        if current_price is not None:highs.append(current_price)
        highest=max(highs) if highs else None;current_return=current_price/entry_price-1 if entry_price and current_price else None
        highest_return=highest/entry_price-1 if entry_price and highest else None;drawdown=current_price/highest-1 if current_price and highest else None
        holding_days=max(len(days),1 if entry_price else 0);sellable=holding_days>=2
        if not entry_price:status,level,reason="等待买入","waiting","尚未取得下一交易日开盘价"
        elif not sellable:status,level,reason="买入日观察","observe","T+1买入当日不可卖出，仅记录盘中表现"
        elif current_price is not None and current_price<=risk_price:status,level,reason="建议退出","exit",f"当前价跌破波动风险价 {risk_price:.2f}"
        elif target_price is not None and current_price is not None and current_price>=target_price:status,level,reason="建议止盈","take_profit",f"当前价达到模型目标价 {target_price:.2f}"
        elif holding_days>=3:status,level,reason="到期退出","exit",f"已达到最长持有 {holding_days} 个交易日"
        elif drawdown is not None and highest_return is not None and highest_return>=.02 and drawdown<=-risk_distance*.6:status,level,reason="注意回撤","warning",f"从持有期高点回撤 {abs(drawdown):.2%}"
        else:status,level,reason="继续持有","hold","未触发风险、目标或到期退出条件"
        items.append({"candidate_id":cid,"ranking":row["ranking"],"score":row["score"],"stock_code":row["stock_code"],"stock_name":row["stock_name"],"market":row["market"],"signal_date":run["base_date"],"entry_date":entry_date,"entry_price":_round(entry_price),"sellable_date":days[1]["trade_date"] if len(days)>1 else None,"current_date":current_date.isoformat() if current_date else None,"current_price":_round(current_price),"price_source":price_source,"current_return":_round(current_return,8),"highest_return":_round(highest_return,8),"drawdown":_round(drawdown,8),"target_price":_round(target_price),"risk_price":_round(risk_price),"holding_days":holding_days,"up_probability":row["up_probability"],"expected_return":row["expected_return"],"status":status,"status_level":level,"reason":reason})
    counts={key:sum(1 for row in items if row["status_level"]==key) for key in ("waiting","observe","hold","warning","take_profit","exit")}
    return {"run":run,"observed_at":latest_intraday.get("observed_at") if latest_intraday else None,"counts":counts,"items":items,"rules":{"entry":"信号后下一交易日开盘模拟买入","sellable":"买入后的下一交易日起允许卖出","risk":"1.5×10日波动率，限制在2.5%—8%","target":"买入价×(1+模型预计收益)，仅预计收益为正时显示","max_holding_days":3}}