from __future__ import annotations

import asyncio
import unittest
from typing import Any, Mapping

from app.services.market_data import Candle, MarketDataClient


class DummyResponse:
    def __init__(self, status_code: int, json_payload: Mapping[str, Any]):
        self.status_code = status_code
        self._json_payload = json_payload

    def json(self) -> Mapping[str, Any]:
        return self._json_payload


class DummyAsyncClient:
    def __init__(self, response: DummyResponse):
        self.response = response
        self.last_request = None

    async def get(self, url: str, headers: Mapping[str, Any], params: Mapping[str, Any], timeout: float) -> DummyResponse:
        self.last_request = {"url": url, "headers": headers, "params": params, "timeout": timeout}
        return self.response

    async def aclose(self) -> None:
        return None


class MarketDataClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_latest_bar_success(self) -> None:
        response = DummyResponse(
            200,
            {
                "bar": {
                    "o": 100.0,
                    "h": 110.0,
                    "l": 95.0,
                    "c": 105.0,
                    "v": 1000,
                    "t": "2024-01-01T00:00:00Z",
                }
            },
        )
        client = MarketDataClient("key", "secret", http_client=DummyAsyncClient(response))
        candle = await client.latest_bar("AAPL", timeframe="1Min")
        self.assertIsInstance(candle, Candle)
        self.assertEqual(candle.symbol, "AAPL")
        self.assertEqual(candle.timeframe, "1Min")
        self.assertEqual(candle.close, 105.0)

    async def test_historical_missing_bars_raises(self) -> None:
        response = DummyResponse(200, {"bars": []})
        client = MarketDataClient("key", "secret", http_client=DummyAsyncClient(response))
        with self.assertRaises(RuntimeError):
            await client.historical_bars("AAPL", "1Min", start="2024-01-01T00:00:00Z")

    async def test_market_closed_latest_bar(self) -> None:
        response = DummyResponse(200, {"bar": None})
        client = MarketDataClient("key", "secret", http_client=DummyAsyncClient(response))
        with self.assertRaises(RuntimeError):
            await client.latest_bar("AAPL")

    async def test_api_downtime(self) -> None:
        response = DummyResponse(503, {})
        client = MarketDataClient("key", "secret", http_client=DummyAsyncClient(response))
        with self.assertRaises(RuntimeError):
            await client.latest_bar("AAPL")

    async def test_multi_timeframe(self) -> None:
        response = DummyResponse(
            200,
            {
                "bars": [
                    {"o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 10, "t": "2024-01-01T00:00:00Z"}
                ]
            },
        )
        client = MarketDataClient("key", "secret", http_client=DummyAsyncClient(response))
        data = await client.multi_timeframe("AAPL", ["1Min", "5Min"], start="2024-01-01T00:00:00Z")
        self.assertIn("1Min", data)
        self.assertEqual(len(data["1Min"]), 1)
        self.assertEqual(data["1Min"][0].close, 1.5)


if __name__ == "__main__":
    asyncio.run(unittest.main())
