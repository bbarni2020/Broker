"""Web search client for news-derived signals."""

from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

BASE_URL = "https://ai.hackclub.com"
SEARCH_PATH = "/res/v1/web/search"


@dataclass(frozen=True)
class SearchSignals:
    total_results: int
    earnings: bool
    lawsuits: bool
    fda: bool
    macro: bool
    unusual_mentions: bool
    matched_categories: Sequence[str]


class WebSearchClient:
    def __init__(
        self,
        api_key: str,
        base_url: str = BASE_URL,
        http_client: Any = None,
        timeout_seconds: float = 15.0,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._http_client = http_client

    async def search(self, query: str, freshness: str = "pd", count: int = 10) -> SearchSignals:
        if not isinstance(query, str) or not query.strip():
            raise ValueError("Query must be a non-empty string")
        if count <= 0:
            raise ValueError("Count must be positive")

        params = {"q": query, "freshness": freshness, "count": count}

        if self._http_client is not None:
            response = await self._http_client.get(
                self._url(), headers=self._headers(), params=params, timeout=self.timeout_seconds
            )
        else:
            response = await asyncio.to_thread(self._get_with_urllib, self._url(), params)

        if response.status_code == 401:
            raise RuntimeError("Invalid API key for search")
        if response.status_code == 429:
            raise RuntimeError("Search rate limited")
        if response.status_code != 200:
            raise RuntimeError(f"Search service error {response.status_code}")

        payload = response.json()
        results = self._extract_results(payload)
        return self._build_signals(results, count)

    def _url(self) -> str:
        return f"{self.base_url}{SEARCH_PATH}"

    def _headers(self) -> Mapping[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
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
            raise RuntimeError(f"Search service unreachable: {exc.reason}") from exc

        try:
            content_json = json.loads(content_bytes.decode("utf-8"))
        except json.JSONDecodeError:
            content_json = {}

        return _SimpleResponse(status, content_json)

    def _extract_results(self, payload: Mapping[str, Any]) -> Sequence[Mapping[str, Any]]:
        if not isinstance(payload, Mapping):
            return ()
        value = payload.get("value")
        if isinstance(value, Sequence):
            return tuple(item for item in value if isinstance(item, Mapping))
        return ()

    def _build_signals(self, results: Sequence[Mapping[str, Any]], requested_count: int) -> SearchSignals:
        total = len(results)
        earnings_hit = False
        lawsuits_hit = False
        fda_hit = False
        macro_hit = False
        unusual_hit = total >= max(5, requested_count)

        earnings_terms = ("earnings", "eps", "guidance", "results", "revenue", "profit", "quarter")
        lawsuits_terms = ("lawsuit", "class action", "litigation", "settlement", "sec investigation", "probe")
        fda_terms = ("fda", "clinical", "trial", "approval", "phase")
        macro_terms = (
            "inflation",
            "cpi",
            "ppi",
            "fomc",
            "fed",
            "ecb",
            "opec",
            "gdp",
            "jobs report",
            "unemployment",
            "rate hike",
            "interest rate",
        )

        for item in results:
            text = self._result_text(item)
            lower = text.lower()
            if not earnings_hit and self._contains_any(lower, earnings_terms):
                earnings_hit = True
            if not lawsuits_hit and self._contains_any(lower, lawsuits_terms):
                lawsuits_hit = True
            if not fda_hit and self._contains_any(lower, fda_terms):
                fda_hit = True
            if not macro_hit and self._contains_any(lower, macro_terms):
                macro_hit = True
            if self._contains_any(lower, ("unusual activity", "surge", "spike")):
                unusual_hit = True

        matched = []
        if earnings_hit:
            matched.append("earnings")
        if lawsuits_hit:
            matched.append("lawsuits")
        if fda_hit:
            matched.append("fda")
        if macro_hit:
            matched.append("macro")
        if unusual_hit:
            matched.append("unusual")

        return SearchSignals(
            total_results=total,
            earnings=earnings_hit,
            lawsuits=lawsuits_hit,
            fda=fda_hit,
            macro=macro_hit,
            unusual_mentions=unusual_hit,
            matched_categories=tuple(matched),
        )

    def _contains_any(self, text: str, terms: Iterable[str]) -> bool:
        return any(term in text for term in terms)

    def _result_text(self, item: Mapping[str, Any]) -> str:
        title = str(item.get("title", ""))
        snippet = str(item.get("snippet", ""))
        return f"{title} {snippet}".strip()


class _SimpleResponse:
    def __init__(self, status_code: int, payload: Mapping[str, Any]):
        self.status_code = status_code
        self._payload = payload

    def json(self) -> Mapping[str, Any]:
        return self._payload
