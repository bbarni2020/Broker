from __future__ import annotations

import asyncio
import json
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import httpx

from app.services import (
    AlpacaExecutionClient,
    ExecutedOrder,
    ExecutionError,
    ExecutionService,
    HealthStatus,
    OrderRequest,
    OrderStatus,
    OrderType,
    TimeInForce,
)


def run(coro):
    return asyncio.run(coro)


class AlpacaExecutionClientTests(unittest.TestCase):
    def test_requires_confirmation_for_live(self) -> None:
        with self.assertRaises(ExecutionError):
            AlpacaExecutionClient(
                api_key="key",
                secret_key="secret",
                trading_mode="live",
                live_trading_confirmed=False,
            )

    def test_submits_market_order_success(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content.decode())
            self.assertEqual(payload["symbol"], "AAPL")
            self.assertEqual(payload["qty"], 10)
            body = {
                "id": "o1",
                "symbol": "AAPL",
                "qty": "10",
                "filled_qty": "10",
                "side": "buy",
                "status": "filled",
                "filled_avg_price": "101.5",
                "created_at": "2026-01-02T10:00:00Z",
                "filled_at": "2026-01-02T10:00:00Z",
            }
            return httpx.Response(200, json=body)

        client = AlpacaExecutionClient(
            api_key="key",
            secret_key="secret",
            http_client=httpx.AsyncClient(
                transport=httpx.MockTransport(handler),
                base_url=AlpacaExecutionClient.PAPER_BASE_URL,
            ),
        )
        request = OrderRequest(
            symbol="AAPL",
            qty=10,
            side="buy",
            order_type=OrderType.MARKET,
            time_in_force=TimeInForce.DAY,
        )

        order = run(client.submit_order(request))

        self.assertEqual(order.order_id, "o1")
        self.assertEqual(order.status, OrderStatus.FILLED)
        self.assertAlmostEqual(order.filled_avg_price or 0.0, 101.5)

    def test_rejects_on_http_error(self) -> None:
        def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(422, json={"message": "rejected"})

        client = AlpacaExecutionClient(
            api_key="key",
            secret_key="secret",
            http_client=httpx.AsyncClient(
                transport=httpx.MockTransport(handler),
                base_url=AlpacaExecutionClient.PAPER_BASE_URL,
            ),
        )
        request = OrderRequest(
            symbol="AAPL",
            qty=1,
            side="buy",
            order_type=OrderType.LIMIT,
            time_in_force=TimeInForce.DAY,
            limit_price=150.0,
        )

        with self.assertRaises(ExecutionError):
            run(client.submit_order(request))

    def test_times_out(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("timeout", request=request)

        client = AlpacaExecutionClient(
            api_key="key",
            secret_key="secret",
            http_client=httpx.AsyncClient(
                transport=httpx.MockTransport(handler),
                base_url=AlpacaExecutionClient.PAPER_BASE_URL,
            ),
        )
        request = OrderRequest(
            symbol="AAPL",
            qty=5,
            side="sell",
            order_type=OrderType.MARKET,
            time_in_force=TimeInForce.DAY,
        )

        with self.assertRaises(ExecutionError) as ctx:
            run(client.submit_order(request))
        self.assertEqual(ctx.exception.code, "timeout")

    def test_health_check_account_blocked(self) -> None:
        responses = {
            "/v2/clock": httpx.Response(200, json={"timestamp": "2026-01-02T10:00:00Z", "is_open": True}),
            "/v2/account": httpx.Response(200, json={"trading_blocked": True}),
        }

        def handler(request: httpx.Request) -> httpx.Response:
            return responses[request.url.path]

        client = AlpacaExecutionClient(
            api_key="key",
            secret_key="secret",
            http_client=httpx.AsyncClient(
                transport=httpx.MockTransport(handler),
                base_url=AlpacaExecutionClient.PAPER_BASE_URL,
            ),
        )

        status = run(client.check_health())

        self.assertIsInstance(status, HealthStatus)
        self.assertFalse(status.is_healthy)
        self.assertEqual(status.detail, "account_blocked")


class ExecutionServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mock_client = AsyncMock(spec=AlpacaExecutionClient)
        self.service = ExecutionService(client=self.mock_client, max_slippage_bps=50.0)

    def test_rejects_negative_qty(self) -> None:
        request = OrderRequest(
            symbol="AAPL",
            qty=-1,
            side="buy",
            order_type=OrderType.MARKET,
            time_in_force=TimeInForce.DAY,
        )

        approved, reason, order = run(
            self.service.execute_trade(
                request=request,
                position_size_from_risk=-1,
                entry_price_estimate=150.0,
                has_passed_all_checks=True,
            )
        )

        self.assertFalse(approved)
        self.assertIn("quantity", reason.lower())
        self.assertIsNone(order)

    def test_handles_partial_fill_accept(self) -> None:
        request = OrderRequest(
            symbol="AAPL",
            qty=10,
            side="buy",
            order_type=OrderType.MARKET,
            time_in_force=TimeInForce.DAY,
        )
        partial = ExecutedOrder(
            order_id="p1",
            symbol="AAPL",
            qty=10,
            filled_qty=5,
            side="buy",
            status=OrderStatus.PARTIAL_FILL,
            filled_avg_price=150.5,
            submitted_at=datetime.now(timezone.utc),
            filled_at=None,
            estimated_slippage_bps=0.0,
        )
        self.mock_client.submit_order.return_value = partial

        approved, reason, order = run(
            self.service.execute_trade(
                request=request,
                position_size_from_risk=10,
                entry_price_estimate=150.0,
                has_passed_all_checks=True,
            )
        )

        self.assertTrue(approved)
        self.assertIn("partially", reason.lower())
        self.assertEqual(order.status, OrderStatus.PARTIAL_FILL)

    def test_handles_broker_rejection(self) -> None:
        request = OrderRequest(
            symbol="AAPL",
            qty=10,
            side="buy",
            order_type=OrderType.MARKET,
            time_in_force=TimeInForce.DAY,
        )
        rejected = ExecutedOrder(
            order_id="r1",
            symbol="AAPL",
            qty=10,
            filled_qty=0,
            side="buy",
            status=OrderStatus.REJECTED,
            filled_avg_price=None,
            submitted_at=datetime.now(timezone.utc),
            filled_at=None,
            estimated_slippage_bps=0.0,
        )
        self.mock_client.submit_order.return_value = rejected

        approved, reason, order = run(
            self.service.execute_trade(
                request=request,
                position_size_from_risk=10,
                entry_price_estimate=150.0,
                has_passed_all_checks=True,
            )
        )

        self.assertFalse(approved)
        self.assertIn("rejected", reason.lower())
        self.assertIsNone(order)

    def test_rejects_on_submission_error(self) -> None:
        request = OrderRequest(
            symbol="AAPL",
            qty=10,
            side="buy",
            order_type=OrderType.MARKET,
            time_in_force=TimeInForce.DAY,
        )
        self.mock_client.submit_order.side_effect = ExecutionError("http_error", "upstream error")

        approved, reason, order = run(
            self.service.execute_trade(
                request=request,
                position_size_from_risk=10,
                entry_price_estimate=150.0,
                has_passed_all_checks=True,
            )
        )

        self.assertFalse(approved)
        self.assertIn("submission failed", reason.lower())
        self.assertIsNone(order)

    def test_slippage_cancels_order(self) -> None:
        request = OrderRequest(
            symbol="AAPL",
            qty=10,
            side="buy",
            order_type=OrderType.MARKET,
            time_in_force=TimeInForce.DAY,
        )
        filled = ExecutedOrder(
            order_id="s1",
            symbol="AAPL",
            qty=10,
            filled_qty=10,
            side="buy",
            status=OrderStatus.FILLED,
            filled_avg_price=101.0,
            submitted_at=datetime.now(timezone.utc),
            filled_at=datetime.now(timezone.utc),
            estimated_slippage_bps=0.0,
        )
        self.mock_client.submit_order.return_value = filled
        self.mock_client.cancel_order.return_value = True

        approved, reason, order = run(
            self.service.execute_trade(
                request=request,
                position_size_from_risk=10,
                entry_price_estimate=99.0,
                has_passed_all_checks=True,
            )
        )

        self.assertFalse(approved)
        self.assertIn("slippage", reason.lower())
        self.assertIsNotNone(order)
