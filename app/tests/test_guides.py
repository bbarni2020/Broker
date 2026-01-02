from __future__ import annotations

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.models import Base
from app.services import GuideEvaluation, GuidePayload, GuideService


class GuideServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine, future=True)
        self.service = GuideService()

    def tearDown(self) -> None:
        self.engine.dispose()

    def test_create_and_versioning(self) -> None:
        with self.SessionLocal() as session:
            payload = GuidePayload(
                name="trend-follow",
                version="1.0",
                description="Trend following rules",
                hard_rules=["price_above_sma", "atr_ok"],
                soft_rules=["volume_support"],
                disqualifiers=["halted"],
            )
            guide = self.service.create(session, payload)
            self.assertEqual(guide.version, "1.0")
            with self.assertRaises(ValueError):
                self.service.create(session, payload)

    def test_rule_evaluation(self) -> None:
        with self.SessionLocal() as session:
            payload = GuidePayload(
                name="mean-revert",
                version="1.0",
                description="Mean reversion rules",
                hard_rules=["rsi_oversold"],
                soft_rules=["vwap_support"],
                disqualifiers=["earnings_day"],
            )
            guide = self.service.create(session, payload)
            result = self.service.evaluate(guide, signals={"vwap_support"})
            self.assertIsInstance(result, GuideEvaluation)
            self.assertFalse(result.allowed)
            self.assertIn("rsi_oversold", result.unmet_hard_rules)
            result_ok = self.service.evaluate(guide, signals={"rsi_oversold", "vwap_support"})
            self.assertTrue(result_ok.allowed)
            result_block = self.service.evaluate(guide, signals={"rsi_oversold", "earnings_day"})
            self.assertFalse(result_block.allowed)
            self.assertIn("earnings_day", result_block.disqualifiers)

    def test_invalid_payload(self) -> None:
        with self.SessionLocal() as session:
            with self.assertRaises(ValueError):
                self.service.create(
                    session,
                    GuidePayload(
                        name="",
                        version="1.0",
                        description="",
                        hard_rules=["a"],
                        soft_rules=[],
                        disqualifiers=[],
                    ),
                )
            with self.assertRaises(ValueError):
                self.service.create(
                    session,
                    GuidePayload(
                        name="valid",
                        version="1.0",
                        description="x",
                        hard_rules=[],
                        soft_rules=[],
                        disqualifiers=[],
                    ),
                )

    def test_attach_strategy(self) -> None:
        with self.SessionLocal() as session:
            guide = self.service.create(
                session,
                GuidePayload(
                    name="attachable",
                    version="1.0",
                    description="Attach test",
                    hard_rules=["x"],
                    soft_rules=[],
                    disqualifiers=[],
                ),
            )
            link = self.service.attach_to_strategy(session, guide.id, "strategy-a")
            self.assertEqual(link.strategy, "strategy-a")
            self.assertEqual(link.guide_id, guide.id)


if __name__ == "__main__":
    unittest.main()
