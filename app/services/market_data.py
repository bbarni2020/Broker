from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping, Sequence

import pandas as pd
import yfinance as yf

BASE_URL = "https://data.alpaca.markets/v2"
YAHOO_BASE = "https://query1.finance.yahoo.com/v8/finance/chart"


@dataclass(frozen=True)
class Candle:
    symbol: str
    timeframe: str
    open: float
    high: float
    low: float
    close: float
    volume: int
    timestamp: str


class MarketDataClient:
    def __init__(
        self,
        api_key: str,
        api_secret: str,
        base_url: str = BASE_URL,
        http_client: Any = None,
        timeout_seconds: float = 15.0,
    ) -> None:
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._http_client = http_client

    async def latest_bar(self, symbol: str, timeframe: str = "1Min") -> Candle:
        url = f"{self.base_url}/stocks/{symbol}/bars/latest"
        params = {"timeframe": timeframe}
        response = await self._get(url, params)
        payload = response.json()
        bar = payload.get("bar") if isinstance(payload, Mapping) else None
        if not bar:
            raise RuntimeError("No latest bar available")
        return self._normalize_bar(symbol, timeframe, bar)

    async def historical_bars(
        self,
        symbol: str,
        timeframe: str,
        start: str,
        end: str | None = None,
        limit: int = 1000,
    ) -> Sequence[Candle]:
        url = f"{self.base_url}/stocks/{symbol}/bars"
        params = {"timeframe": timeframe, "start": start, "limit": limit}
        if end:
            params["end"] = end
        response = await self._get(url, params)
        payload = response.json()
        bars = payload.get("bars") if isinstance(payload, Mapping) else None
        if not bars:
            raise RuntimeError("No bars returned")
        return tuple(self._normalize_bar(symbol, timeframe, bar) for bar in bars)

    async def multi_timeframe(
        self,
        symbol: str,
        timeframes: Iterable[str],
        start: str,
        end: str | None = None,
        limit: int = 1000,
    ) -> Mapping[str, Sequence[Candle]]:
        results: dict[str, Sequence[Candle]] = {}
        for tf in timeframes:
            results[tf] = await self.historical_bars(symbol, tf, start, end=end, limit=limit)
        return results

    async def _get(self, url: str, params: Mapping[str, Any]):
        if self._http_client is not None:
            response = await self._http_client.get(url, headers=self._headers(), params=params, timeout=self.timeout_seconds)
        else:
            response = await asyncio.to_thread(self._get_with_urllib, url, params)
        if response.status_code == 401:
            raise RuntimeError("Invalid API credentials for market data")
        if response.status_code == 429:
            raise RuntimeError("Market data rate limited")
        if response.status_code >= 500:
            raise RuntimeError("Market data service unavailable")
        if response.status_code != 200:
            raise RuntimeError(f"Market data error {response.status_code}")
        return response

    def _headers(self) -> Mapping[str, str]:
        return {
            "APCA-API-KEY-ID": self.api_key,
            "APCA-API-SECRET-KEY": self.api_secret,
            "Content-Type": "application/json",
        }

    def _get_with_urllib(self, url: str, params: Mapping[str, Any]):
        query_string = urllib.parse.urlencode(params)
        full_url = f"{url}?{query_string}"
        request = urllib.request.Request(full_url, headers=dict(self._headers()))
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                status = response.getcode()
                content_bytes = response.read()
        except urllib.error.HTTPError as exc:
            status = exc.code
            content_bytes = exc.read()
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Market data service unreachable: {exc.reason}") from exc

        try:
            content_json = json.loads(content_bytes.decode("utf-8"))
        except json.JSONDecodeError:
            content_json = {}

        return _SimpleResponse(status, content_json)

    def _normalize_bar(self, symbol: str, timeframe: str, bar: Mapping[str, Any]) -> Candle:
        if not isinstance(bar, Mapping):
            raise ValueError("Bar must be a mapping")
        required = ("o", "h", "l", "c", "v", "t")
        for key in required:
            if key not in bar:
                raise ValueError("Bar missing required fields")
        return Candle(
            symbol=symbol,
            timeframe=timeframe,
            open=float(bar["o"]),
            high=float(bar["h"]),
            low=float(bar["l"]),
            close=float(bar["c"]),
            volume=int(bar["v"]),
            timestamp=str(bar["t"]),
        )


class YahooMarketDataClient:
    def __init__(self, timeout_seconds: float = 15.0) -> None:
        self.timeout_seconds = timeout_seconds

    async def latest_bar(self, symbol: str, timeframe: str = "1m") -> Candle:
        bars = await self.historical_bars(symbol, timeframe, range_param="1d", limit=1)
        if not bars:
            raise RuntimeError("No latest bar available")
        return bars[-1]

    async def historical_bars(
        self,
        symbol: str,
        timeframe: str,
        start: str | None = None,
        end: str | None = None,
        limit: int = 1000,
        range_param: str = "5d",
    ) -> Sequence[Candle]:
        interval = self._map_timeframe(timeframe)
        bars = await asyncio.to_thread(self._fetch_history, symbol, interval, start, end, range_param)
        if bars.empty:
            return ()
        trimmed = bars.tail(limit)
        candles: list[Candle] = []
        for ts, row in trimmed.iterrows():
            try:
                candles.append(
                    Candle(
                        symbol=symbol,
                        timeframe=timeframe,
                        open=float(row["Open"]),
                        high=float(row["High"]),
                        low=float(row["Low"]),
                        close=float(row["Close"]),
                        volume=int(row["Volume"]),
                        timestamp=ts.isoformat(),
                    )
                )
            except (TypeError, ValueError):
                continue
        return tuple(candles)

    def _fetch_history(self, symbol: str, interval: str, start: str | None, end: str | None, period: str) -> pd.DataFrame:
        ticker = yf.Ticker(symbol)
        kwargs: dict[str, Any] = {"interval": interval, "auto_adjust": False}
        if start or end:
            if start:
                kwargs["start"] = start
            if end:
                kwargs["end"] = end
        else:
            kwargs["period"] = period
        data = ticker.history(**kwargs)
        if not isinstance(data, pd.DataFrame):
            return pd.DataFrame()
        return data

    def _map_timeframe(self, tf: str) -> str:
        mapping = {
            "1Min": "1m",
            "5Min": "5m",
            "15Min": "15m",
            "1h": "60m",
            "1D": "1d",
        }
        return mapping.get(tf, "1m")


class HybridMarketDataClient:
    def __init__(self, alpaca_client: MarketDataClient, yahoo_client: YahooMarketDataClient, recency_hours: int = 48) -> None:
        self.alpaca_client = alpaca_client
        self.yahoo_client = yahoo_client
        self.recency_cutoff = timedelta(hours=recency_hours)

    async def latest_bar(self, symbol: str, timeframe: str = "1Min") -> Candle:
        return await self.alpaca_client.latest_bar(symbol, timeframe=timeframe)

    async def historical_bars(
        self,
        symbol: str,
        timeframe: str,
        start: str,
        end: str | None = None,
        limit: int = 1000,
    ) -> Sequence[Candle]:
        if self._use_yahoo(start):
            return await self.yahoo_client.historical_bars(symbol, timeframe, start=start, end=end, limit=limit)
        try:
            return await self.alpaca_client.historical_bars(symbol, timeframe, start=start, end=end, limit=limit)
        except Exception:
            return await self.yahoo_client.historical_bars(symbol, timeframe, start=start, end=end, limit=limit)

    async def multi_timeframe(
        self,
        symbol: str,
        timeframes: Iterable[str],
        start: str,
        end: str | None = None,
        limit: int = 1000,
    ) -> Mapping[str, Sequence[Candle]]:
        results: dict[str, Sequence[Candle]] = {}
        for tf in timeframes:
            results[tf] = await self.historical_bars(symbol, tf, start=start, end=end, limit=limit)
        return results

    def _use_yahoo(self, start: str | None) -> bool:
        if not start:
            return False
        try:
            parsed = datetime.fromisoformat(start)
        except ValueError:
            return False
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        return now - parsed > self.recency_cutoff


class _SimpleResponse:
    def __init__(self, status_code: int, payload: Mapping[str, Any]):
        self.status_code = status_code
        self._payload = payload

    def json(self) -> Mapping[str, Any]:
        return self._payload
