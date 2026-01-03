from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from openrouter import OpenRouter

BASE_URL = "https://ai.hackclub.com/proxy"
MODEL = "qwen/qwen3-32b"
DECISIONS = {"LONG", "SHORT", "NO_TRADE"}
SYSTEM_PROMPT = (
    "You are a trading decision engine. Respond with a single JSON object only. "
    "Schema: {\"decision\": string one of LONG|SHORT|NO_TRADE, \"confidence\": number 0-1, "
    "\"matched_rules\": array of strings, \"violated_rules\": array of strings, "
    "\"risk_flags\": array of strings, \"explanation\": non-empty string}. "
    "No prose, no code fences, no additional keys."
)


@dataclass(frozen=True)
class AIDecision:
    decision: str
    confidence: float
    matched_rules: Sequence[str]
    violated_rules: Sequence[str]
    risk_flags: Sequence[str]
    explanation: str

    @staticmethod
    def from_dict(payload: Mapping[str, Any]) -> "AIDecision":
        if not isinstance(payload, Mapping):
            raise ValueError("AI response payload must be a mapping")

        decision = payload.get("decision")
        confidence = payload.get("confidence")
        matched_rules = payload.get("matched_rules")
        violated_rules = payload.get("violated_rules")
        risk_flags = payload.get("risk_flags")
        explanation = payload.get("explanation")

        if decision not in DECISIONS:
            raise ValueError("Invalid decision value")
        try:
            confidence_value = float(confidence)
        except (TypeError, ValueError):
            raise ValueError("Confidence must be a float") from None
        if not 0.0 <= confidence_value <= 1.0:
            raise ValueError("Confidence must be between 0 and 1")

        for name, value in (
            ("matched_rules", matched_rules),
            ("violated_rules", violated_rules),
            ("risk_flags", risk_flags),
        ):
            if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
                raise ValueError(f"{name} must be a sequence of strings")
            if any(not isinstance(item, str) for item in value):
                raise ValueError(f"{name} must contain strings only")

        if not isinstance(explanation, str) or not explanation:
            raise ValueError("Explanation must be a non-empty string")

        return AIDecision(
            decision=decision,
            confidence=confidence_value,
            matched_rules=tuple(matched_rules),
            violated_rules=tuple(violated_rules),
            risk_flags=tuple(risk_flags),
            explanation=explanation,
        )


class AIClient:
    def __init__(
        self,
        api_key: str,
        base_url: str = BASE_URL,
        model: str = MODEL,
        http_client: Any = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self._http_client = http_client
        self._openrouter = None if http_client else OpenRouter(api_key=self.api_key, server_url=f"{self.base_url}/v1")

    async def classify(self, payload: Mapping[str, Any]) -> AIDecision:
        if not isinstance(payload, Mapping):
            raise ValueError("Payload must be a mapping")
        body = self._build_request_body(payload)
        if self._http_client is not None:
            response = await self._http_client.post(
                f"{self.base_url}/v1/chat/completions",
                headers=self._headers(),
                json=body,
                timeout=self.timeout_seconds,
            )
            status = response.status_code
            content = response.json() if hasattr(response, "json") else {}
        else:
            content = await asyncio.to_thread(self._send_with_openrouter, body)
            status = 200

        if status != 200:
            detail = content.get("error") if isinstance(content, Mapping) else None
            suffix = f": {detail}" if detail else ""
            raise RuntimeError(f"AI service error {status}{suffix}")

        decision_payload = self._extract_decision_payload(content)
        return AIDecision.from_dict(decision_payload)

    def _headers(self) -> Mapping[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _build_request_body(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        return {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT,
                },
                {
                    "role": "user",
                    "content": json.dumps(payload),
                },
            ],
            "stream": False,
            "response_format": {"type": "json_object"},
        }

    def _send_with_openrouter(self, body: Mapping[str, Any]) -> Mapping[str, Any]:
        if self._openrouter is None:
            raise RuntimeError("OpenRouter client unavailable")
        try:
            response = self._openrouter.chat.send(
                model=body.get("model", self.model),
                messages=body.get("messages", []),
                stream=False,
            )
        except Exception as exc:
            raise RuntimeError(f"AI service unreachable: {exc}") from exc

        if hasattr(response, "model_dump"):
            return response.model_dump()
        if hasattr(response, "dict"):
            try:
                return response.dict()
            except TypeError:
                pass
        if hasattr(response, "to_dict"):
            return response.to_dict()
        if isinstance(response, Mapping):
            return response
        raise RuntimeError("AI service returned unsupported response type")

    def _extract_decision_payload(self, response_json: Mapping[str, Any]) -> Mapping[str, Any]:
        if not isinstance(response_json, Mapping):
            raise ValueError("AI response must be a mapping")
        choices = response_json.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ValueError("AI response missing choices")
        message = choices[0].get("message")
        if not isinstance(message, Mapping):
            raise ValueError("AI response missing message")
        content = message.get("content")
        if isinstance(content, str):
            try:
                return json.loads(content)
            except json.JSONDecodeError as exc:
                raise ValueError("AI content is not valid JSON") from exc
        if isinstance(content, list) and content:
            first = content[0]
            if isinstance(first, Mapping) and first.get("type") == "output_json":
                output = first.get("output_json")
                if isinstance(output, Mapping):
                    return output
        raise ValueError("AI content is missing structured JSON")
