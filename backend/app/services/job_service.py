from __future__ import annotations
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock
from typing import Any
from sqlalchemy import text
from backend.app.database import engine

ROOT=Path(__file__).resolve().parents[3]
EXECUTOR=ThreadPoolExecutor(max_workers=1,thread_name_prefix="stock-job")
SUBMIT_LOCK=Lock()

def _resolve_data_dir(value:str)->Path:
    target=(ROOT/value).resolve() if not Path(value).is_absolute() else Path(value).resolve()
    if target!=ROOT and ROOT not in target.parents: raise ValueError("数据目录必须位于项目目录内")
    if not target.exists() or not target.is_dir(): raise ValueError(f"数据目录不存在：{value}")
    return target

def _commands(kind:str,data_dir:Path,source:str,top:int)->list[list[str]]:
    py=sys.executable; relative=str(data_dir.relative_to(ROOT))
    commands={
      "collect":[[py,"scripts/market_fetcher.py","incremental","--output-dir",relative,"--list-source",source]],
      "predict":[[py,"scripts/stock_predictor.py","--data-dir",relative,"--top",str(top)]],
      "verify":[[py,"scripts/verify_predictions.py","--data-dir",relative]],
      "intraday":[[py,"scripts/monitor_predictions_intraday.py","--data-dir",relative,"--source",source]],
      "pipeline":[[py,"scripts/stock_pipeline.py","--data-dir",relative,"--source",source,"--top",str(top)]],
    }
    result=commands[kind]
    if kind!="pipeline": result.append([py,"scripts/import_existing_csv.py","--data-dir",relative])
    return result

def submit_job(kind:str,data_dir:str,source:str,top:int)->int:
    target=_resolve_data_dir(data_dir)
    with SUBMIT_LOCK,engine().begin() as conn:
        active=conn.execute(text("SELECT id FROM system_job WHERE status IN ('pending','running') ORDER BY id LIMIT 1")).scalar()
        if active: raise RuntimeError(f"已有任务 #{active} 正在运行，请等待完成")
        params={"data_dir":str(target.relative_to(ROOT)),"source":source,"top":top}
        result=conn.execute(text("INSERT INTO system_job(job_type,status,parameters) VALUES(:type,'pending',:params)"),{"type":kind,"params":json.dumps(params,ensure_ascii=False)})
        job_id=int(result.lastrowid)
    EXECUTOR.submit(_run_job,job_id,kind,target,source,top)
    return job_id

def _append_log(job_id:int,message:str)->None:
    with engine().begin() as conn: conn.execute(text("UPDATE system_job SET log_text=CONCAT(COALESCE(log_text,''),:message) WHERE id=:id"),{"id":job_id,"message":message})

def _run_job(job_id:int,kind:str,data_dir:Path,source:str,top:int)->None:
    commands=_commands(kind,data_dir,source,top)
    env=os.environ.copy();env["PYTHONUTF8"]="1";env["PYTHONUNBUFFERED"]="1"
    try:
        with engine().begin() as conn: conn.execute(text("UPDATE system_job SET status='running',progress=5,started_at=NOW(),command_text=:cmd WHERE id=:id"),{"id":job_id,"cmd":" && ".join(subprocess.list2cmdline(c) for c in commands)})
        for index,command in enumerate(commands):
            _append_log(job_id,f"\n$ {subprocess.list2cmdline(command)}\n")
            process=subprocess.Popen(command,cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding="utf-8",errors="replace",env=env)
            assert process.stdout
            for line in process.stdout: _append_log(job_id,line)
            code=process.wait()
            if code: raise RuntimeError(f"命令执行失败，退出码 {code}")
            progress=10+int(85*(index+1)/len(commands))
            with engine().begin() as conn: conn.execute(text("UPDATE system_job SET progress=:progress WHERE id=:id"),{"id":job_id,"progress":progress})
        with engine().begin() as conn: conn.execute(text("UPDATE system_job SET status='success',progress=100,finished_at=NOW() WHERE id=:id"),{"id":job_id})
    except Exception as exc:
        _append_log(job_id,f"\nERROR: {exc}\n")
        with engine().begin() as conn: conn.execute(text("UPDATE system_job SET status='failed',finished_at=NOW(),error_message=:error WHERE id=:id"),{"id":job_id,"error":str(exc)})

def recover_interrupted_jobs()->None:
    with engine().begin() as conn: conn.execute(text("UPDATE system_job SET status='failed',finished_at=NOW(),error_message='服务重启，任务执行被中断' WHERE status IN ('pending','running')"))
