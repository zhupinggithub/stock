from __future__ import annotations
from dataclasses import dataclass
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

@dataclass(frozen=True)
class Settings:
    db_host: str = os.getenv("STOCK_DB_HOST", "127.0.0.1")
    db_port: int = int(os.getenv("STOCK_DB_PORT", "3306"))
    db_user: str = os.getenv("STOCK_DB_USER", "root")
    db_password: str = os.getenv("STOCK_DB_PASSWORD", "")
    db_name: str = os.getenv("STOCK_DB_NAME", "stock")
    app_host: str = os.getenv("STOCK_APP_HOST", "0.0.0.0")
    app_port: int = int(os.getenv("STOCK_APP_PORT", "9999"))
    session_days: int = int(os.getenv("STOCK_SESSION_DAYS", "60"))
    session_idle_days: int = int(os.getenv("STOCK_SESSION_IDLE_DAYS", "30"))

settings = Settings()
