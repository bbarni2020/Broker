from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from app.logging import AuditLogger, log_decision


@dataclass(frozen=True)
class NewsSentimentResult:
    symbol: str
    passed: bool
    risk_level: str
    rejection_reason: str
    signals_detected: Sequence[str]
    total_mentions: int
    sentiment_score: float


class NewsSentimentEvaluator:
    def __init__(
        self,
        audit_logger: AuditLogger | None = None,
        max_negative_signals: int = 2,
        min_confidence_override: float = 0.85,
    ) -> None:
        self.audit_logger = audit_logger
        self.max_negative_signals = max_negative_signals
        self.min_confidence_override = min_confidence_override

    def evaluate(
        self,
        symbol: str,
        search_signals: Mapping[str, Any],
    ) -> NewsSentimentResult:
        signals_detected = list(search_signals.get("matched_categories", []))
        total_results = int(search_signals.get("total_results", 0))
        
        negative_signals = []
        neutral_signals = []
        positive_signals = []

        if search_signals.get("lawsuits"):
            negative_signals.append("lawsuits")
        if search_signals.get("fda") and "fda" in signals_detected:
            neutral_signals.append("fda_event")
        if search_signals.get("earnings"):
            neutral_signals.append("earnings")
        if search_signals.get("macro"):
            neutral_signals.append("macro_event")
        if search_signals.get("unusual_mentions"):
            neutral_signals.append("unusual_activity")

        sentiment_score = self._calculate_sentiment(
            total_results,
            negative_signals,
            neutral_signals,
            positive_signals,
        )

        passed = True
        risk_level = "low"
        rejection_reason = ""

        if len(negative_signals) >= self.max_negative_signals:
            passed = False
            risk_level = "high"
            rejection_reason = f"multiple_negative_signals: {', '.join(negative_signals)}"
        elif len(negative_signals) > 0:
            risk_level = "medium"
            rejection_reason = f"negative_signal_detected: {', '.join(negative_signals)}"
        elif search_signals.get("earnings") and total_results > 20:
            risk_level = "medium"
            rejection_reason = "high_volume_earnings_news"
        elif total_results > 50:
            risk_level = "medium"
            rejection_reason = "excessive_news_volume"

        log_decision(
            symbol,
            "news_sentiment_level",
            "PASSED" if passed else "REJECTED",
            rejection_reason or "no_major_risks",
            metadata={
                "risk_level": risk_level,
                "signals": signals_detected,
                "negative": negative_signals,
                "neutral": neutral_signals,
                "total_mentions": total_results,
                "sentiment_score": sentiment_score,
            },
        )

        if self.audit_logger:
            self.audit_logger.record_rule_check(
                symbol,
                "news_sentiment",
                passed,
                {
                    "risk_level": risk_level,
                    "signals": signals_detected,
                    "negative_signals": negative_signals,
                    "neutral_signals": neutral_signals,
                    "total_mentions": total_results,
                    "sentiment_score": sentiment_score,
                    "rejection_reason": rejection_reason,
                },
            )

        return NewsSentimentResult(
            symbol=symbol,
            passed=passed,
            risk_level=risk_level,
            rejection_reason=rejection_reason or "no_major_risks",
            signals_detected=tuple(signals_detected),
            total_mentions=total_results,
            sentiment_score=sentiment_score,
        )

    def _calculate_sentiment(
        self,
        total_results: int,
        negative_signals: list[str],
        neutral_signals: list[str],
        positive_signals: list[str],
    ) -> float:
        if total_results == 0:
            return 0.5

        base_score = 0.5
        
        negative_weight = len(negative_signals) * -0.15
        neutral_weight = len(neutral_signals) * -0.05
        positive_weight = len(positive_signals) * 0.1

        volume_penalty = 0
        if total_results > 30:
            volume_penalty = -0.1
        elif total_results > 50:
            volume_penalty = -0.2

        sentiment = base_score + negative_weight + neutral_weight + positive_weight + volume_penalty
        
        return max(0.0, min(1.0, sentiment))
