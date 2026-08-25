from __future__ import annotations
from datetime import date, datetime
from decimal import Decimal
from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

class Base(DeclarativeBase): pass

class StockMaster(Base):
    __tablename__ = "stock_master"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    stock_code: Mapped[str] = mapped_column(String(10), unique=True)
    market: Mapped[str] = mapped_column(String(2))
    stock_name: Mapped[str] = mapped_column(String(100))
    full_code: Mapped[str] = mapped_column(String(12), unique=True)
    daily: Mapped[list["StockDaily"]] = relationship(back_populates="stock")

class StockDaily(Base):
    __tablename__ = "stock_daily"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    stock_id: Mapped[int] = mapped_column(ForeignKey("stock_master.id"))
    trade_date: Mapped[date] = mapped_column(Date)
    open_price: Mapped[Decimal | None] = mapped_column(Numeric(12,4))
    close_price: Mapped[Decimal] = mapped_column(Numeric(12,4))
    high_price: Mapped[Decimal | None] = mapped_column(Numeric(12,4))
    low_price: Mapped[Decimal | None] = mapped_column(Numeric(12,4))
    volume: Mapped[Decimal | None] = mapped_column(Numeric(24,4))
    amount: Mapped[Decimal | None] = mapped_column(Numeric(24,4))
    stock: Mapped[StockMaster] = relationship(back_populates="daily")

class PredictionRun(Base):
    __tablename__ = "prediction_run"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    model_code: Mapped[str] = mapped_column(String(50))
    model_version: Mapped[str] = mapped_column(String(30))
    base_date: Mapped[date] = mapped_column(Date)
    top_n: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime)

class PredictionCandidate(Base):
    __tablename__ = "prediction_candidate"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    prediction_run_id: Mapped[int] = mapped_column(ForeignKey("prediction_run.id"))
    stock_id: Mapped[int] = mapped_column(ForeignKey("stock_master.id"))
    ranking: Mapped[int] = mapped_column(Integer)
    score: Mapped[Decimal] = mapped_column(Numeric(14,8))
