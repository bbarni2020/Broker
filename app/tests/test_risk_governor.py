from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from app.services import PositionSize, RiskGovernor


class RiskGovernorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.governor = RiskGovernor(
            max_risk_per_trade=0.02,
            max_daily_loss=0.05,
            max_trades_per_day=5,
            cooldown_seconds=60,
            account_size=100_000.0,
        )

    def test_approves_valid_trade(self) -> None:
        approved, reason, position = self.governor.evaluate(
            symbol="AAPL",
            decision="LONG",
            confidence=0.8,
            price=150.0,
            atr=5.0,
        )
        self.assertTrue(approved)
        self.assertIsNotNone(position)
        self.assertGreater(position.shares, 0)
        self.assertEqual(position.risk_per_trade, 0.02 * 100_000.0)

    def test_rejects_no_trade_decision(self) -> None:
        approved, reason, position = self.governor.evaluate(
            symbol="XYZ",
            decision="NO_TRADE",
            confidence=0.0,
            price=100.0,
            atr=2.0,
        )
        self.assertTrue(approved)
        self.assertIsNone(position)

    def test_rejects_max_daily_loss(self) -> None:
        self.governor.state.daily_loss = 5_500.0
        approved, reason, position = self.governor.evaluate(
            symbol="LOSS",
            decision="LONG",
            confidence=0.75,
            price=100.0,
            atr=2.0,
        )
        self.assertFalse(approved)
        self.assertIn("daily loss", reason.lower())

    def test_rejects_max_trades_per_day(self) -> None:
        self.governor.state.trades_today = 5
        approved, reason, position = self.governor.evaluate(
            symbol="LIMIT",
            decision="LONG",
            confidence=0.8,
            price=100.0,
            atr=2.0,
        )
        self.assertFalse(approved)
        self.assertIn("trades per day", reason.lower())

    def test_enforces_cooldown(self) -> None:
        now = datetime.now(timezone.utc)
        self.governor.state.last_trade_timestamp = now - timedelta(seconds=30)

        approved, reason, position = self.governor.evaluate(
            symbol="COOL",
            decision="LONG",
            confidence=0.8,
            price=100.0,
            atr=2.0,
        )
        self.assertFalse(approved)
        self.assertIn("cooldown", reason.lower())

    def test_allows_trade_after_cooldown(self) -> None:
        now = datetime.now(timezone.utc)
        self.governor.state.last_trade_timestamp = now - timedelta(seconds=61)

        approved, reason, position = self.governor.evaluate(
            symbol="COOL",
            decision="LONG",
            confidence=0.8,
            price=100.0,
            atr=2.0,
        )
        self.assertTrue(approved)
        self.assertIsNotNone(position)

    def test_position_size_calculation(self) -> None:
        approved, reason, position = self.governor.evaluate(
            symbol="SIZE",
            decision="LONG",
            confidence=0.85,
            price=100.0,
            atr=4.0,
        )
        self.assertTrue(approved)
        self.assertEqual(position.notional, position.shares * 100.0)
        self.assertLess(position.stop_loss_price, 100.0)

    def test_stop_loss_distance(self) -> None:
        atr = 3.0
        price = 150.0
        approved, reason, position = self.governor.evaluate(
            symbol="SL",
            decision="LONG",
            confidence=0.8,
            price=price,
            atr=atr,
        )
        expected_sl = price - (atr * 2)
        self.assertEqual(position.stop_loss_price, expected_sl)

    def test_rejects_invalid_symbol(self) -> None:
        approved, reason, position = self.governor.evaluate(
            symbol="",
            decision="LONG",
            confidence=0.8,
            price=100.0,
            atr=2.0,
        )
        self.assertFalse(approved)

    def test_rejects_zero_price(self) -> None:
        approved, reason, position = self.governor.evaluate(
            symbol="ZERO",
            decision="LONG",
            confidence=0.8,
            price=0.0,
            atr=2.0,
        )
        self.assertFalse(approved)

    def test_rejects_negative_price(self) -> None:
        approved, reason, position = self.governor.evaluate(
            symbol="NEG",
            decision="LONG",
            confidence=0.8,
            price=-10.0,
            atr=2.0,
        )
        self.assertFalse(approved)

    def test_rejects_negative_atr(self) -> None:
        approved, reason, position = self.governor.evaluate(
            symbol="ATR",
            decision="LONG",
            confidence=0.8,
            price=100.0,
            atr=-1.0,
        )
        self.assertFalse(approved)

    def test_rejects_zero_atr(self) -> None:
        approved, reason, position = self.governor.evaluate(
            symbol="ZERO_ATR",
            decision="LONG",
            confidence=0.8,
            price=100.0,
            atr=0.0,
        )
        self.assertFalse(approved)

    def test_record_trade_increments_count(self) -> None:
        self.assertEqual(self.governor.state.trades_today, 0)
        self.governor.record_trade("AAPL", 0.0)
        self.assertEqual(self.governor.state.trades_today, 1)

    def test_record_trade_tracks_loss(self) -> None:
        self.assertEqual(self.governor.state.daily_loss, 0.0)
        self.governor.record_trade("AAPL", -500.0)
        self.assertEqual(self.governor.state.daily_loss, 500.0)

    def test_record_trade_ignores_profit(self) -> None:
        self.governor.record_trade("AAPL", 1000.0)
        self.assertEqual(self.governor.state.daily_loss, 0.0)

    def test_daily_reset_on_new_day(self) -> None:
        self.governor.state.trades_today = 5
        self.governor.state.daily_loss = 2500.0

        yesterday = datetime.now(timezone.utc) - timedelta(days=1)
        self.governor.state.daily_reset_time = yesterday.replace(hour=0, minute=0, second=0, microsecond=0)

        approved, reason, position = self.governor.evaluate(
            symbol="RESET",
            decision="LONG",
            confidence=0.8,
            price=100.0,
            atr=2.0,
        )
        self.assertTrue(approved)
        self.assertEqual(self.governor.state.trades_today, 0)

    def test_would_exceed_daily_loss_projection(self) -> None:
        self.governor.state.daily_loss = 4_900.0
        approved, reason, position = self.governor.evaluate(
            symbol="PROJ",
            decision="LONG",
            confidence=0.8,
            price=100.0,
            atr=2.0,
        )
        self.assertFalse(approved)
        self.assertIn("daily loss", reason.lower())

    def test_previous_loss_breach(self) -> None:
        approved, reason, position = self.governor.evaluate(
            symbol="PREV",
            decision="LONG",
            confidence=0.8,
            price=100.0,
            atr=2.0,
            previous_loss=6_000.0,
        )
        self.assertFalse(approved)

    def test_max_risk_per_trade_limit(self) -> None:
        governor = RiskGovernor(
            max_risk_per_trade=0.001,
            max_daily_loss=0.1,
            account_size=100_000.0,
        )
        approved, reason, position = governor.evaluate(
            symbol="TIGHT",
            decision="LONG",
            confidence=0.8,
            price=100.0,
            atr=200.0,
        )
        self.assertFalse(approved)

    def test_multiple_consecutive_trades(self) -> None:
        now = datetime.now(timezone.utc)
        self.governor.state.last_trade_timestamp = now

        for i in range(3):
            self.governor.state.last_trade_timestamp = now - timedelta(seconds=90)
            approved, reason, position = self.governor.evaluate(
                symbol=f"TRADE_{i}",
                decision="LONG",
                confidence=0.8,
                price=100.0 + i,
                atr=2.0,
            )
            if i < 3:
                self.assertTrue(approved, f"Trade {i} should be approved")
                self.governor.record_trade(f"TRADE_{i}", 0.0)
                self.assertEqual(self.governor.state.trades_today, i + 1)

    def test_loss_accumulation(self) -> None:
        self.governor.record_trade("LOSS1", -500.0)
        self.assertEqual(self.governor.state.daily_loss, 500.0)
        self.governor.record_trade("LOSS2", -800.0)
        self.assertEqual(self.governor.state.daily_loss, 1300.0)

    def test_boundary_max_daily_loss(self) -> None:
        self.governor.state.daily_loss = 5_000.0 - 2_000.1

        approved, reason, position = self.governor.evaluate(
            symbol="BOUND",
            decision="LONG",
            confidence=0.8,
            price=100.0,
            atr=2.0,
        )
        self.assertTrue(approved)

        self.governor.state.daily_loss = 5_000.0 - 1_999.9
        approved, reason, position = self.governor.evaluate(
            symbol="BOUND",
            decision="LONG",
            confidence=0.8,
            price=100.0,
            atr=2.0,
        )
        self.assertFalse(approved)

    def test_high_atr_small_position(self) -> None:
        approved, reason, position = self.governor.evaluate(
            symbol="HIGH_ATR",
            decision="LONG",
            confidence=0.8,
            price=100.0,
            atr=50.0,
        )
        self.assertTrue(approved)
        self.assertGreater(position.shares, 0)
        self.assertLess(position.shares, 100)

    def test_low_atr_large_position(self) -> None:
        approved, reason, position = self.governor.evaluate(
            symbol="LOW_ATR",
            decision="LONG",
            confidence=0.8,
            price=100.0,
            atr=0.5,
        )
        self.assertTrue(approved)
        self.assertGreater(position.shares, 100)


if __name__ == "__main__":
    unittest.main()
