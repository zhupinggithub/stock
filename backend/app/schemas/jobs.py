from typing import Literal
from pydantic import BaseModel,Field

class JobCreate(BaseModel):
    job_type: Literal["collect","predict","verify","intraday","pipeline"]
    data_dir: str = "data"
    source: Literal["sina","eastmoney","auto"] = "sina"
    top: int = Field(30,ge=1,le=500)
