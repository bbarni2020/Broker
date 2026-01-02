from __future__ import annotations

import asyncio
import json
import unittest
from typing import Any, Mapping

from app.ai.client import AIDecision, AIClient


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

    async def post(self, url: str, headers: Mapping[str, Any], json: Mapping[str, Any], timeout: float) -> DummyResponse:
        self.last_request = {"url": url, "headers": headers, "json": json, "timeout": timeout}
        return self.response

    async def aclose(self) -> None:
        return None


class AIClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_classify_success(self) -> None:
        decision_payload = {
            "decision": "LONG",
            "confidence": 0.82,
            "matched_rules": ["rule-1"],
            "violated_rules": [],
            "risk_flags": ["drawdown"],
            "explanation": "Signal meets criteria",
        }
        response = DummyResponse(
            200,
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(decision_payload),
                        }
                    }
                ]
            },
        )
        dummy_client = DummyAsyncClient(response)
        client = AIClient(api_key="test-key", http_client=dummy_client)
        result = await client.classify({"features": {"a": 1}})

        self.assertIsInstance(result, AIDecision)
        self.assertEqual(result.decision, "LONG")
        self.assertEqual(result.confidence, 0.82)
        self.assertEqual(result.matched_rules, ("rule-1",))
        self.assertEqual(result.risk_flags, ("drawdown",))
        self.assertEqual(dummy_client.last_request["url"], "https://ai.hackclub.com/v1/chat/completions")
        self.assertEqual(dummy_client.last_request["headers"]["Authorization"], "Bearer test-key")
        self.assertIn("input_json", dummy_client.last_request["json"]["messages"][0]["content"][0])

    async def test_classify_rejects_invalid_schema(self) -> None:
        bad_payload = {
            "decision": "HOLD",
            "confidence": 2,
            "matched_rules": "not-a-list",
            "violated_rules": [],
            "risk_flags": [],
            "explanation": "",
        }
        response = DummyResponse(
            200,
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(bad_payload),
                        }
                    }
                ]
            },
        )
        dummy_client = DummyAsyncClient(response)
        client = AIClient(api_key="test-key", http_client=dummy_client)

        with self.assertRaises(ValueError):
            await client.classify({"features": {}})

    async def test_classify_handles_http_error(self) -> None:
        response = DummyResponse(500, {"error": "server"})
        dummy_client = DummyAsyncClient(response)
        client = AIClient(api_key="test-key", http_client=dummy_client)

        with self.assertRaises(RuntimeError):
            await client.classify({"features": {}})


if __name__ == "__main__":
    asyncio.run(unittest.main())
