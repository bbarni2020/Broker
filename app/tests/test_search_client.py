from __future__ import annotations

import asyncio
import unittest
from typing import Any, Mapping

from app.services.search import SearchSignals, WebSearchClient


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


class WebSearchClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_search_signals_detect_flags(self) -> None:
        response = DummyResponse(
            200,
            {
                "news": {
                    "results": [
                        {"title": "TSLA earnings beat", "snippet": "Record EPS guidance"},
                        {"title": "TSLA faces lawsuit", "snippet": "Class action filed"},
                        {"title": "FDA approves new drug", "snippet": "Phase 3 success"},
                        {"title": "Macro update", "snippet": "Fed rate hike expected"},
                    ]
                },
                "discussions": {
                    "results": [
                        {"title": "Unusual activity spotted", "snippet": "Spike in mentions"},
                        {"title": "Social chatter", "body": "reddit thread"},
                    ]
                },
            },
        )
        dummy_client = DummyAsyncClient(response)
        client = WebSearchClient(api_key="k", http_client=dummy_client)

        signals = await client.search("TSLA earnings", count=6, result_filter="news,discussions,web")

        self.assertIsInstance(signals, SearchSignals)
        self.assertEqual(signals.total_results, 6)
        self.assertTrue(signals.earnings)
        self.assertTrue(signals.lawsuits)
        self.assertTrue(signals.fda)
        self.assertTrue(signals.macro)
        self.assertTrue(signals.unusual_mentions)
        self.assertIn("earnings", signals.matched_categories)
        self.assertIn("unusual", signals.matched_categories)
        self.assertEqual(dummy_client.last_request["params"]["q"], "TSLA earnings")
        self.assertEqual(dummy_client.last_request["params"]["count"], 6)
        self.assertEqual(dummy_client.last_request["params"]["result_filter"], "news,discussions,web")

    async def test_search_empty_results(self) -> None:
        response = DummyResponse(200, {"news": {"results": []}, "discussions": {"results": []}})
        dummy_client = DummyAsyncClient(response)
        client = WebSearchClient(api_key="k", http_client=dummy_client)

        signals = await client.search("TSLA earnings", count=10)

        self.assertEqual(signals.total_results, 0)
        self.assertFalse(signals.unusual_mentions)
        self.assertEqual(signals.matched_categories, ())

    async def test_search_invalid_api_key(self) -> None:
        response = DummyResponse(401, {})
        dummy_client = DummyAsyncClient(response)
        client = WebSearchClient(api_key="bad", http_client=dummy_client)

        with self.assertRaises(RuntimeError):
            await client.search("TSLA earnings")

    async def test_search_rate_limited(self) -> None:
        response = DummyResponse(429, {})
        dummy_client = DummyAsyncClient(response)
        client = WebSearchClient(api_key="k", http_client=dummy_client)

        with self.assertRaises(RuntimeError):
            await client.search("TSLA earnings")


if __name__ == "__main__":
    asyncio.run(unittest.main())
