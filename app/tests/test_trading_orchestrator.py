from __future__ import annotations

import asyncio
import os
import unittest
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Sequence

from app.services.ai_evaluation import AIEvaluationResult
from app.services.execution import ExecutedOrder, OrderStatus
from app.services.market_data import Candle
from app.services.news_sentiment import NewsSentimentResult
from app.services.search import SearchSignals
from app.services.trading import TradingDecision, TradingOrchestrator
from app.services.risk import PositionSize
from app.utils import ValidationResult


class DummyMarketDataClient:
    def __init__(self, bars: Sequence[Candle]):
        self._bars = list(bars)
        self.latest_requested = False
        self.history_requested = False

    async def historical_bars(self, symbol: str, timeframe: str, start: str, end: str | None = None, limit: int = 1000) -> Sequence[Candle]:
        self.history_requested = True
        return self._bars

    async def latest_bar(self, symbol: str, timeframe: str = "1Min") -> Candle:
        self.latest_requested = True
        return self._bars[-1]


class DummySearchClient:
    async def search(self, query: str, freshness: str = "pd", count: int = 10, **_: Any) -> SearchSignals:
        return SearchSignals(
            total_results=5,
            earnings=False,
            lawsuits=False,
            fda=False,
            macro=False,
            unusual_mentions=False,
            matched_categories=(),
        )


class DummyAIService:
    def __init__(self, decision: str = "LONG", confidence: float = 0.9) -> None:
        self.decision = decision
        self.confidence = confidence
        self.last_payload: Mapping[str, Any] | None = None

    async def evaluate(
        self,
        symbol: str,
        validation_result: ValidationResult,
        guide,
        guide_evaluation,
        search_signals: Mapping[str, Any],
        price: float,
        volume_24h: float,
        indicators: Mapping[str, float],
        current_position: float | int = 0,
    ) -> AIEvaluationResult:
        self.last_payload = {
            "symbol": symbol,
            "validation_result": validation_result,
            "guide": guide,
            "guide_evaluation": guide_evaluation,
            "search_signals": search_signals,
            "price": price,
            "volume_24h": volume_24h,
            "indicators": indicators,
            "current_position": current_position,
        }
        return AIEvaluationResult(
            symbol=symbol,
            passed_level_1=True,
            decision=self.decision,
            confidence=self.confidence,
            guide_alignment=True,
            weak_conditions=(),
            matched_rules=(),
            violated_rules=(),
        )


class DummyValidationService:
    def __init__(self, passed: bool = True) -> None:
        self.passed = passed

    def validate(
        self,
        symbol: str,
        current_price: float,
        volume_24h: float,
        latest_bars,
        market_regime: str,
        has_earnings_today: bool,
        has_fda_event: bool,
        is_trading_halted: bool,
        use_extended_hours: bool = False,
    ) -> ValidationResult:
        violations = () if self.passed else ("blocked",)
        return ValidationResult(self.passed, violations, ())


class DummyNewsSentimentEvaluator:
    def __init__(self, passed: bool = True, risk_level: str = "low") -> None:
        self.passed = passed
        self.risk_level = risk_level

    def evaluate(self, symbol: str, search_signals: Mapping[str, Any]) -> NewsSentimentResult:
        return NewsSentimentResult(
            symbol=symbol,
            passed=self.passed,
            risk_level=self.risk_level,
            rejection_reason="test_reason" if not self.passed else "no_major_risks",
            signals_detected=(),
            total_mentions=5,
            sentiment_score=0.5,
        )


class DummyRiskGovernor:
    def __init__(self, approves: bool = True) -> None:
        self.approves = approves
        self.state = type("State", (), {"daily_loss": 0.0})()

    def evaluate(
        self,
        symbol: str,
        decision: str,
        confidence: float,
        price: float,
        atr: float,
        previous_loss: float = 0.0,
    ) -> tuple[bool, str, PositionSize | None]:
        if not self.approves:
            return False, "blocked", None
        position = PositionSize(shares=10, notional=price * 10, risk_per_trade=100.0, stop_loss_price=price - 1.0)
        return True, "ok", position


class DummyExecutionService:
    def __init__(self, approve: bool = True) -> None:
        self.approve = approve
        self.called = False

    async def execute_trade(
        self,
        request,
        position_size_from_risk: int,
        entry_price_estimate: float,
        has_passed_all_checks: bool,
    ) -> tuple[bool, str, ExecutedOrder | None]:
        self.called = True
        if not self.approve:
            return False, "rejected", None
        order = ExecutedOrder(
            order_id="o-1",
            symbol=request.symbol,
            qty=request.qty,
            filled_qty=request.qty,
            side=request.side,
            status=OrderStatus.FILLED,
            filled_avg_price=entry_price_estimate,
            submitted_at=datetime.now(timezone.utc),
            filled_at=datetime.now(timezone.utc),
            estimated_slippage_bps=0.0,
        )
        return True, "executed", order


def sample_bars(symbol: str, count: int = 60) -> list[Candle]:
    now = datetime.now(timezone.utc)
    bars: list[Candle] = []
    for i in range(count):
        base = 100 + i * 0.1
        bars.append(
            Candle(
                symbol=symbol,
                timeframe="1Min",
                open=base,
                high=base + 0.5,
                low=base - 0.5,
                close=base + 0.2,
                volume=20000,
                timestamp=(now - timedelta(minutes=count - i)).isoformat(),
            )
        )
    return bars


class TradingOrchestratorTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        os.environ["APP_ENV"] = "test"

    async def test_executes_when_enabled(self) -> None:
        bars = sample_bars("AAPL")
        orchestrator = TradingOrchestrator(
            market_data_client=DummyMarketDataClient(bars),
            search_client=DummySearchClient(),
            ai_service=DummyAIService(),
            validation_service=DummyValidationService(),
            news_sentiment_evaluator=DummyNewsSentimentEvaluator(),
            risk_governor=DummyRiskGovernor(),
            execution_service=DummyExecutionService(),
            allow_execution=True,
        )

        decision = await orchestrator.run("AAPL", strategy=None, execute=True)

        self.assertIsInstance(decision, TradingDecision)
        self.assertEqual(decision.final_decision, "LONG")
        self.assertIsNotNone(decision.executed_order)
        self.assertEqual(decision.risk_position.shares if decision.risk_position else 0, 10)

    async def test_returns_plan_when_execution_disabled(self) -> None:
        bars = sample_bars("MSFT")
        execution = DummyExecutionService()
        orchestrator = TradingOrchestrator(
            market_data_client=DummyMarketDataClient(bars),
            search_client=DummySearchClient(),
            ai_service=DummyAIService(),
            validation_service=DummyValidationService(),
            news_sentiment_evaluator=DummyNewsSentimentEvaluator(),
            risk_governor=DummyRiskGovernor(),
            execution_service=execution,
            allow_execution=False,
        )

        decision = await orchestrator.run("MSFT", strategy=None, execute=True)

        self.assertEqual(decision.final_decision, "LONG")
        self.assertIsNone(decision.executed_order)
        self.assertFalse(execution.called)

    async def test_blocks_on_validation_failure(self) -> None:
        bars = sample_bars("TSLA")
        orchestrator = TradingOrchestrator(
            market_data_client=DummyMarketDataClient(bars),
            search_client=DummySearchClient(),
            ai_service=DummyAIService(),
            validation_service=DummyValidationService(passed=False),
            news_sentiment_evaluator=DummyNewsSentimentEvaluator(),
            risk_governor=DummyRiskGovernor(),
            execution_service=DummyExecutionService(),
            allow_execution=True,
        )

        decision = await orchestrator.run("TSLA", strategy=None, execute=True)

        self.assertEqual(decision.final_decision, "NO_TRADE")
        self.assertIsNone(decision.executed_order)
        self.assertEqual(decision.validation.passed, False)

    async def test_blocks_on_news_sentiment_failure(self) -> None:
        bars = sample_bars("NFLX")
        orchestrator = TradingOrchestrator(
            market_data_client=DummyMarketDataClient(bars),
            search_client=DummySearchClient(),
            ai_service=DummyAIService(),
            validation_service=DummyValidationService(),
            news_sentiment_evaluator=DummyNewsSentimentEvaluator(passed=False, risk_level="high"),
            risk_governor=DummyRiskGovernor(),
            execution_service=DummyExecutionService(),
            allow_execution=True,
        )

        decision = await orchestrator.run("NFLX", strategy=None, execute=True)

        self.assertEqual(decision.final_decision, "NO_TRADE")
        self.assertIsNone(decision.executed_order)
        self.assertIsNotNone(decision.news_sentiment)
        self.assertEqual(decision.news_sentiment.passed, False)
        self.assertEqual(decision.news_sentiment.risk_level, "high")


if __name__ == "__main__":
    asyncio.run(unittest.main())
