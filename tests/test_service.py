import asyncio
from datetime import date

from app.config import Settings
from app.errors import SetNotFound, SetUpstreamError
from app.service import fetch_many, fetch_symbol

TODAY = date(2026, 11, 6)
S = Settings()


class FakeFetcher:
    """Maps URL path -> payload or exception."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    async def get_json(self, path):
        self.calls.append(path)
        value = self.routes[path]
        if isinstance(value, Exception):
            raise value
        return value


def ca_path(sym):
    return S.corporate_action_path.format(symbol=sym)


def pf_path(sym):
    return S.profile_path.format(symbol=sym)


GOOD_CA = [{"caType": "XD", "xDate": "2026-11-20", "paymentDate": "2026-12-18", "dividend": "2.5", "currency": "Baht"}]


def test_fetch_symbol_happy_path():
    f = FakeFetcher({ca_path("PTT"): GOOD_CA, pf_path("PTT"): {"paidUpShare": 28562996250}})
    out = asyncio.run(fetch_symbol("PTT", f, S, TODAY))
    assert out == {
        "symbol": "PTT",
        "dps": "2.5",
        "currency": "Baht",
        "xd_date": date(2026, 11, 20),
        "payment_date": date(2026, 12, 18),
        "paid_up_shares": 28562996250,
        "warnings": [],
    }


def test_missing_paid_up_gives_null_and_warning_not_error():
    f = FakeFetcher({ca_path("PTT"): GOOD_CA, pf_path("PTT"): {"name": "x"}})
    out = asyncio.run(fetch_symbol("PTT", f, S, TODAY))
    assert out["paid_up_shares"] is None
    assert "PAID_UP_SHARES_NOT_FOUND" in out["warnings"]


def test_no_dividend_history_gives_nulls_and_warning():
    f = FakeFetcher({ca_path("NEW"): [], pf_path("NEW"): {"paidUpShare": 10}})
    out = asyncio.run(fetch_symbol("NEW", f, S, TODAY))
    assert out["dps"] is None and out["xd_date"] is None
    assert "NO_DIVIDEND_FOUND" in out["warnings"]


def test_fetch_many_isolates_failures_and_classifies_them():
    f = FakeFetcher(
        {
            ca_path("GOOD"): GOOD_CA,
            pf_path("GOOD"): {"paidUpShare": 5},
            ca_path("MISSING"): SetNotFound("x"),
            pf_path("MISSING"): SetNotFound("x"),
            ca_path("DOWN"): SetUpstreamError("boom"),
            pf_path("DOWN"): {"paidUpShare": 5},
            ca_path("BAD"): {"weird": True},
            pf_path("BAD"): {"paidUpShare": 5},
        }
    )
    results, errors = asyncio.run(fetch_many(["GOOD", "MISSING", "DOWN", "BAD"], f, S, TODAY))
    assert [r["symbol"] for r in results] == ["GOOD"]
    codes = {e["symbol"]: e["code"] for e in errors}
    assert codes == {"MISSING": "NOT_FOUND", "DOWN": "UPSTREAM_ERROR", "BAD": "PARSE_ERROR"}


def test_upstream_error_detail_is_reported():
    f = FakeFetcher(
        {
            ca_path("X"): SetUpstreamError("HTTP 403 from https://www.set.or.th/api/set/stock/X/corporate-action"),
            pf_path("X"): {"paidUpShare": 5},
        }
    )
    _, errors = asyncio.run(fetch_many(["X"], f, S, TODAY))
    assert errors[0]["code"] == "UPSTREAM_ERROR" and "HTTP 403" in errors[0]["detail"]
