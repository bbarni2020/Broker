from __future__ import annotations

import unittest
from datetime import datetime, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.logging import AuditLogger
from app.models import (
    AIOutputLog,
    Base,
    DecisionLog,
    OrderLog,
    RiskOverrideLog,
    RuleCheckLog,
    TradeOutcomeLog,
)
from app.services.execution import ExecutedOrder, OrderStatus


class AuditLoggingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        self.audit = AuditLogger(self.session)

    def tearDown(self) -> None:
        self.session.close()
        self.engine.dispose()

    def test_record_decision_persists(self) -> None:
        entry = self.audit.record_decision(
            "AAPL",
            "level_1",
            "NO_TRADE",
            "Failed checks",
            confidence=0.25,
            context={"violations": ["liquidity"]},
        )
        stored = self.session.query(DecisionLog).filter_by(id=entry.id).one()
        self.assertEqual(stored.symbol, "AAPL")
        self.assertEqual(stored.decision, "NO_TRADE")
        self.assertEqual(stored.context["violations"], ["liquidity"])

    def test_record_ai_output_persists(self) -> None:
        entry = self.audit.record_ai_output(
            "MSFT",
            "LONG",
            0.82,
            ("r1",),
            (),
            ("risk_flag",),
            "Good setup",
            {"payload": True},
        )
        stored = self.session.query(AIOutputLog).filter_by(id=entry.id).one()
        self.assertEqual(stored.decision, "LONG")
        self.assertEqual(stored.matched_rules, ["r1"])
        self.assertEqual(stored.risk_flags, ["risk_flag"])

    def test_rule_and_override_logging(self) -> None:
        rule_entry = self.audit.record_rule_check("NVDA", "volume", False, {"value": 100})
        override_entry = self.audit.record_risk_override(
            "NVDA",
            "NO_TRADE",
            "ALLOW",
            "Manual approval",
            "risk_officer",
            context={"note": "override"},
        )
        stored_rule = self.session.query(RuleCheckLog).filter_by(id=rule_entry.id).one()
        stored_override = self.session.query(RiskOverrideLog).filter_by(id=override_entry.id).one()
        self.assertFalse(stored_rule.passed)
        self.assertEqual(stored_override.override_decision, "ALLOW")
        self.assertEqual(stored_override.context["note"], "override")

    def test_order_and_trade_outcome_logging(self) -> None:
        now = datetime.now(timezone.utc)
        order = ExecutedOrder(
            order_id="ord-1",
            symbol="TSLA",
            qty=10,
            filled_qty=10,
            side="buy",
            status=OrderStatus.FILLED,
            filled_avg_price=250.5,
            submitted_at=now,
            filled_at=now,
            estimated_slippage_bps=5.0,
        )
        order_entry = self.audit.record_order(order, {"broker": "alpaca"})
        outcome_entry = self.audit.record_trade_outcome(
            "ord-1",
            "TSLA",
            "closed",
            125.0,
            duration_seconds=3600,
            context={"exit_reason": "target"},
        )
        stored_order = self.session.query(OrderLog).filter_by(id=order_entry.id).one()
        stored_outcome = self.session.query(TradeOutcomeLog).filter_by(id=outcome_entry.id).one()
        self.assertEqual(stored_order.estimated_slippage_bps, 5.0)
        self.assertEqual(stored_outcome.pnl, 125.0)
        self.assertEqual(stored_outcome.context["exit_reason"], "target")

    def test_logs_are_immutable(self) -> None:
        entry = self.audit.record_decision(
            "AMZN",
            "level_1",
            "NO_TRADE",
            "Validation failed",
        )
        entry.reason = "changed"
        with self.assertRaises(ValueError):
            self.session.commit()
        self.session.rollback()
        with self.assertRaises(ValueError):
            self.session.delete(entry)
            self.session.commit()
        self.session.rollback()


if __name__ == "__main__":
    unittest.main()
