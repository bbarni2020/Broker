from __future__ import annotations

import os
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Sequence

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai import AIClient
from app.config import Settings
from app.indicators.core import atr, ema, rsi, vwap
from app.logging import AuditLogger, log_decision
from app.models import Guide, OrderLog, StrategyGuideLink, TradeOutcomeLog
from app.services.ai_evaluation import AIEvaluationResult, AIEvaluationService
from app.services.execution import (
    AlpacaExecutionClient,
    ExecutedOrder,
    ExecutionService,
    OrderRequest,
    OrderType,
    StopLoss,
    TimeInForce,
)
from app.services.guides import GuideEvaluation, GuideService
from app.services.market_data import Candle, HybridMarketDataClient, MarketDataClient, YahooMarketDataClient
from app.services.news_sentiment import NewsSentimentEvaluator, NewsSentimentResult
from app.services.risk import PositionSize, RiskGovernor
from app.services.search import SearchSignals, WebSearchClient
from app.utils import ValidationResult, ValidationService


@dataclass(frozen=True)
class TradingDecision:
    symbol: str
    final_decision: str
    price: float
    volume_24h: float
    indicators: Mapping[str, float]
    validation: ValidationResult
    search_signals: Mapping[str, Any]
    news_sentiment: NewsSentimentResult | None
    guide_evaluation: GuideEvaluation | None
    ai_result: AIEvaluationResult
    risk_position: PositionSize | None
    risk_reason: str
    executed_order: ExecutedOrder | None
    execution_reason: str


class TradingOrchestrator:
    def __init__(
        self,
        market_data_client: MarketDataClient,
        search_client: WebSearchClient,
        ai_service: AIEvaluationService,
        validation_service: ValidationService,
        news_sentiment_evaluator: NewsSentimentEvaluator,
        risk_governor: RiskGovernor,
        execution_service: ExecutionService,
        guide_service: GuideService | None = None,
        session: Session | None = None,
        audit_logger: AuditLogger | None = None,
        allow_execution: bool = False,
    ) -> None:
        self.market_data_client = market_data_client
        self.search_client = search_client
        self.ai_service = ai_service
        self.validation_service = validation_service
        self.news_sentiment_evaluator = news_sentiment_evaluator
        self.risk_governor = risk_governor
        self.execution_service = execution_service
        self.guide_service = guide_service
        self.session = session
        self.audit_logger = audit_logger
        self.allow_execution = allow_execution

    async def run(
        self,
        symbol: str,
        strategy: str | None = None,
        execute: bool = False,
        use_extended_hours: bool = False,
    ) -> TradingDecision:
        current_position = self._current_position(symbol)
        market_snapshot = await self._load_market_data(symbol)
        if market_snapshot is None:
            validation = ValidationResult(False, ("market_data_error",), ())
            ai_result = self._empty_ai_result(symbol)
            self._record_validation(symbol, validation)
            self._record_final(symbol, "NO_TRADE", "market_data_error", {})
            return TradingDecision(
                symbol=symbol,
                final_decision="NO_TRADE",
                price=0.0,
                volume_24h=0.0,
                indicators={},
                validation=validation,
                search_signals={},
                news_sentiment=None,
                guide_evaluation=None,
                ai_result=ai_result,
                risk_position=None,
                risk_reason="market_data_error",
                executed_order=None,
                execution_reason="market_data_error",
            )

        bars, latest_bar = market_snapshot
        indicators = self._compute_indicators(bars)
        price = latest_bar.close
        volume_24h = float(sum(c.volume for c in bars))

        search_signals = await self._load_search_signals(symbol)
        validation = self.validation_service.validate(
            symbol=symbol,
            current_price=price,
            volume_24h=volume_24h,
            latest_bars=self._candles_to_frame(bars),
            market_regime="normal",
            has_earnings_today=bool(search_signals.get("earnings")),
            has_fda_event=bool(search_signals.get("fda")),
            is_trading_halted=False,
            use_extended_hours=use_extended_hours,
        )
        self._record_validation(symbol, validation)

        news_sentiment = self.news_sentiment_evaluator.evaluate(symbol, search_signals)

        guide, guide_eval = self._evaluate_guide(strategy, search_signals)

        ai_result = await self.ai_service.evaluate(
            symbol=symbol,
            validation_result=validation,
            guide=guide,
            guide_evaluation=guide_eval,
            search_signals=search_signals,
            price=price,
            volume_24h=volume_24h,
            indicators=indicators,
            current_position=current_position,
        )

        risk_ok, risk_reason, position = self.risk_governor.evaluate(
            symbol=symbol,
            decision=ai_result.decision,
            confidence=ai_result.confidence,
            price=price,
            atr=indicators.get("atr", 0.0),
            previous_loss=self.risk_governor.state.daily_loss,
        )
        self._record_risk(symbol, risk_ok, risk_reason, position)

        final_decision = ai_result.decision if ai_result.decision in {"LONG", "SHORT"} else "NO_TRADE"
        execution_reason = risk_reason
        executed_order = None

        if current_position != 0:
            final_decision = "NO_TRADE"
            execution_reason = "existing_position_open"
            executed_order = None
        elif not validation.passed or not news_sentiment.passed or not risk_ok or not ai_result.passed_level_1:
            final_decision = "NO_TRADE"
            if not news_sentiment.passed:
                execution_reason = f"news_sentiment_rejection: {news_sentiment.rejection_reason}"
        elif execute and self.allow_execution and position:
            side = "buy" if ai_result.decision == "LONG" else "sell"
            order_request = OrderRequest(
                symbol=symbol,
                qty=position.shares,
                side=side,
                order_type=OrderType.MARKET,
                time_in_force=TimeInForce.DAY,
                stop_loss=StopLoss(position.stop_loss_price),
            )
            approved, execution_reason, executed_order = await self.execution_service.execute_trade(
                request=order_request,
                position_size_from_risk=position.shares,
                entry_price_estimate=price,
                has_passed_all_checks=True,
            )
            if not approved:
                final_decision = "NO_TRADE"

        self._record_final(
            symbol,
            final_decision,
            execution_reason,
            {
                "validation_passed": validation.passed,
                "news_sentiment_passed": news_sentiment.passed,
                "news_risk_level": news_sentiment.risk_level,
                "risk_ok": risk_ok,
                "execute_requested": execute,
                "execution_allowed": self.allow_execution,
            },
        )

        return TradingDecision(
            symbol=symbol,
            final_decision=final_decision,
            price=price,
            volume_24h=volume_24h,
            indicators=indicators,
            validation=validation,
            search_signals=search_signals,
            news_sentiment=news_sentiment,
            guide_evaluation=guide_eval,
            ai_result=ai_result,
            risk_position=position if risk_ok else None,
            risk_reason=risk_reason,
            executed_order=executed_order,
            execution_reason=execution_reason,
        )

    def _current_position(self, symbol: str) -> int:
        if not self.session:
            return 0
        orders = (
            self.session.query(OrderLog)
            .filter(OrderLog.symbol == symbol)
            .order_by(OrderLog.created_at.desc())
            .all()
        )
        if not orders:
            return 0
        outcomes = self.session.query(TradeOutcomeLog).filter(TradeOutcomeLog.symbol == symbol).all()
        outcome_by_order = {o.order_id: o for o in outcomes}
        qty = 0
        for order in orders:
            if order.order_id in outcome_by_order and outcome_by_order[order.order_id].outcome == "closed":
                continue
            direction = 1 if order.side.lower() == "buy" else -1
            qty += direction * (order.filled_qty or order.qty)
        return qty

    async def _load_market_data(self, symbol: str) -> tuple[Sequence[Candle], Candle] | None:
        timeframe = "1Min"
        start = (datetime.now(timezone.utc) - timedelta(hours=8)).isoformat()
        try:
            bars = await self.market_data_client.historical_bars(symbol, timeframe, start=start, limit=400)
            if not bars:
                latest = await self.market_data_client.latest_bar(symbol, timeframe=timeframe)
                return ([latest], latest)
            return bars, bars[-1]
        except Exception:
            return None

    async def _load_search_signals(self, symbol: str) -> Mapping[str, Any]:
        try:
            signals = await self.search_client.search(
                f"{symbol} stock news",
                freshness="pd",
                count=15,
                result_filter="news,discussions,web",
            )
            return asdict(signals)
        except Exception:
            return {}

    def _evaluate_guide(
        self,
        strategy: str | None,
        search_signals: Mapping[str, Any],
    ) -> tuple[Guide | None, GuideEvaluation | None]:
        if not strategy or not self.guide_service or not self.session:
            return None, None
        stmt = (
            select(Guide)
            .join(StrategyGuideLink, StrategyGuideLink.guide_id == Guide.id)
            .where(StrategyGuideLink.strategy == strategy, Guide.is_active.is_(True))
            .order_by(Guide.id.desc())
        )
        guide = self.session.scalars(stmt).first()
        if not guide:
            return None, None
        categories = search_signals.get("matched_categories") or []
        guide_eval = self.guide_service.evaluate(guide, categories)
        return guide, guide_eval

    def _compute_indicators(self, bars: Sequence[Candle]) -> dict[str, float]:
        frame = self._candles_to_frame(bars)
        indicators: dict[str, float] = {}
        try:
            indicators["vwap"] = float(vwap(frame).iloc[-1])
        except Exception:
            pass
        try:
            indicators["atr"] = float(atr(frame).iloc[-1])
        except Exception:
            pass
        try:
            indicators["rsi"] = float(rsi(frame).iloc[-1])
        except Exception:
            pass
        try:
            indicators["ema_21"] = float(ema(frame, 21).iloc[-1])
        except Exception:
            pass
        try:
            indicators["ema_50"] = float(ema(frame, 50).iloc[-1])
        except Exception:
            pass
        return indicators

    def _candles_to_frame(self, bars: Sequence[Candle]) -> pd.DataFrame:
        data = {
            "open": [c.open for c in bars],
            "high": [c.high for c in bars],
            "low": [c.low for c in bars],
            "close": [c.close for c in bars],
            "volume": [c.volume for c in bars],
        }
        return pd.DataFrame(data)

    def _record_validation(self, symbol: str, validation: ValidationResult) -> None:
        log_decision(symbol, "validation", "PASSED" if validation.passed else "FAILED", "validation_run", metadata={"hard": list(validation.hard_rule_violations), "soft": list(validation.soft_warnings)})
        if self.audit_logger:
            self.audit_logger.record_rule_check(symbol, "validation", validation.passed, {"hard": list(validation.hard_rule_violations), "soft": list(validation.soft_warnings)})

    def _record_risk(self, symbol: str, passed: bool, reason: str, position: PositionSize | None) -> None:
        log_decision(symbol, "risk", "PASSED" if passed else "FAILED", reason, metadata={"position": asdict(position) if position else {}})
        if self.audit_logger:
            self.audit_logger.record_rule_check(symbol, "risk", passed, {"reason": reason, "position": asdict(position) if position else {}})

    def _record_final(self, symbol: str, decision: str, reason: str, context: Mapping[str, Any]) -> None:
        log_decision(symbol, "final_decision", decision, reason, metadata=context)
        if self.audit_logger:
            self.audit_logger.record_decision(symbol, "final_decision", decision, reason, context=context)

    def _empty_ai_result(self, symbol: str) -> AIEvaluationResult:
        return AIEvaluationResult(
            symbol=symbol,
            passed_level_1=False,
            decision="NO_TRADE",
            confidence=0.0,
            guide_alignment=False,
            weak_conditions=(),
            matched_rules=(),
            violated_rules=(),
        )


def build_trading_orchestrator(
    settings: Settings,
    session: Session,
    allow_execution: bool | None = None,
    budget: float | None = None,
) -> TradingOrchestrator:
    ai_client = AIClient(settings.ai_api_key, model=settings.ai_model)
    search_client = WebSearchClient(settings.search_api_key)
    provider = str(os.environ.get("MARKET_DATA_PROVIDER", "hybrid")).strip().lower()
    alpaca_client = MarketDataClient(settings.alpaca_api_key, settings.alpaca_secret_key)
    yahoo_client = YahooMarketDataClient()
    if provider == "alpaca":
        market_data_client = alpaca_client
    elif provider == "yahoo":
        market_data_client = yahoo_client
    else:
        market_data_client = HybridMarketDataClient(alpaca_client=alpaca_client, yahoo_client=yahoo_client)
    audit_logger = AuditLogger(session)
    guide_service = GuideService()
    validation_service = ValidationService()
    news_sentiment_evaluator = NewsSentimentEvaluator(audit_logger=audit_logger)
    account_size = budget if budget and budget > 0 else 100_000.0
    risk_governor = RiskGovernor(account_size=account_size)
    execution_client = AlpacaExecutionClient(
        api_key=settings.alpaca_api_key,
        secret_key=settings.alpaca_secret_key,
        trading_mode=settings.trading_mode,
        live_trading_confirmed=settings.trading_live_confirm,
    )
    execution_service = ExecutionService(execution_client, audit_logger=audit_logger)
    ai_service = AIEvaluationService(ai_client, audit_logger=audit_logger)
    enabled = False if allow_execution is None else allow_execution
    return TradingOrchestrator(
        market_data_client=market_data_client,
        search_client=search_client,
        ai_service=ai_service,
        validation_service=validation_service,
        news_sentiment_evaluator=news_sentiment_evaluator,
        risk_governor=risk_governor,
        execution_service=execution_service,
        guide_service=guide_service,
        session=session,
        audit_logger=audit_logger,
        allow_execution=enabled,
    )
