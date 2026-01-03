from __future__ import annotations

import asyncio
import unittest
from datetime import datetime, timedelta, timezone
from typing import Iterable, Mapping, Sequence

from app.services.market_data import Candle, HybridMarketDataClient


class DummyAlpaca:
    def __init__(self, bars: Sequence[Candle]) -> None:
        self.bars = list(bars)
        self.latest_calls = 0
        self.history_calls = 0

    async def latest_bar(self, symbol: str, timeframe: str = "1Min") -> Candle:
        self.latest_calls += 1
        return self.bars[-1]

    async def historical_bars(self, symbol: str, timeframe: str, start: str, end: str | None = None, limit: int = 1000) -> Sequence[Candle]:
        self.history_calls += 1
        return tuple(self.bars)

    async def multi_timeframe(self, symbol: str, timeframes: Iterable[str], start: str, end: str | None = None, limit: int = 1000) -> Mapping[str, Sequence[Candle]]:
        return {tf: tuple(self.bars) for tf in timeframes}


class DummyYahoo:
    def __init__(self, bars: Sequence[Candle]) -> None:
        self.bars = list(bars)
        self.history_calls = 0

    async def latest_bar(self, symbol: str, timeframe: str = "1Min") -> Candle:
        return self.bars[-1]

    async def historical_bars(self, symbol: str, timeframe: str, start: str | None = None, end: str | None = None, limit: int = 1000) -> Sequence[Candle]:
        self.history_calls += 1
        return tuple(self.bars)


class HybridMarketDataClientTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        now = datetime.now(timezone.utc)
        self.recent = Candle(symbol="TSLA", timeframe="1Min", open=1.0, high=1.1, low=0.9, close=1.05, volume=1000, timestamp=now.isoformat())
        self.old = Candle(symbol="TSLA", timeframe="1Min", open=0.5, high=0.6, low=0.4, close=0.55, volume=900, timestamp=(now - timedelta(days=3)).isoformat())

    async def test_recent_requests_use_alpaca(self) -> None:
        alpaca = DummyAlpaca([self.recent])
        yahoo = DummyYahoo([self.old])
        client = HybridMarketDataClient(alpaca_client=alpaca, yahoo_client=yahoo, recency_hours=48)
        start = (datetime.now(timezone.utc) - timedelta(hours=6)).isoformat()
        bars = await client.historical_bars("TSLA", "1Min", start=start, limit=10)
        self.assertEqual(len(bars), 1)
        self.assertEqual(alpaca.history_calls, 1)
        self.assertEqual(yahoo.history_calls, 0)

    async def test_old_requests_use_yahoo(self) -> None:
        alpaca = DummyAlpaca([self.recent])
        yahoo = DummyYahoo([self.old])
        client = HybridMarketDataClient(alpaca_client=alpaca, yahoo_client=yahoo, recency_hours=48)
        start = (datetime.now(timezone.utc) - timedelta(days=4)).isoformat()
        bars = await client.historical_bars("TSLA", "1Min", start=start, limit=10)
        self.assertEqual(len(bars), 1)
        self.assertEqual(alpaca.history_calls, 0)
        self.assertEqual(yahoo.history_calls, 1)

    async def test_latest_bar_always_alpaca(self) -> None:
        alpaca = DummyAlpaca([self.recent])
        yahoo = DummyYahoo([self.old])
        client = HybridMarketDataClient(alpaca_client=alpaca, yahoo_client=yahoo, recency_hours=48)
        bar = await client.latest_bar("TSLA", timeframe="1Min")
        self.assertEqual(bar.close, self.recent.close)
        self.assertEqual(alpaca.latest_calls, 1)


if __name__ == "__main__":
    asyncio.run(unittest.main())
