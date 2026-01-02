from __future__ import annotations

from sqlalchemy import Boolean, Column, DateTime, Integer, String, func

from .db import Base


class Symbol(Base):
    __tablename__ = "symbols"

    id = Column(Integer, primary_key=True)
    symbol = Column(String(16), nullable=False, unique=True)
    enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
