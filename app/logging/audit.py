from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, Mapping

from sqlalchemy.orm import Session

from app.models import (
    AIOutputLog,
    DecisionLog,
    OrderLog,
    RiskOverrideLog,
    RuleCheckLog,
    TradeOutcomeLog,
)
if TYPE_CHECKING:
    from app.services.execution import ExecutedOrder


class AuditLogger:
    def __init__(self, session: Session, logger: logging.Logger | None = None) -> None:
        self.session = session
        self.logger = logger or logging.getLogger("broker.audit")

    def record_decision(
        self,
        symbol: str,
        decision_type: str,
        decision: str,
        reason: str,
        confidence: float | None = None,
        context: Mapping[str, Any] | None = None,
    ) -> DecisionLog:
        entry = DecisionLog(
            symbol=symbol,
            decision_type=decision_type,
            decision=decision,
            reason=reason,
            confidence=confidence,
            context=dict(context) if context else {},
        )
        self._persist(entry, "decision")
        return entry

    def record_ai_output(
        self,
        symbol: str,
        decision: str,
        confidence: float,
        matched_rules: list[str] | tuple[str, ...],
        violated_rules: list[str] | tuple[str, ...],
        risk_flags: list[str] | tuple[str, ...],
        explanation: str | None,
        payload: Mapping[str, Any],
    ) -> AIOutputLog:
        entry = AIOutputLog(
            symbol=symbol,
            decision=decision,
            confidence=confidence,
            matched_rules=list(matched_rules),
            violated_rules=list(violated_rules),
            risk_flags=list(risk_flags),
            explanation=explanation,
            payload=dict(payload),
        )
        self._persist(entry, "ai_output")
        return entry

    def record_rule_check(
        self,
        symbol: str,
        rule: str,
        passed: bool,
        details: Mapping[str, Any] | None = None,
    ) -> RuleCheckLog:
        entry = RuleCheckLog(
            symbol=symbol,
            rule=rule,
            passed=passed,
            details=dict(details) if details else {},
        )
        self._persist(entry, "rule_check")
        return entry

    def record_risk_override(
        self,
        symbol: str,
        original_decision: str,
        override_decision: str,
        reason: str,
        actor: str,
        context: Mapping[str, Any] | None = None,
    ) -> RiskOverrideLog:
        entry = RiskOverrideLog(
            symbol=symbol,
            original_decision=original_decision,
            override_decision=override_decision,
            reason=reason,
            actor=actor,
            context=dict(context) if context else {},
        )
        self._persist(entry, "risk_override")
        return entry

    def record_order(self, order: "ExecutedOrder", raw_response: Mapping[str, Any] | None = None) -> OrderLog:
        entry = OrderLog(
            order_id=order.order_id,
            symbol=order.symbol,
            side=order.side,
            qty=order.qty,
            status=order.status.value,
            filled_qty=order.filled_qty,
            filled_avg_price=order.filled_avg_price,
            submitted_at=order.submitted_at,
            filled_at=order.filled_at,
            estimated_slippage_bps=order.estimated_slippage_bps,
            raw_response=dict(raw_response) if raw_response else {},
        )
        self._persist(entry, "order")
        return entry

    def record_trade_outcome(
        self,
        order_id: str,
        symbol: str,
        outcome: str,
        pnl: float,
        duration_seconds: int | None = None,
        context: Mapping[str, Any] | None = None,
    ) -> TradeOutcomeLog:
        entry = TradeOutcomeLog(
            order_id=order_id,
            symbol=symbol,
            outcome=outcome,
            pnl=pnl,
            duration_seconds=duration_seconds,
            context=dict(context) if context else {},
        )
        self._persist(entry, "trade_outcome")
        return entry

    def _persist(self, entry: Any, category: str) -> None:
        self.session.add(entry)
        try:
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise
        self.session.refresh(entry)
        self._log_entry(category, entry)

    def _log_entry(self, category: str, entry: Any) -> None:
        payload = {"category": category}
        for column in entry.__table__.columns:
            payload[column.name] = getattr(entry, column.name)
        self.logger.info(json.dumps(payload, default=str))
