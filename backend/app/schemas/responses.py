from typing import Any
from pydantic import BaseModel

class DashboardResponse(BaseModel):
    stats: dict[str, Any]
    latest_prediction: dict[str, Any]
    latest_intraday_groups: list[dict[str, Any]]
    market_history: list[dict[str, Any]]
