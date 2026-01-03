from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.dashboard.server import create_dashboard_app
from app.models import Base, OrderLog, TradeOutcomeLog


class DashboardTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
        os.environ["AI_API_KEY"] = "test-ai"
        os.environ["SEARCH_API_KEY"] = "test-search"
        os.environ["ALPACA_API_KEY"] = "test-alpaca"
        os.environ["ALPACA_SECRET_KEY"] = "test-alpaca-secret"
        os.environ["JWT_SECRET"] = "test-jwt"
        os.environ["OTP_ISSUER_NAME"] = "test-issuer"
        os.environ["APP_ENV"] = "test"
        self.app = create_dashboard_app().test_client()

    def test_index_renders(self) -> None:
        resp = self.app.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Trading Dashboard", resp.data)

    def test_candles_api(self) -> None:
        resp = self.app.get("/api/candles")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(len(data), 0)

    def test_stats_api(self) -> None:
        resp = self.app.get("/api/stats")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("realized_pnl", data)
        self.assertIn("unrealized_pnl", data)
        self.assertIn("win_rate", data)

    def test_trades_api(self) -> None:
        resp = self.app.get("/api/trades")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(len(data), 0)

    def test_drawdown_api(self) -> None:
        resp = self.app.get("/api/drawdown")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(len(data), 0)

    def test_dashboard_reads_trade_logs(self) -> None:
        fd, path = tempfile.mkstemp(prefix="dashboard", suffix=".db")
        os.close(fd)
        db_url = f"sqlite+pysqlite:///{path}"
        os.environ["DATABASE_URL"] = db_url
        engine = create_engine(db_url, future=True)
        Base.metadata.create_all(engine)
        SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)
        with SessionLocal() as session:
            submitted_at = datetime.now(timezone.utc)
            order = OrderLog(
                order_id="o-db-1",
                symbol="AAPL",
                side="buy",
                qty=10,
                status="filled",
                filled_qty=10,
                filled_avg_price=150.0,
                submitted_at=submitted_at,
                filled_at=submitted_at,
                estimated_slippage_bps=1.0,
                raw_response={},
            )
            outcome = TradeOutcomeLog(
                order_id="o-db-1",
                symbol="AAPL",
                outcome="closed",
                pnl=25.0,
                duration_seconds=3600,
                context={},
            )
            session.add(order)
            session.add(outcome)
            session.commit()
        app = create_dashboard_app().test_client()
        trades_resp = app.get("/api/trades")
        stats_resp = app.get("/api/stats")
        drawdown_resp = app.get("/api/drawdown")
        try:
            self.assertEqual(trades_resp.status_code, 200)
            trades = trades_resp.get_json()
            self.assertGreater(len(trades), 0)
            self.assertEqual(trades[0]["symbol"], "AAPL")
            self.assertEqual(trades[0]["realized_pnl"], 25.0)
            self.assertEqual(stats_resp.status_code, 200)
            stats = stats_resp.get_json()
            self.assertGreater(stats["win_rate"], 0)
            self.assertGreater(stats["realized_pnl"], 0)
            self.assertEqual(drawdown_resp.status_code, 200)
        finally:
            os.remove(path)

    def test_rules_budget_roundtrip(self) -> None:
        os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
        app = create_dashboard_app().test_client()
        put_resp = app.put(
            "/api/admin/rules",
            json={
                "max_risk_per_trade": 0.02,
                "max_daily_loss": 0.1,
                "max_trades_per_day": 15,
                "cooldown_seconds": 120,
                "budget": 250000.0,
            },
        )
        self.assertEqual(put_resp.status_code, 200)
        get_resp = app.get("/api/admin/rules")
        self.assertEqual(get_resp.status_code, 200)
        data = get_resp.get_json()
        self.assertEqual(data["budget"], 250000.0)

    def test_otp_secret_persists_across_restart(self) -> None:
        fd, path = tempfile.mkstemp(prefix="dashboard", suffix=".db")
        os.close(fd)
        db_url = f"sqlite+pysqlite:///{path}"
        os.environ["DATABASE_URL"] = db_url
        first_app = create_dashboard_app()
        first_secret = first_app.config["OTP_SECRET"]
        second_app = create_dashboard_app()
        second_secret = second_app.config["OTP_SECRET"]
        try:
            self.assertEqual(first_secret, second_secret)
        finally:
            os.remove(path)


if __name__ == "__main__":
    unittest.main()
