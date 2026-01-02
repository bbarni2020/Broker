from __future__ import annotations

from sqlalchemy import Boolean, Column, ForeignKey, Integer, String, UniqueConstraint, JSON
from sqlalchemy.orm import relationship

from app.models.db import Base


class Guide(Base):
    __tablename__ = "guides"
    __table_args__ = (UniqueConstraint("name", "version", name="uq_guide_name_version"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    version = Column(String, nullable=False)
    description = Column(String, nullable=False)
    hard_rules = Column(JSON, nullable=False)
    soft_rules = Column(JSON, nullable=False)
    disqualifiers = Column(JSON, nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)

    strategy_links = relationship("StrategyGuideLink", back_populates="guide", cascade="all, delete-orphan")


class StrategyGuideLink(Base):
    __tablename__ = "strategy_guides"
    id = Column(Integer, primary_key=True, autoincrement=True)
    guide_id = Column(Integer, ForeignKey("guides.id", ondelete="CASCADE"), nullable=False)
    strategy = Column(String, nullable=False)

    guide = relationship("Guide", back_populates="strategy_links")
