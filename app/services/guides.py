from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Guide, StrategyGuideLink


@dataclass(frozen=True)
class GuidePayload:
    name: str
    version: str
    description: str
    hard_rules: Sequence[str]
    soft_rules: Sequence[str]
    disqualifiers: Sequence[str]


@dataclass(frozen=True)
class GuideEvaluation:
    allowed: bool
    unmet_hard_rules: Sequence[str]
    matched_soft_rules: Sequence[str]
    disqualifiers: Sequence[str]


class GuideService:
    def create(self, session: Session, payload: GuidePayload) -> Guide:
        self._validate_payload(payload)
        guide = Guide(
            name=payload.name,
            version=payload.version,
            description=payload.description,
            hard_rules=list(payload.hard_rules),
            soft_rules=list(payload.soft_rules),
            disqualifiers=list(payload.disqualifiers),
            is_active=True,
        )
        session.add(guide)
        try:
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            raise ValueError("Guide version already exists") from exc
        session.refresh(guide)
        return guide

    def attach_to_strategy(self, session: Session, guide_id: int, strategy: str) -> StrategyGuideLink:
        if not strategy or not isinstance(strategy, str):
            raise ValueError("Strategy must be a non-empty string")
        link = StrategyGuideLink(guide_id=guide_id, strategy=strategy)
        session.add(link)
        session.commit()
        session.refresh(link)
        return link

    def get(self, session: Session, guide_id: int) -> Guide | None:
        stmt = select(Guide).where(Guide.id == guide_id)
        return session.scalars(stmt).first()

    def get_by_name_version(self, session: Session, name: str, version: str) -> Guide | None:
        stmt = select(Guide).where(Guide.name == name, Guide.version == version)
        return session.scalars(stmt).first()

    def evaluate(self, guide: Guide, signals: Iterable[str]) -> GuideEvaluation:
        signal_set = {s for s in signals if isinstance(s, str)}
        unmet_hard = [rule for rule in guide.hard_rules if rule not in signal_set]
        disqualified = [rule for rule in guide.disqualifiers if rule in signal_set]
        soft = [rule for rule in guide.soft_rules if rule in signal_set]
        allowed = len(unmet_hard) == 0 and len(disqualified) == 0 and guide.is_active
        return GuideEvaluation(
            allowed=allowed,
            unmet_hard_rules=tuple(unmet_hard),
            matched_soft_rules=tuple(soft),
            disqualifiers=tuple(disqualified),
        )

    def _validate_payload(self, payload: GuidePayload) -> None:
        for field_name in ("name", "version", "description"):
            value = getattr(payload, field_name)
            if not value or not isinstance(value, str):
                raise ValueError(f"{field_name} must be a non-empty string")
        for field_name in ("hard_rules", "soft_rules", "disqualifiers"):
            value = getattr(payload, field_name)
            if not isinstance(value, Sequence) or any(not isinstance(v, str) or not v for v in value):
                raise ValueError(f"{field_name} must be a sequence of non-empty strings")
        if len(payload.hard_rules) == 0:
            raise ValueError("At least one hard rule is required")
