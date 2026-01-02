from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

import pyotp
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.auth import AuthError, AuthService, RateLimiter
from app.models import Base


class AuthSecurityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        self.service = AuthService(
            self.session,
            jwt_secret="secret",
            session_ttl_seconds=1,
            max_failed_attempts=3,
            lockout_minutes=1,
            rate_limiter=RateLimiter(5, 300),
        )

    def tearDown(self) -> None:
        self.session.close()
        self.engine.dispose()

    def test_password_hash_and_otp_login(self) -> None:
        user, _ = self.service.register_user("user@example.com", "StrongPass123", role="admin")
        code = pyotp.TOTP(user.otp_secret).now()
        token = self.service.authenticate("user@example.com", "StrongPass123", otp_code=code)
        self.assertIsInstance(token, str)
        payload = self.service.verify_token(token)
        self.assertEqual(payload["role"], "admin")

    def test_token_expiry(self) -> None:
        user, _ = self.service.register_user("expire@example.com", "Password1!")
        past = datetime.now(timezone.utc) - timedelta(seconds=120)
        token = self.service.issue_token_for_user(user, past)
        with self.assertRaises(AuthError):
            self.service.verify_token(token)

    def test_bruteforce_lockout(self) -> None:
        user, _ = self.service.register_user("lock@example.com", "Password1!")
        for _ in range(3):
            with self.assertRaises(AuthError):
                self.service.authenticate("lock@example.com", "bad", otp_code="000000")
        self.assertIsNotNone(self.session.query(type(user)).filter_by(email="lock@example.com").first().locked_until)
        code = pyotp.TOTP(user.otp_secret).now()
        with self.assertRaises(AuthError):
            self.service.authenticate("lock@example.com", "Password1!", otp_code=code)

    def test_recovery_codes(self) -> None:
        user, recovery_codes = self.service.register_user("recover@example.com", "Password1!")
        token = self.service.authenticate("recover@example.com", "Password1!", recovery_code=recovery_codes[0])
        self.assertIsInstance(token, str)
        with self.assertRaises(AuthError):
            self.service.authenticate("recover@example.com", "Password1!", recovery_code=recovery_codes[0])

    def test_rate_limit_blocks(self) -> None:
        limiter = RateLimiter(2, 300)
        limited_service = AuthService(
            self.session,
            jwt_secret="secret",
            session_ttl_seconds=60,
            max_failed_attempts=10,
            lockout_minutes=1,
            rate_limiter=limiter,
        )
        limited_service.register_user("limit@example.com", "Password1!")
        with self.assertRaises(AuthError):
            limited_service.authenticate("limit@example.com", "Password1!", otp_code="000000")
        with self.assertRaises(AuthError):
            limited_service.authenticate("limit@example.com", "Password1!", otp_code="000000")
        with self.assertRaises(AuthError):
            limited_service.authenticate("limit@example.com", "Password1!", otp_code="000000")


if __name__ == "__main__":
    unittest.main()
