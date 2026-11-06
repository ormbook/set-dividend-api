"""HTTP client for set.or.th JSON endpoints: timeouts, retries, cache, throttle."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Protocol

from .config import Settings
from .errors import SetNotFound, SetUpstreamError

log = logging.getLogger("set_client")

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9,th;q=0.8",
    "Referer": "https://www.set.or.th/",
}


class JsonFetcher(Protocol):
    async def get_json(self, path: str) -> Any: ...


class SetClient:
    """Fetches JSON from SET.

    SET sits behind bot protection that can reject plain HTTP clients. If the
    optional `curl_cffi` package is installed we use it with browser TLS
    impersonation; otherwise we fall back to httpx.
    """

    def __init__(self, settings: Settings) -> None:
        self._s = settings
        self._sem = asyncio.Semaphore(settings.max_concurrency)
        self._cache: dict[str, tuple[float, Any]] = {}
        self._session: Any = None
        self._use_curl = False

    async def start(self) -> None:
        try:
            from curl_cffi.requests import AsyncSession  # type: ignore

            self._session = AsyncSession(impersonate="chrome", headers=BROWSER_HEADERS)
            self._use_curl = True
        except ImportError:
            import httpx

            self._session = httpx.AsyncClient(
                headers=BROWSER_HEADERS, timeout=self._s.timeout_seconds, follow_redirects=True
            )
        log.info("SET client started (curl_cffi=%s)", self._use_curl)

    async def close(self) -> None:
        if self._session is None:
            return
        if self._use_curl:
            await self._session.close()
        else:
            await self._session.aclose()

    async def get_json(self, path: str) -> Any:
        now = time.monotonic()
        hit = self._cache.get(path)
        if hit and hit[0] > now:
            return hit[1]

        url = self._s.set_base_url.rstrip("/") + path
        last_error: Exception | None = None
        for attempt in range(self._s.max_retries + 1):
            try:
                async with self._sem:
                    data = await self._request(url)
                self._cache[path] = (time.monotonic() + self._s.cache_ttl_seconds, data)
                return data
            except SetNotFound:
                raise
            except SetUpstreamError as exc:
                last_error = exc
                if attempt < self._s.max_retries:
                    await asyncio.sleep(0.5 * 2**attempt)
        raise SetUpstreamError(str(last_error))

    async def probe(self, path: str) -> dict[str, Any]:
        """Raw diagnostic call: status, content type and the start of the body."""
        url = self._s.set_base_url.rstrip("/") + path
        try:
            if self._use_curl:
                resp = await self._session.get(url, timeout=self._s.timeout_seconds)
            else:
                resp = await self._session.get(url)
        except Exception as exc:
            return {"url": url, "error": f"{type(exc).__name__}: {exc}"}
        return {
            "url": url,
            "client": "curl_cffi" if self._use_curl else "httpx",
            "status": resp.status_code,
            "content_type": resp.headers.get("content-type"),
            "body_head": resp.text[:600],
        }

    async def _request(self, url: str) -> Any:
        try:
            if self._use_curl:
                resp = await self._session.get(url, timeout=self._s.timeout_seconds)
            else:
                resp = await self._session.get(url)
        except Exception as exc:  # network/TLS/timeout, library-specific types
            raise SetUpstreamError(f"{type(exc).__name__}: {exc}") from exc

        status = resp.status_code
        if status == 404:
            raise SetNotFound(url)
        if status != 200:
            raise SetUpstreamError(f"HTTP {status} from {url}")
        try:
            return resp.json()
        except ValueError as exc:
            raise SetUpstreamError(f"non-JSON response from {url}") from exc
