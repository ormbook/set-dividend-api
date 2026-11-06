"""Pure parsing / selection logic. No network, no framework: easy to test."""
from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

from .errors import SetParseError

TZ = ZoneInfo("Asia/Bangkok")
_EMPTY = (None, "", "-", "--", "N/A", "n/a")

# SET payload key candidates. Keys are compared case-insensitively with
# underscores/dashes removed, so "xDate", "x_date" and "XDATE" all match.
KEYS_CA_TYPE = ("caType", "type")
KEYS_DIVIDEND = ("dividend", "dividendPerShare", "dps")
KEYS_XD_DATE = ("xDate", "xdDate", "exDate", "xd")
KEYS_PAYMENT_DATE = ("paymentDate", "payDate", "dividendPaymentDate")
KEYS_CURRENCY = ("currency",)
KEYS_PAID_UP = (
    "paidUpShare",
    "paidUpShares",
    "paidUpCapitalShare",
    "paidupShare",
    "issuedShare",
    "issuedShares",
)


def norm_key(key: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(key).lower())


def pick(obj: Mapping[str, Any], names: Iterable[str]) -> Any:
    """First non-empty value among candidate keys (tolerant key matching)."""
    index = {norm_key(k): v for k, v in obj.items()}
    for name in names:
        value = index.get(norm_key(name))
        if value not in _EMPTY:
            return value
    return None


def parse_date(value: Any) -> date | None:
    """ISO 8601 or dd/mm/yyyy. Buddhist-era years (> 2400) are converted."""
    if value in _EMPTY:
        return None
    if isinstance(value, datetime):
        return value.astimezone(TZ).date() if value.tzinfo else value.date()
    if isinstance(value, date):
        return value

    text = str(value).strip()
    try:
        if re.match(r"^\d{4}-\d{2}-\d{2}", text):
            if len(text) > 10:  # has a time part: honour the offset, then use Thai calendar day
                parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
                year_fix = parsed.year > 2400
                if year_fix:
                    parsed = parsed.replace(year=parsed.year - 543)
                return parsed.astimezone(TZ).date() if parsed.tzinfo else parsed.date()
            year, month, day = (int(p) for p in text[:10].split("-"))
        else:
            m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", text)
            if not m:
                raise ValueError("unrecognised format")
            day, month, year = (int(g) for g in m.groups())
        if year > 2400:
            year -= 543
        return date(year, month, day)
    except ValueError as exc:
        raise SetParseError(f"bad date {value!r}: {exc}") from exc


def parse_decimal(value: Any) -> Decimal | None:
    if value in _EMPTY:
        return None
    try:
        number = Decimal(str(value).replace(",", "").strip())
    except InvalidOperation as exc:
        raise SetParseError(f"bad number {value!r}") from exc
    if not number.is_finite() or number < 0:
        raise SetParseError(f"number out of range {value!r}")
    return number


def parse_share_count(value: Any) -> int | None:
    number = parse_decimal(value)
    if number is None:
        return None
    if number != number.to_integral_value():
        raise SetParseError(f"share count is not an integer: {value!r}")
    if number <= 0:
        raise SetParseError(f"share count must be positive: {value!r}")
    return int(number)


def unwrap_list(payload: Any) -> list[dict[str, Any]]:
    """SET returns either a bare list or an object wrapping one."""
    if isinstance(payload, list):
        return [p for p in payload if isinstance(p, dict)]
    if isinstance(payload, dict):
        for key in ("data", "items", "corporateActions", "corporateAction", "result"):
            inner = payload.get(key)
            if isinstance(inner, list):
                return [p for p in inner if isinstance(p, dict)]
    raise SetParseError("corporate action payload is neither a list nor a wrapped list")


def select_dividend(actions: list[dict[str, Any]], today: date) -> dict[str, Any] | None:
    """Choose ONE dividend event using a fixed, documented rule.

    1. Only XD (dividend) events that have an XD date.
    2. Prefer events with a cash amount over those without (e.g. stock dividends).
    3. Prefer the nearest upcoming/ongoing XD date (>= today); if there is none,
       the most recent past one.
    """
    events: list[dict[str, Any]] = []
    for action in actions:
        ca_type = pick(action, KEYS_CA_TYPE)
        if ca_type is not None and str(ca_type).strip().upper() != "XD":
            continue
        xd = parse_date(pick(action, KEYS_XD_DATE))
        if xd is None:
            continue
        dps = parse_decimal(pick(action, KEYS_DIVIDEND))
        pay = parse_date(pick(action, KEYS_PAYMENT_DATE))
        if pay is not None and pay < xd:
            raise SetParseError(f"payment date {pay} is before XD date {xd}")
        events.append(
            {
                "dps": dps,
                "xd_date": xd,
                "payment_date": pay,
                "currency": pick(action, KEYS_CURRENCY),
            }
        )
    if not events:
        return None

    with_cash = [e for e in events if e["dps"] is not None]
    pool = with_cash or events
    upcoming = sorted((e for e in pool if e["xd_date"] >= today), key=lambda e: e["xd_date"])
    if upcoming:
        return upcoming[0]
    return max(pool, key=lambda e: e["xd_date"])


def extract_paid_up(profile: Any) -> int | None:
    """Find the paid-up share count in the profile payload (None if absent)."""
    if not isinstance(profile, dict):
        raise SetParseError("profile payload is not an object")
    value = pick(profile, KEYS_PAID_UP)
    if value is None:
        # look one level down (some payloads nest share data)
        for inner in profile.values():
            if isinstance(inner, dict):
                value = pick(inner, KEYS_PAID_UP)
                if value is not None:
                    break
    return parse_share_count(value)
