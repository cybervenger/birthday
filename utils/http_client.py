"""Async HTTP helpers: retrying GET requests + a tiny per-host rate limiter."""
from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from typing import Optional

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from config import DEFAULT_HEADERS
from utils.logging_config import get_logger

logger = get_logger(__name__)


class RateLimiter:
    """Per-host minimum delay between outbound requests."""

    def __init__(self, delay: float = 0.6):
        self.delay = delay
        self._last_hit: dict[str, float] = defaultdict(float)
        self._lock = asyncio.Lock()

    async def wait(self, host: str) -> None:
        async with self._lock:
            elapsed = time.monotonic() - self._last_hit[host]
            remaining = self.delay - elapsed
            if remaining > 0:
                await asyncio.sleep(remaining)
            self._last_hit[host] = time.monotonic()


class AsyncHTTPClient:
    """Thin wrapper around httpx.AsyncClient with retries + rate limiting."""

    def __init__(
        self,
        timeout: float = 20.0,
        retries: int = 3,
        rate_limit_delay: float = 0.6,
        headers: Optional[dict] = None,
    ):
        self.retries = retries
        self.limiter = RateLimiter(rate_limit_delay)
        self._client = httpx.AsyncClient(
            timeout=timeout,
            headers=headers or DEFAULT_HEADERS,
            follow_redirects=True,
        )

    async def __aenter__(self) -> "AsyncHTTPClient":
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()

    async def close(self) -> None:
        await self._client.aclose()

    async def get(self, url: str) -> Optional[httpx.Response]:
        host = httpx.URL(url).host or ""
        await self.limiter.wait(host)

        @retry(
            reraise=True,
            stop=stop_after_attempt(self.retries),
            wait=wait_exponential(multiplier=1.0, min=1, max=15),
            retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
        )
        async def _do() -> httpx.Response:
            resp = await self._client.get(url)
            if resp.status_code in (429, 503):
                raise httpx.HTTPStatusError("rate limited", request=resp.request, response=resp)
            resp.raise_for_status()
            return resp

        try:
            return await _do()
        except Exception as exc:  # noqa: BLE001 - we want to keep crawling on any failure
            logger.warning("GET failed for %s: %s", url, exc)
            return None
