from fastapi import APIRouter,HTTPException,Query
from backend.app.repositories.query_repository import fetch_all,fetch_one
from backend.app.schemas.jobs import JobCreate
from backend.app.services.job_service import submit_job

router=APIRouter(prefix="/tasks",tags=["tasks"])

@router.get("")
def jobs(limit:int=Query(30,ge=1,le=200)):
    return fetch_all("""SELECT id,job_type,status,progress,parameters,command_text,error_message,
      created_at,started_at,finished_at FROM system_job ORDER BY id DESC LIMIT :limit""",{"limit":limit})

@router.get("/{job_id}")
def detail(job_id:int):
    value=fetch_one("SELECT * FROM system_job WHERE id=:id",{"id":job_id})
    if not value: raise HTTPException(404,"任务不存在")
    return value

@router.post("",status_code=202)
def create(body:JobCreate):
    try: job_id=submit_job(body.job_type,body.data_dir,body.source,body.top)
    except (ValueError,RuntimeError) as exc: raise HTTPException(409,str(exc)) from exc
    return {"id":job_id,"status":"pending"}
