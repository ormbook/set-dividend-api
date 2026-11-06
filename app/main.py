"""FastAPI application."""
from __future__ import annotations

import logging
import re
import secrets
from contextlib import asynccontextmanager
from datetime import date, datetime
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from pydantic import BaseModel

from .config import Settings, get_settings
from .parsing import TZ
from .service import fetch_many
from .set_client import SetClient

log = logging.getLogger("api")
SYMBOL_RE = re.compile(r"^[A-Z0-9&.\-]{1,20}$")


@asynccontextmanager
async def lifespan(app: FastAPI):
    client = SetClient(app.state.settings)
    await client.start()
    app.state.fetcher = client
    try:
        yield
    finally:
        await client.close()


def create_app(settings: Settings | None = None, fetcher: Any = None) -> FastAPI:
    """`fetcher` can be injected (tests); otherwise a real SetClient is created."""
    app = FastAPI(title="SET Dividend API", version="1.0.0", lifespan=None if fetcher else lifespan)
    app.state.settings = settings or get_settings()
    if fetcher is not None:
        app.state.fetcher = fetcher

    class DividendItem(BaseModel):
        symbol: str
        dps: str | None
        currency: str | None
        xd_date: date | None
        payment_date: date | None
        paid_up_shares: int | None
        warnings: list[str]

    class ErrorItem(BaseModel):
        symbol: str
        code: str
        detail: str | None = None

    class DividendResponse(BaseModel):
        fetched_at: datetime
        results: list[DividendItem]
        errors: list[ErrorItem]

    def require_key(request: Request, x_api_key: str | None = Header(default=None)) -> None:
        keys = request.app.state.settings.api_keys
        if not keys:
            return  # auth disabled (local dev)
        if not x_api_key or not any(secrets.compare_digest(x_api_key, k) for k in keys):
            raise HTTPException(401, "missing or invalid X-API-Key")

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/v1/dividends", response_model=DividendResponse, dependencies=[Depends(require_key)])
    async def dividends(
        request: Request,
        symbol: str = Query(..., description="Comma-separated, e.g. ADVANC,PTT,GULF"),
    ) -> DividendResponse:
        settings: Settings = request.app.state.settings
        symbols = list(dict.fromkeys(s.strip().upper() for s in symbol.split(",") if s.strip()))
        if not symbols or len(symbols) > settings.max_symbols:
            raise HTTPException(400, f"symbol must contain 1-{settings.max_symbols} symbols")
        bad = [s for s in symbols if not SYMBOL_RE.match(s)]
        if bad:
            raise HTTPException(400, f"invalid symbol(s): {bad}")

        now = datetime.now(TZ)
        results, errors = await fetch_many(symbols, request.app.state.fetcher, settings, now.date())
        if errors and not results and all(e["code"] == "NOT_FOUND" for e in errors):
            raise HTTPException(404, "none of the requested symbols were found")
        order = {s: i for i, s in enumerate(symbols)}
        results.sort(key=lambda r: order[r["symbol"]])
        return DividendResponse(
            fetched_at=now.replace(microsecond=0), results=results, errors=errors
        )

    return app
