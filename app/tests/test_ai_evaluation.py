from __future__ import annotations

import asyncio
import json
import unittest
from typing import Any, Mapping

from app.ai import AIClient, AIDecision
from app.models import Guide
from app.services import AIEvaluationResult, AIEvaluationService
from app.services.guides import GuideEvaluation
from app.utils import ValidationResult


class DummyAsyncClient:
    def __init__(self, decision: AIDecision):
        self.decision = decision
        self.last_payload = None

    async def post(self, url: str, headers, json, timeout):
        return _DummyResponse(self.decision)


class DummyClassifyClient:
    def __init__(self, decision: AIDecision):
        self.decision = decision
        self.last_payload = None
        self._http_client = DummyAsyncClient(decision)

    async def classify(self, payload: Mapping[str, Any]) -> AIDecision:
        self.last_payload = payload
        return self.decision


class _DummyResponse:
    def __init__(self, decision: AIDecision):
        self.status_code = 200
        self._decision = decision

    def json(self):
        return {
            "choices": [
                {
                    "message": {
                        "content": [
                            {
                                "type": "output_json",
                                "output_json": {
                                    "decision": self._decision.decision,
                                    "confidence": self._decision.confidence,
                                    "matched_rules": list(self._decision.matched_rules),
                                    "violated_rules": list(self._decision.violated_rules),
                                    "risk_flags": list(self._decision.risk_flags),
                                    "explanation": self._decision.explanation,
                                },
                            }
                        ]
                    }
                }
            ]
        }


class AIEvaluationServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_rejects_on_validation_failure(self) -> None:
        validation = ValidationResult(
            passed=False,
            hard_rule_violations=("insufficient_liquidity",),
            soft_warnings=(),
        )
        ai_decision = AIDecision(
            decision="LONG",
            confidence=0.9,
            matched_rules=(),
            violated_rules=(),
            risk_flags=(),
            explanation="test",
        )
        dummy = DummyAsyncClient(ai_decision)
        service = AIEvaluationService(AIClient("key", http_client=dummy))

        result = await service.evaluate(
            symbol="AAPL",
            validation_result=validation,
            guide=None,
            guide_evaluation=None,
            search_signals={},
            price=150.0,
            volume_24h=100_000.0,
            indicators={},
        )

        self.assertFalse(result.passed_level_1)
        self.assertEqual(result.decision, "NO_TRADE")
        self.assertEqual(result.confidence, 0.0)

    async def test_accepts_on_full_pass(self) -> None:
        validation = ValidationResult(
            passed=True,
            hard_rule_violations=(),
            soft_warnings=(),
        )
        guide_eval = GuideEvaluation(
            allowed=True,
            unmet_hard_rules=(),
            matched_soft_rules=("volume_support",),
            disqualifiers=(),
        )
        ai_decision = AIDecision(
            decision="LONG",
            confidence=0.85,
            matched_rules=("rule_1",),
            violated_rules=(),
            risk_flags=(),
            explanation="Strong signal",
        )
        dummy = DummyAsyncClient(ai_decision)
        service = AIEvaluationService(AIClient("key", http_client=dummy))

        result = await service.evaluate(
            symbol="AAPL",
            validation_result=validation,
            guide=Guide(
                id=1,
                name="test",
                version="1.0",
                description="test",
                hard_rules=["rule_1"],
                soft_rules=["volume_support"],
                disqualifiers=[],
                is_active=True,
            ),
            guide_evaluation=guide_eval,
            search_signals={},
            price=150.0,
            volume_24h=5_000_000.0,
            indicators={"rsi": 35},
        )

        self.assertTrue(result.passed_level_1)
        self.assertEqual(result.decision, "LONG")
        self.assertGreater(result.confidence, 0.7)
        self.assertTrue(result.guide_alignment)

    async def test_rejects_low_confidence(self) -> None:
        validation = ValidationResult(
            passed=True,
            hard_rule_violations=(),
            soft_warnings=(),
        )
        ai_decision = AIDecision(
            decision="LONG",
            confidence=0.65,
            matched_rules=(),
            violated_rules=(),
            risk_flags=(),
            explanation="Weak signal",
        )
        dummy = DummyAsyncClient(ai_decision)
        service = AIEvaluationService(AIClient("key", http_client=dummy), confidence_threshold=0.7)

        result = await service.evaluate(
            symbol="XYZ",
            validation_result=validation,
            guide=None,
            guide_evaluation=None,
            search_signals={},
            price=50.0,
            volume_24h=2_000_000.0,
            indicators={},
        )

        self.assertEqual(result.decision, "NO_TRADE")
        self.assertIn("low_confidence", result.weak_conditions[0])

    async def test_rejects_misaligned_guide(self) -> None:
        validation = ValidationResult(
            passed=True,
            hard_rule_violations=(),
            soft_warnings=(),
        )
        guide_eval = GuideEvaluation(
            allowed=False,
            unmet_hard_rules=("price_above_sma",),
            matched_soft_rules=(),
            disqualifiers=(),
        )
        ai_decision = AIDecision(
            decision="LONG",
            confidence=0.9,
            matched_rules=(),
            violated_rules=(),
            risk_flags=(),
            explanation="Strong but guide says no",
        )
        dummy = DummyAsyncClient(ai_decision)
        service = AIEvaluationService(AIClient("key", http_client=dummy))

        result = await service.evaluate(
            symbol="ABC",
            validation_result=validation,
            guide=Guide(
                id=1,
                name="strict",
                version="1.0",
                description="strict guide",
                hard_rules=["price_above_sma"],
                soft_rules=[],
                disqualifiers=[],
                is_active=True,
            ),
            guide_evaluation=guide_eval,
            search_signals={},
            price=100.0,
            volume_24h=3_000_000.0,
            indicators={},
        )

        self.assertEqual(result.decision, "NO_TRADE")
        self.assertFalse(result.guide_alignment)

    async def test_identifies_weak_conditions(self) -> None:
        validation = ValidationResult(
            passed=True,
            hard_rule_violations=(),
            soft_warnings=(),
        )
        guide_eval = GuideEvaluation(
            allowed=False,
            unmet_hard_rules=("rule_a", "rule_b"),
            matched_soft_rules=(),
            disqualifiers=(),
        )
        ai_decision = AIDecision(
            decision="SHORT",
            confidence=0.75,
            matched_rules=(),
            violated_rules=(),
            risk_flags=("high_volatility",),
            explanation="test",
        )
        dummy = DummyAsyncClient(ai_decision)
        service = AIEvaluationService(AIClient("key", http_client=dummy))

        result = await service.evaluate(
            symbol="VOL",
            validation_result=validation,
            guide=None,
            guide_evaluation=guide_eval,
            search_signals={},
            price=75.0,
            volume_24h=2_500_000.0,
            indicators={},
        )

        self.assertIn("unmet_rules_2", result.weak_conditions)
        self.assertIn("high_volatility", result.weak_conditions)

    async def test_no_trade_on_ai_error(self) -> None:
        validation = ValidationResult(
            passed=True,
            hard_rule_violations=(),
            soft_warnings=(),
        )

        class FailingClient:
            async def classify(self, payload):
                raise RuntimeError("AI service down")

        service = AIEvaluationService(FailingClient())

        with self.assertRaises(RuntimeError):
            await service.evaluate(
                symbol="FAIL",
                validation_result=validation,
                guide=None,
                guide_evaluation=None,
                search_signals={},
                price=100.0,
                volume_24h=1_000_000.0,
                indicators={},
            )

    async def test_payload_structure(self) -> None:
        validation = ValidationResult(
            passed=True,
            hard_rule_violations=(),
            soft_warnings=(),
        )
        guide_eval = GuideEvaluation(
            allowed=True,
            unmet_hard_rules=(),
            matched_soft_rules=("soft_1",),
            disqualifiers=(),
        )
        ai_decision = AIDecision(
            decision="LONG",
            confidence=0.8,
            matched_rules=(),
            violated_rules=(),
            risk_flags=(),
            explanation="test",
        )
        dummy = DummyAsyncClient(ai_decision)
        service = AIEvaluationService(AIClient("key", http_client=dummy))

        result = await service.evaluate(
            symbol="PAY",
            validation_result=validation,
            guide=None,
            guide_evaluation=guide_eval,
            search_signals={"earnings": True},
            price=200.0,
            volume_24h=10_000_000.0,
            indicators={"rsi": 45, "vwap": 195},
        )

        self.assertEqual(result.symbol, "PAY")
        self.assertEqual(result.confidence, 0.8)
        self.assertEqual(result.decision, "LONG")


if __name__ == "__main__":
    asyncio.run(unittest.main())
