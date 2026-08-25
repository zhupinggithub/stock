from datetime import date,time
from typing import Literal
from pydantic import BaseModel,Field

class JobCreate(BaseModel):
    job_type: Literal["collect","predict","verify","intraday","pipeline"]
    data_dir: str = "data"
    source: Literal["sina","eastmoney","auto"] = "sina"
    top: int = Field(30,ge=1,le=500)
    trade_date: date | None = None

class ScheduleUpdate(BaseModel):
    enabled: bool = False
    run_time: time
    weekdays: list[int] = Field(min_length=1)
    data_dir: str = "data"
    source: Literal["sina","eastmoney","auto"] = "sina"
    top: int = Field(30,ge=1,le=500)
