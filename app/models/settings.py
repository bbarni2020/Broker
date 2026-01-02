from __future__ import annotations

from sqlalchemy import Column, DateTime, Float, Integer, String, func

from .db import Base


class BaseRules(Base):
    __tablename__ = "base_rules"

    id = Column(Integer, primary_key=True, autoincrement=True)
    max_risk_per_trade = Column(Float, nullable=False, default=0.01)
    max_daily_loss = Column(Float, nullable=False, default=0.05)
    max_trades_per_day = Column(Integer, nullable=False, default=10)
    cooldown_seconds = Column(Integer, nullable=False, default=300)


class DashboardSecret(Base):
    __tablename__ = "dashboard_secrets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_secret = Column(String, nullable=False)
    otp_secret = Column(String(64), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
