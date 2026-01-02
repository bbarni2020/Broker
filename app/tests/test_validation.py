from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pandas as pd

from app.utils import ValidationResult, ValidationService


class ValidationServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = ValidationService(
            liquidity_threshold=1_000_000.0, min_bars_for_indicators=50
        )

    def test_passes_valid_trade(self) -> None:
        result = self.service.validate(
            symbol="AAPL",
            current_price=150.0,
            volume_24h=5_000_000.0,
            latest_bars=pd.DataFrame({"close": range(100)}),
            market_regime="bullish",
            has_earnings_today=False,
            has_fda_event=False,
            is_trading_halted=False,
        )
        self.assertTrue(result.passed)
        self.assertEqual(result.hard_rule_violations, ())

    def test_rejects_low_liquidity(self) -> None:
        result = self.service.validate(
            symbol="PENNY",
            current_price=1.0,
            volume_24h=100_000.0,
            latest_bars=pd.DataFrame({"close": range(100)}),
            market_regime="normal",
            has_earnings_today=False,
            has_fda_event=False,
            is_trading_halted=False,
        )
        self.assertFalse(result.passed)
        self.assertIn("insufficient_liquidity", result.hard_rule_violations)

    def test_rejects_halt(self) -> None:
        result = self.service.validate(
            symbol="HALT",
            current_price=50.0,
            volume_24h=2_000_000.0,
            latest_bars=pd.DataFrame({"close": range(100)}),
            market_regime="normal",
            has_earnings_today=False,
            has_fda_event=False,
            is_trading_halted=True,
        )
        self.assertFalse(result.passed)
        self.assertIn("trading_halted", result.hard_rule_violations)

    def test_rejects_earnings_blackout(self) -> None:
        result = self.service.validate(
            symbol="EARN",
            current_price=100.0,
            volume_24h=2_000_000.0,
            latest_bars=pd.DataFrame({"close": range(100)}),
            market_regime="normal",
            has_earnings_today=True,
            has_fda_event=False,
            is_trading_halted=False,
        )
        self.assertFalse(result.passed)
        self.assertIn("blackout_window", result.hard_rule_violations)

    def test_rejects_fda_blackout(self) -> None:
        result = self.service.validate(
            symbol="FDA",
            current_price=100.0,
            volume_24h=2_000_000.0,
            latest_bars=pd.DataFrame({"close": range(100)}),
            market_regime="normal",
            has_earnings_today=False,
            has_fda_event=True,
            is_trading_halted=False,
        )
        self.assertFalse(result.passed)
        self.assertIn("blackout_window", result.hard_rule_violations)

    def test_rejects_insufficient_bars(self) -> None:
        result = self.service.validate(
            symbol="LOW",
            current_price=100.0,
            volume_24h=2_000_000.0,
            latest_bars=pd.DataFrame({"close": range(20)}),
            market_regime="normal",
            has_earnings_today=False,
            has_fda_event=False,
            is_trading_halted=False,
        )
        self.assertFalse(result.passed)
        self.assertIn("insufficient_bars_for_indicators", result.hard_rule_violations)

    def test_rejects_none_bars(self) -> None:
        result = self.service.validate(
            symbol="NONE",
            current_price=100.0,
            volume_24h=2_000_000.0,
            latest_bars=None,
            market_regime="normal",
            has_earnings_today=False,
            has_fda_event=False,
            is_trading_halted=False,
        )
        self.assertFalse(result.passed)
        self.assertIn("insufficient_bars_for_indicators", result.hard_rule_violations)

    def test_rejects_invalid_symbol(self) -> None:
        result = self.service.validate(
            symbol="",
            current_price=100.0,
            volume_24h=2_000_000.0,
            latest_bars=pd.DataFrame({"close": range(100)}),
            market_regime="normal",
            has_earnings_today=False,
            has_fda_event=False,
            is_trading_halted=False,
        )
        self.assertFalse(result.passed)
        self.assertIn("insufficient_liquidity", result.hard_rule_violations)

    def test_rejects_negative_volume(self) -> None:
        result = self.service.validate(
            symbol="NEG",
            current_price=100.0,
            volume_24h=-100.0,
            latest_bars=pd.DataFrame({"close": range(100)}),
            market_regime="normal",
            has_earnings_today=False,
            has_fda_event=False,
            is_trading_halted=False,
        )
        self.assertFalse(result.passed)
        self.assertIn("insufficient_liquidity", result.hard_rule_violations)

    def test_rejects_invalid_price(self) -> None:
        result = self.service.validate(
            symbol="ZERO",
            current_price=0.0,
            volume_24h=2_000_000.0,
            latest_bars=pd.DataFrame({"close": range(100)}),
            market_regime="normal",
            has_earnings_today=False,
            has_fda_event=False,
            is_trading_halted=False,
        )
        self.assertFalse(result.passed)
        self.assertIn("invalid_price", result.hard_rule_violations)

    def test_warns_on_crash_regime(self) -> None:
        result = self.service.validate(
            symbol="CRA",
            current_price=100.0,
            volume_24h=2_000_000.0,
            latest_bars=pd.DataFrame({"close": range(100)}),
            market_regime="crash",
            has_earnings_today=False,
            has_fda_event=False,
            is_trading_halted=False,
        )
        self.assertTrue(result.passed)
        self.assertIn("regime_warning", result.soft_warnings)

    def test_threshold_boundary(self) -> None:
        result = self.service.validate(
            symbol="BOUND",
            current_price=100.0,
            volume_24h=1_000_000.0,
            latest_bars=pd.DataFrame({"close": range(100)}),
            market_regime="normal",
            has_earnings_today=False,
            has_fda_event=False,
            is_trading_halted=False,
        )
        self.assertTrue(result.passed)
        result_below = self.service.validate(
            symbol="BOUND",
            current_price=100.0,
            volume_24h=999_999.0,
            latest_bars=pd.DataFrame({"close": range(100)}),
            market_regime="normal",
            has_earnings_today=False,
            has_fda_event=False,
            is_trading_halted=False,
        )
        self.assertFalse(result_below.passed)

    def test_min_bars_threshold(self) -> None:
        result = self.service.validate(
            symbol="EXACT",
            current_price=100.0,
            volume_24h=2_000_000.0,
            latest_bars=pd.DataFrame({"close": range(50)}),
            market_regime="normal",
            has_earnings_today=False,
            has_fda_event=False,
            is_trading_halted=False,
        )
        self.assertTrue(result.passed)
        result_below = self.service.validate(
            symbol="EXACT",
            current_price=100.0,
            volume_24h=2_000_000.0,
            latest_bars=pd.DataFrame({"close": range(49)}),
            market_regime="normal",
            has_earnings_today=False,
            has_fda_event=False,
            is_trading_halted=False,
        )
        self.assertFalse(result_below.passed)

    def test_bars_as_sequence(self) -> None:
        bars = [{"close": 100}, {"close": 101}] * 30
        result = self.service.validate(
            symbol="SEQ",
            current_price=100.0,
            volume_24h=2_000_000.0,
            latest_bars=bars,
            market_regime="normal",
            has_earnings_today=False,
            has_fda_event=False,
            is_trading_halted=False,
        )
        self.assertTrue(result.passed)

    def test_multiple_violations(self) -> None:
        result = self.service.validate(
            symbol="MULTI",
            current_price=-50.0,
            volume_24h=100_000.0,
            latest_bars=pd.DataFrame({"close": range(10)}),
            market_regime="normal",
            has_earnings_today=True,
            has_fda_event=False,
            is_trading_halted=True,
        )
        self.assertFalse(result.passed)
        self.assertEqual(len(result.hard_rule_violations), 5)
        self.assertIn("invalid_price", result.hard_rule_violations)
        self.assertIn("insufficient_liquidity", result.hard_rule_violations)
        self.assertIn("blackout_window", result.hard_rule_violations)
        self.assertIn("trading_halted", result.hard_rule_violations)
        self.assertIn("insufficient_bars_for_indicators", result.hard_rule_violations)


if __name__ == "__main__":
    unittest.main()
