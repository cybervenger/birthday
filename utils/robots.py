"""robots.txt compliance helper built on top of Protego."""
from __future__ import annotations

from typing import Optional
from urllib.parse import urljoin, urlparse

import httpx
from protego import Protego

from utils.logging_config import get_logger

logger = get_logger(__name__)


class RobotsChecker:
    """Fetches and caches robots.txt for a single host and answers can_fetch()."""

    def __init__(self, base_url: str, user_agent: str, enabled: bool = True):
        self.enabled = enabled
        self.user_agent = user_agent
        parsed = urlparse(base_url)
        self.robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        self._parser: Optional[Protego] = None

    async def load(self) -> None:
        if not self.enabled:
            return
        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                resp = await client.get(self.robots_url)
                if resp.status_code == 200:
                    self._parser = Protego.parse(resp.text)
                else:
                    self._parser = Protego.parse("")  # no restrictions found
        except Exception as exc:  # noqa: BLE001
            logger.info("Could not fetch robots.txt (%s); assuming crawl allowed.", exc)
            self._parser = Protego.parse("")

    def can_fetch(self, url: str) -> bool:
        if not self.enabled or self._parser is None:
            return True
        return self._parser.can_fetch(url, self.user_agent)

    def crawl_delay(self) -> Optional[float]:
        if self._parser is None:
            return None
        try:
            return self._parser.crawl_delay(self.user_agent)
        except Exception:  # noqa: BLE001
            return None
