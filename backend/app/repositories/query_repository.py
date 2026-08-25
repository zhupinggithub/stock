from __future__ import annotations
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from sqlalchemy import text
from backend.app.database import engine

def _serial(value: Any) -> Any:
    if isinstance(value, Decimal): return float(value)
    if isinstance(value, (date, datetime)): return value.isoformat()
    return value

def fetch_all(sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    with engine().connect() as conn:
        result=conn.execute(text(sql),params or {})
        return [{k:_serial(v) for k,v in row.items()} for row in result.mappings()]

def fetch_one(sql: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    values=fetch_all(sql,params)
    return values[0] if values else {}
