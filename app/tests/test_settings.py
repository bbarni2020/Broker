from __future__ import annotations

import unittest

from app.config.settings import REQUIRED_ENV_VARS, Settings, load_settings


class SettingsTests(unittest.TestCase):
    def test_load_settings_raises_on_missing(self) -> None:
        env = {key: "" for key in REQUIRED_ENV_VARS}
        with self.assertRaises(RuntimeError):
            load_settings(env)

    def test_load_settings_populates_fields(self) -> None:
        env = {
            "DATABASE_URL": "postgresql+psycopg://user:pass@localhost:5432/db",
            "AI_API_KEY": "test-ai-key",
            "SEARCH_API_KEY": "test-search-key",
            "ALPACA_API_KEY": "alpaca-key",
            "ALPACA_SECRET_KEY": "alpaca-secret",
            "JWT_SECRET": "jwt-secret",
            "OTP_ISSUER_NAME": "BrokerApp",
            "APP_ENV": "test",
        }

        settings = load_settings(env)

        self.assertIsInstance(settings, Settings)
        self.assertEqual(settings.database_url, env["DATABASE_URL"])
        self.assertEqual(settings.ai_api_key, env["AI_API_KEY"])
        self.assertEqual(settings.search_api_key, env["SEARCH_API_KEY"])
        self.assertEqual(settings.alpaca_api_key, env["ALPACA_API_KEY"])
        self.assertEqual(settings.alpaca_secret_key, env["ALPACA_SECRET_KEY"])
        self.assertEqual(settings.jwt_secret, env["JWT_SECRET"])
        self.assertEqual(settings.otp_issuer_name, env["OTP_ISSUER_NAME"])
        self.assertEqual(settings.app_env, env["APP_ENV"])


if __name__ == "__main__":
    unittest.main()
