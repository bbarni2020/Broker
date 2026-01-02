from __future__ import annotations

from sqlalchemy import Column, DateTime, Integer, String, UniqueConstraint, JSON, func

from .db import Base


class User(Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("email", name="uq_users_email"),)

    id = Column(Integer, primary_key=True)
    email = Column(String(255), nullable=False)
    password_hash = Column(String, nullable=False)
    role = Column(String(16), nullable=False, default="viewer")
    otp_secret = Column(String(64), nullable=False)
    otp_recovery_codes = Column(JSON, nullable=False, default=list)
    failed_attempts = Column(Integer, nullable=False, default=0)
    locked_until = Column(DateTime(timezone=True))
    last_login = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
