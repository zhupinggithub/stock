from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from backend.app.api import admin,auth,dashboard,intraday,predictions,stocks,tasks,tracking,verifications
from backend.app.database import init_schema
from backend.app.repositories.query_repository import fetch_one
from backend.app.services.job_service import recover_interrupted_jobs
from backend.app.services.schedule_service import start_scheduler,stop_scheduler

ROOT=Path(__file__).resolve().parents[2]
DIST=ROOT/"frontend"/"dist"
init_schema()
recover_interrupted_jobs()
@asynccontextmanager
async def lifespan(app:FastAPI):
    start_scheduler()
    yield
    stop_scheduler()

app=FastAPI(title="A股量化观察台",version="1.0.0",lifespan=lifespan)
for router in (auth.router,admin.router,dashboard.router,predictions.router,intraday.router,tracking.router,verifications.router,stocks.router,tasks.router): app.include_router(router,prefix="/api")

@app.get("/api/health",tags=["system"])
def health(): return {"status":"ok","database":fetch_one("SELECT DATABASE() name,VERSION() version")}

if DIST.exists():
    app.mount("/assets",StaticFiles(directory=DIST/"assets"),name="assets")
    @app.get("/{path:path}",include_in_schema=False)
    def frontend(path:str): return FileResponse(DIST/"index.html")
