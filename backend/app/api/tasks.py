from fastapi import APIRouter,Depends,HTTPException,Query,Request
from backend.app.repositories.query_repository import fetch_all,fetch_one
from backend.app.schemas.jobs import JobCreate,ScheduleUpdate
from backend.app.services.job_service import submit_job
from backend.app.services.schedule_service import get_schedule,update_schedule
from backend.app.services.auth_service import audit,require_permission

router=APIRouter(prefix="/tasks",tags=["tasks"])

@router.get("")
def jobs(limit:int=Query(30,ge=1,le=200),_:dict=Depends(require_permission("task:view"))):
    return fetch_all("""SELECT j.id,j.job_type,j.status,j.progress,j.parameters,j.command_text,j.error_message,
      j.trigger_type,j.created_by,u.username created_by_username,j.created_at,j.started_at,j.finished_at
      FROM system_job j LEFT JOIN app_user u ON u.id=j.created_by ORDER BY j.id DESC LIMIT :limit""",{"limit":limit})

@router.get("/schedule")
def schedule(_:dict=Depends(require_permission("schedule:view"))): return get_schedule()

@router.put("/schedule")
def save_schedule(body:ScheduleUpdate,request:Request,user:dict=Depends(require_permission("schedule:update"))):
    if any(value<1 or value>7 for value in body.weekdays): raise HTTPException(422,"执行星期必须在1至7之间")
    try: result=update_schedule(body.enabled,body.run_time,body.weekdays,body.data_dir,body.source,body.top)
    except ValueError as exc: raise HTTPException(422,str(exc)) from exc
    audit("schedule.update",request,user,resource_type="schedule",resource_id=1,detail={"enabled":body.enabled,"run_time":str(body.run_time),"weekdays":body.weekdays});return result

@router.get("/{job_id}")
def detail(job_id:int,_:dict=Depends(require_permission("task:view"))):
    value=fetch_one("SELECT j.*,u.username created_by_username FROM system_job j LEFT JOIN app_user u ON u.id=j.created_by WHERE j.id=:id",{"id":job_id})
    if not value: raise HTTPException(404,"任务不存在")
    return value

@router.post("",status_code=202)
def create(body:JobCreate,request:Request,user:dict=Depends(require_permission("task:view"))):
    permission={"collect":"task:collect","predict":"task:predict","verify":"task:verify","intraday":"task:intraday","pipeline":"task:pipeline"}[body.job_type]
    if permission not in user["permissions"]:raise HTTPException(403,"没有执行该任务的权限")
    try: job_id=submit_job(body.job_type,body.data_dir,body.source,body.top,body.trade_date,user["id"],"manual")
    except (ValueError,RuntimeError) as exc: raise HTTPException(409,str(exc)) from exc
    audit(f"task.{body.job_type}",request,user,resource_type="system_job",resource_id=job_id)
    return {"id":job_id,"status":"pending"}
