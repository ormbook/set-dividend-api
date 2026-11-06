"""Orchestration: fetch both SET payloads for a symbol and build one record."""
from __future__ import annotations

import asyncio
from datetime import date
from typing import Any

from .config import Settings
from .errors import SetNotFound, SetParseError, SetUpstreamError
from .parsing import extract_paid_up, select_dividend, unwrap_list
from .set_client import JsonFetcher


async def fetch_symbol(symbol: str, fetcher: JsonFetcher, settings: Settings, today: date) -> dict[str, Any]:
    """Return the record for one symbol, or raise SetNotFound/SetUpstreamError/SetParseError."""
    ca_path = settings.corporate_action_path.format(symbol=symbol)
    profile_path = settings.profile_path.format(symbol=symbol)

    ca_payload, profile_payload = await asyncio.gather(
        fetcher.get_json(ca_path), fetcher.get_json(profile_path)
    )

    warnings: list[str] = []

    event = select_dividend(unwrap_list(ca_payload), today)
    if event is None:
        warnings.append("NO_DIVIDEND_FOUND")
        event = {"dps": None, "xd_date": None, "payment_date": None, "currency": None}
    elif event["dps"] is None:
        warnings.append("NO_CASH_DIVIDEND_AMOUNT")

    paid_up = extract_paid_up(profile_payload)
    if paid_up is None:
        warnings.append("PAID_UP_SHARES_NOT_FOUND")

    return {
        "symbol": symbol,
        "dps": None if event["dps"] is None else format(event["dps"], "f"),
        "currency": event["currency"],
        "xd_date": event["xd_date"],
        "payment_date": event["payment_date"],
        "paid_up_shares": paid_up,
        "warnings": warnings,
    }


async def fetch_many(
    symbols: list[str], fetcher: JsonFetcher, settings: Settings, today: date
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    outcomes = await asyncio.gather(
        *(fetch_symbol(s, fetcher, settings, today) for s in symbols), return_exceptions=True
    )
    results: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for symbol, outcome in zip(symbols, outcomes):
        if isinstance(outcome, SetNotFound):
            errors.append({"symbol": symbol, "code": "NOT_FOUND"})
        elif isinstance(outcome, SetUpstreamError):
            errors.append({"symbol": symbol, "code": "UPSTREAM_ERROR"})
        elif isinstance(outcome, SetParseError):
            errors.append({"symbol": symbol, "code": "PARSE_ERROR", "detail": str(outcome)})
        elif isinstance(outcome, BaseException):
            errors.append({"symbol": symbol, "code": "INTERNAL_ERROR"})
        else:
            results.append(outcome)
    return results, errors
