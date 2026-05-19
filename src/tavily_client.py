from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Any

import httpx

LOGGER = logging.getLogger(__name__)


@dataclass
class TavilyKeyState:
    key: str
    disabled_until: float = 0.0
    failures: int = 0


class TavilySearchClient:
    def __init__(self, settings: dict[str, Any]):
        self.settings = settings
        self.endpoint = settings.get("tavily_endpoint", "https://api.tavily.com/search")
        self.timeout_seconds = float(settings.get("tavily_timeout_seconds", 30))
        self.key_cooldown_seconds = float(settings.get("tavily_key_cooldown_seconds", 3600))
        self.keys = [TavilyKeyState(key) for key in self._load_keys(settings)]
        self._index = 0

    def _load_keys(self, settings: dict[str, Any]) -> list[str]:
        keys_env = settings.get("tavily_api_keys_env", "TAVILY_API_KEYS")
        single_key_env = settings.get("tavily_api_key_env", "TAVILY_API_KEY")
        values: list[str] = []
        for raw in [os.getenv(keys_env), os.getenv(single_key_env)]:
            if not raw:
                continue
            for item in raw.replace("\n", ",").split(","):
                key = item.strip()
                if key and key not in values:
                    values.append(key)
        return values

    def available(self) -> bool:
        return bool(self.keys)

    def _next_key(self) -> TavilyKeyState | None:
        if not self.keys:
            return None
        now = time.monotonic()
        for _ in range(len(self.keys)):
            state = self.keys[self._index % len(self.keys)]
            self._index = (self._index + 1) % len(self.keys)
            if state.disabled_until <= now:
                return state
        return None

    def _disable_key(self, state: TavilyKeyState, reason: str) -> None:
        state.failures += 1
        state.disabled_until = time.monotonic() + self.key_cooldown_seconds
        LOGGER.warning("Tavily key temporarily disabled: reason=%s failures=%s", reason, state.failures)

    def search(self, query: str, max_results: int) -> list[dict[str, Any]]:
        if not self.available():
            raise RuntimeError("No Tavily API keys configured.")
        last_error: Exception | None = None
        attempted = 0
        while attempted < len(self.keys):
            state = self._next_key()
            if state is None:
                break
            attempted += 1
            try:
                return self._search_with_key(state, query, max_results)
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                last_error = exc
                if status in {401, 429, 432, 433}:
                    self._disable_key(state, f"http_{status}")
                    continue
                raise
            except httpx.HTTPError as exc:
                last_error = exc
                self._disable_key(state, exc.__class__.__name__)
                continue
        if last_error:
            raise last_error
        raise RuntimeError("All Tavily API keys are currently cooling down.")

    def _search_with_key(self, state: TavilyKeyState, query: str, max_results: int) -> list[dict[str, Any]]:
        payload = {
            "query": query,
            "search_depth": self.settings.get("tavily_search_depth", "basic"),
            "topic": self.settings.get("tavily_topic", "general"),
            "max_results": min(int(max_results), int(self.settings.get("tavily_max_results", 10)), 20),
            "include_answer": bool(self.settings.get("tavily_include_answer", False)),
            "include_raw_content": self.settings.get("tavily_include_raw_content", False),
            "include_images": False,
            "include_favicon": False,
            "include_usage": bool(self.settings.get("tavily_include_usage", True)),
        }
        country = self.settings.get("tavily_country")
        if country:
            payload["country"] = country
        with httpx.Client(timeout=httpx.Timeout(self.timeout_seconds)) as client:
            response = client.post(
                self.endpoint,
                headers={"Authorization": f"Bearer {state.key}", "Content-Type": "application/json"},
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
        results = []
        for item in data.get("results", []) or []:
            results.append(
                {
                    "url": item.get("url") or "",
                    "title": item.get("title") or "",
                    "snippet": item.get("content") or item.get("raw_content") or "",
                    "source_backend": "tavily",
                    "tavily_score": item.get("score"),
                    "published_date": item.get("published_date"),
                }
            )
        return results
