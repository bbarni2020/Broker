from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Sequence

import jwt
import pyotp
from passlib.hash import argon2
from sqlalchemy.orm import Session

from app.models import User


class AuthError(Exception):
    pass


class RateLimiter:
    def __init__(self, max_attempts: int, window_seconds: int) -> None:
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._attempts: dict[str, list[datetime]] = {}

    def allow(self, key: str, now: datetime) -> bool:
        items = self._attempts.get(key, [])
        cutoff = now - timedelta(seconds=self.window_seconds)
        filtered = [ts for ts in items if ts >= cutoff]
        if len(filtered) >= self.max_attempts:
            self._attempts[key] = filtered
            return False
        filtered.append(now)
        self._attempts[key] = filtered
        return True

    def reset(self, key: str) -> None:
        self._attempts.pop(key, None)


class AuthService:
    def __init__(
        self,
        session: Session,
        jwt_secret: str,
        session_ttl_seconds: int = 3600,
        max_failed_attempts: int = 5,
        lockout_minutes: int = 15,
        rate_limiter: RateLimiter | None = None,
    ) -> None:
        self.session = session
        self.jwt_secret = jwt_secret
        self.session_ttl_seconds = session_ttl_seconds
        self.max_failed_attempts = max_failed_attempts
        self.lockout_minutes = lockout_minutes
        self.rate_limiter = rate_limiter or RateLimiter(10, 60)

    def register_user(self, email: str, password: str, role: str = "viewer") -> tuple[User, list[str]]:
        normalized_email = email.strip().lower()
        if role not in ("admin", "viewer"):
            raise AuthError("invalid_role")
        existing = self.session.query(User).filter_by(email=normalized_email).first()
        if existing:
            raise AuthError("user_exists")
        otp_secret = pyotp.random_base32()
        recovery_codes_plain = self._generate_recovery_codes()
        recovery_codes_hashed = [self._hash_value(code) for code in recovery_codes_plain]
        user = User(
            email=normalized_email,
            password_hash=self._hash_value(password),
            role=role,
            otp_secret=otp_secret,
            otp_recovery_codes=recovery_codes_hashed,
        )
        self.session.add(user)
        self.session.commit()
        self.session.refresh(user)
        return user, recovery_codes_plain

    def authenticate(
        self,
        email: str,
        password: str,
        otp_code: str | None = None,
        recovery_code: str | None = None,
        now: datetime | None = None,
    ) -> str:
        moment = now or datetime.now(timezone.utc)
        if not self.rate_limiter.allow(email, moment):
            raise AuthError("rate_limited")
        user = self.session.query(User).filter_by(email=email.strip().lower()).first()
        if not user:
            raise AuthError("invalid_credentials")
        locked_until = self._normalize_time(user.locked_until)
        if locked_until and locked_until > moment:
            raise AuthError("locked")
        if not self._verify_password(password, user.password_hash):
            self._register_failure(user, moment)
            raise AuthError("invalid_credentials")
        if recovery_code:
            if not self._consume_recovery_code(user, recovery_code):
                self._register_failure(user, moment)
                raise AuthError("invalid_recovery_code")
        else:
            if not otp_code:
                self._register_failure(user, moment)
                raise AuthError("otp_required")
            totp = pyotp.TOTP(user.otp_secret)
            if not totp.verify(otp_code, valid_window=1, for_time=moment):
                self._register_failure(user, moment)
                raise AuthError("otp_invalid")
        self._reset_failures(user)
        user.last_login = moment
        self.session.commit()
        token = self.issue_token_for_user(user, moment)
        return token

    def issue_token_for_user(self, user: User, now: datetime | None = None) -> str:
        moment = now or datetime.now(timezone.utc)
        exp = moment + timedelta(seconds=self.session_ttl_seconds)
        payload = {"sub": str(user.id), "role": user.role, "exp": exp, "iat": moment}
        return jwt.encode(payload, self.jwt_secret, algorithm="HS256")

    def verify_token(self, token: str) -> dict:
        try:
            payload = jwt.decode(token, self.jwt_secret, algorithms=["HS256"])
        except jwt.ExpiredSignatureError as exc:
            raise AuthError("token_expired") from exc
        except jwt.InvalidTokenError as exc:
            raise AuthError("invalid_token") from exc
        return payload

    def authorize(self, token: str, required_role: str) -> bool:
        payload = self.verify_token(token)
        role = payload.get("role")
        if required_role == "viewer":
            return role in ("viewer", "admin")
        if required_role == "admin":
            return role == "admin"
        raise AuthError("invalid_role")

    def _register_failure(self, user: User, moment: datetime) -> None:
        user.failed_attempts += 1
        if user.failed_attempts >= self.max_failed_attempts:
            user.locked_until = moment + timedelta(minutes=self.lockout_minutes)
        self.session.commit()

    def _reset_failures(self, user: User) -> None:
        user.failed_attempts = 0
        user.locked_until = None
        self.session.commit()

    def _verify_password(self, password: str, password_hash: str) -> bool:
        return argon2.verify(password, password_hash)

    def _hash_value(self, value: str) -> str:
        return argon2.hash(value)

    def _generate_recovery_codes(self, count: int = 5) -> list[str]:
        return [secrets.token_hex(4) for _ in range(count)]

    def _consume_recovery_code(self, user: User, code: str) -> bool:
        remaining: list[str] = []
        matched = False
        for stored in user.otp_recovery_codes:
            if not matched and argon2.verify(code, stored):
                matched = True
                continue
            remaining.append(stored)
        if matched:
            user.otp_recovery_codes = remaining
            self.session.commit()
        return matched

    def _normalize_time(self, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value