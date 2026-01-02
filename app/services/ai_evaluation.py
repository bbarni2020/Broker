from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from app.ai import AIClient, AIDecision
from app.logging import log_decision
from app.models import Guide
from app.services.guides import GuideEvaluation
from app.utils import ValidationResult


@dataclass(frozen=True)
class AIEvaluationResult:
    symbol: str
    passed_level_1: bool
    decision: str
    confidence: float
    guide_alignment: bool
    weak_conditions: Sequence[str]
    matched_rules: Sequence[str]
    violated_rules: Sequence[str]


class AIEvaluationService:
    def __init__(
        self,
        ai_client: AIClient,
        confidence_threshold: float = 0.7,
    ) -> None:
        self.ai_client = ai_client
        self.confidence_threshold = confidence_threshold

    async def evaluate(
        self,
        symbol: str,
        validation_result: ValidationResult,
        guide: Guide | None,
        guide_evaluation: GuideEvaluation | None,
        search_signals: Mapping[str, Any] | None,
        price: float,
        volume_24h: float,
        indicators: Mapping[str, float] | None,
    ) -> AIEvaluationResult:
        if not validation_result.passed:
            log_decision(
                symbol,
                "level_1_rejection",
                "NO_TRADE",
                f"Failed validation: {', '.join(validation_result.hard_rule_violations)}",
                metadata={"violations": list(validation_result.hard_rule_violations)},
            )
            return AIEvaluationResult(
                symbol=symbol,
                passed_level_1=False,
                decision="NO_TRADE",
                confidence=0.0,
                guide_alignment=False,
                weak_conditions=validation_result.hard_rule_violations,
                matched_rules=(),
                violated_rules=(),
            )

        ai_payload = self._build_payload(
            symbol, guide_evaluation, search_signals, price, volume_24h, indicators
        )

        try:
            ai_decision = await self.ai_client.classify(ai_payload)
        except Exception as exc:
            log_decision(
                symbol,
                "ai_error",
                "NO_TRADE",
                f"AI service error: {str(exc)}",
            )
            raise RuntimeError(f"AI evaluation failed for {symbol}") from exc

        guide_aligned = guide_evaluation.allowed if guide_evaluation else True
        weak_conditions = self._identify_weak_conditions(ai_decision, guide_evaluation)
        rejected_by_confidence = ai_decision.confidence < self.confidence_threshold

        passed = (
            guide_aligned
            and ai_decision.decision in ("LONG", "SHORT")
            and not rejected_by_confidence
        )

        log_decision(
            symbol,
            "level_2_evaluation",
            ai_decision.decision if passed else "NO_TRADE",
            f"AI decision with {ai_decision.confidence:.2%} confidence",
            confidence=ai_decision.confidence,
            metadata={
                "guide_aligned": guide_aligned,
                "passed_threshold": not rejected_by_confidence,
                "weak_conditions": weak_conditions,
                "matched_rules": list(ai_decision.matched_rules),
                "violated_rules": list(ai_decision.violated_rules),
                "risk_flags": list(ai_decision.risk_flags),
            },
        )

        return AIEvaluationResult(
            symbol=symbol,
            passed_level_1=True,
            decision=ai_decision.decision if passed else "NO_TRADE",
            confidence=ai_decision.confidence,
            guide_alignment=guide_aligned,
            weak_conditions=tuple(weak_conditions),
            matched_rules=ai_decision.matched_rules,
            violated_rules=ai_decision.violated_rules,
        )

    def _build_payload(
        self,
        symbol: str,
        guide_eval: GuideEvaluation | None,
        search_signals: Mapping[str, Any] | None,
        price: float,
        volume_24h: float,
        indicators: Mapping[str, float] | None,
    ) -> Mapping[str, Any]:
        guide_context = {}
        if guide_eval:
            guide_context = {
                "guide_allowed": guide_eval.allowed,
                "matched_soft_rules": list(guide_eval.matched_soft_rules),
                "unmet_hard_rules": list(guide_eval.unmet_hard_rules),
                "disqualifiers": list(guide_eval.disqualifiers),
            }

        search_context = search_signals or {}

        indicator_context = indicators or {}

        return {
            "symbol": symbol,
            "price": price,
            "volume_24h": volume_24h,
            "guide_context": guide_context,
            "search_signals": search_context,
            "indicators": indicator_context,
        }

    def _identify_weak_conditions(
        self,
        ai_decision: AIDecision,
        guide_eval: GuideEvaluation | None,
    ) -> list[str]:
        weak = []

        if ai_decision.confidence < 0.8:
            weak.append(f"low_confidence_{ai_decision.confidence:.2%}")

        if guide_eval and guide_eval.unmet_hard_rules:
            weak.append(f"unmet_rules_{len(guide_eval.unmet_hard_rules)}")

        if ai_decision.risk_flags:
            weak.extend(ai_decision.risk_flags)

        return weak
