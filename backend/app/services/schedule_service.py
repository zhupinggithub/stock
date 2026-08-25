from __future__ import annotations

from datetime import date, datetime, time, timedelta
from threading import Event, Lock, Thread

from sqlalchemy import text

from backend.app.database import engine
from backend.app.services.job_service import _resolve_data_dir,submit_job

STOP=Event(); START_LOCK=Lock(); THREAD:Thread|None=None

def _weekdays(value:str)->set[int]:
    return {int(item) for item in value.split(",") if item.strip()}

def _as_time(value:time|timedelta)->time:
    if isinstance(value,time): return value
    seconds=int(value.total_seconds())%86400
    return time(seconds//3600,(seconds%3600)//60,seconds%60)

def next_run(schedule:dict,now:datetime|None=None)->datetime|None:
    if not schedule.get("enabled"): return None
    now=now or datetime.now(); run_time=_as_time(schedule["run_time"]); days=_weekdays(schedule["weekdays"])
    for offset in range(8):
        day=now.date()+timedelta(days=offset)
        if day.isoweekday() not in days: continue
        candidate=datetime.combine(day,run_time)
        if candidate>now or (offset==0 and schedule.get("last_trigger_date")!=day): return candidate
    return None

def get_schedule()->dict:
    with engine().connect() as conn:
        row=conn.execute(text("SELECT * FROM task_schedule WHERE id=1")).mappings().one()
    value=dict(row); value["run_time"]=_as_time(value["run_time"]); value["next_run_at"]=next_run(value); return value

def update_schedule(enabled:bool,run_time,weekdays:list[int],data_dir:str,source:str,top:int)->dict:
    _resolve_data_dir(data_dir)
    encoded=",".join(str(value) for value in sorted(set(weekdays)))
    with engine().begin() as conn:
        conn.execute(text("""UPDATE task_schedule SET enabled=:enabled,run_time=:run_time,weekdays=:weekdays,
          data_dir=:data_dir,data_source=:source,top_n=:top WHERE id=1"""),{"enabled":int(enabled),"run_time":run_time,"weekdays":encoded,"data_dir":data_dir,"source":source,"top":top})
    return get_schedule()

def _tick()->None:
    schedule=get_schedule(); now=datetime.now(); today=date.today()
    if not schedule["enabled"] or today.isoweekday() not in _weekdays(schedule["weekdays"]): return
    if now.time()<schedule["run_time"] or schedule["last_trigger_date"]==today: return
    try: job_id=submit_job("pipeline",schedule["data_dir"],schedule["data_source"],schedule["top_n"])
    except RuntimeError: return
    with engine().begin() as conn:
        conn.execute(text("UPDATE task_schedule SET last_trigger_date=:today,last_job_id=:job WHERE id=1"),{"today":today,"job":job_id})

def _loop()->None:
    while not STOP.wait(15):
        try: _tick()
        except Exception: pass

def start_scheduler()->None:
    global THREAD
    with START_LOCK:
        if THREAD and THREAD.is_alive(): return
        STOP.clear(); THREAD=Thread(target=_loop,name="stock-scheduler",daemon=True); THREAD.start()

def stop_scheduler()->None:
    STOP.set()
