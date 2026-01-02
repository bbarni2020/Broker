from __future__ import annotations

from sqlalchemy import Boolean, Column, DateTime, Float, Integer, JSON, String, event, func

from .db import Base


class ImmutableLogMixin:
    @classmethod
    def __declare_last__(cls) -> None:
        event.listen(cls, "before_update", cls._deny_mutation)
        event.listen(cls, "before_delete", cls._deny_mutation)

    @staticmethod
    def _deny_mutation(mapper, connection, target) -> None:
        raise ValueError("Log entries are immutable")


class DecisionLog(ImmutableLogMixin, Base):
    __tablename__ = "decision_logs"

    id = Column(Integer, primary_key=True)
    symbol = Column(String(32), nullable=False)
    decision_type = Column(String(64), nullable=False)
    decision = Column(String(32), nullable=False)
    reason = Column(String, nullable=False)
    confidence = Column(Float)
    context = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AIOutputLog(ImmutableLogMixin, Base):
    __tablename__ = "ai_output_logs"

    id = Column(Integer, primary_key=True)
    symbol = Column(String(32), nullable=False)
    decision = Column(String(32), nullable=False)
    confidence = Column(Float, nullable=False)
    matched_rules = Column(JSON, nullable=False, default=list)
    violated_rules = Column(JSON, nullable=False, default=list)
    risk_flags = Column(JSON, nullable=False, default=list)
    explanation = Column(String, nullable=True)
    payload = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class RuleCheckLog(ImmutableLogMixin, Base):
    __tablename__ = "rule_check_logs"

    id = Column(Integer, primary_key=True)
    symbol = Column(String(32), nullable=False)
    rule = Column(String(128), nullable=False)
    passed = Column(Boolean, nullable=False)
    details = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class RiskOverrideLog(ImmutableLogMixin, Base):
    __tablename__ = "risk_override_logs"

    id = Column(Integer, primary_key=True)
    symbol = Column(String(32), nullable=False)
    original_decision = Column(String(32), nullable=False)
    override_decision = Column(String(32), nullable=False)
    reason = Column(String, nullable=False)
    actor = Column(String(64), nullable=False)
    context = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class OrderLog(ImmutableLogMixin, Base):
    __tablename__ = "order_logs"

    id = Column(Integer, primary_key=True)
    order_id = Column(String(64), nullable=False, unique=True)
    symbol = Column(String(32), nullable=False)
    side = Column(String(8), nullable=False)
    qty = Column(Integer, nullable=False)
    status = Column(String(32), nullable=False)
    filled_qty = Column(Integer, nullable=False, default=0)
    filled_avg_price = Column(Float)
    submitted_at = Column(DateTime(timezone=True), nullable=False)
    filled_at = Column(DateTime(timezone=True))
    estimated_slippage_bps = Column(Float, nullable=False, default=0.0)
    raw_response = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class TradeOutcomeLog(ImmutableLogMixin, Base):
    __tablename__ = "trade_outcome_logs"

    id = Column(Integer, primary_key=True)
    order_id = Column(String(64), nullable=False)
    symbol = Column(String(32), nullable=False)
    outcome = Column(String(32), nullable=False)
    pnl = Column(Float, nullable=False)
    duration_seconds = Column(Integer)
    context = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
