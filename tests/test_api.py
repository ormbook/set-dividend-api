"""HTTP-level tests. Skipped automatically if fastapi/httpx are not installed."""
import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from app.config import Settings  # noqa: E402
from app.errors import SetNotFound  # noqa: E402
from app.main import create_app  # noqa: E402

S = Settings()
GOOD_CA = [{"caType": "XD", "xDate": "2026-11-20", "paymentDate": "2026-12-18", "dividend": "2.5"}]


class FakeFetcher:
    def __init__(self, routes):
        self.routes = routes

    async def get_json(self, path):
        v = self.routes[path]
        if isinstance(v, Exception):
            raise v
        return v


def make_client(routes, settings=None):
    app = create_app(settings=settings or S, fetcher=FakeFetcher(routes))
    return TestClient(app)


def routes_for(sym, ca=GOOD_CA, pf=None):
    return {
        S.corporate_action_path.format(symbol=sym): ca,
        S.profile_path.format(symbol=sym): pf if pf is not None else {"paidUpShare": 100},
    }


def test_ok_response_shape_and_order():
    routes = {**routes_for("PTT"), **routes_for("GULF")}
    r = make_client(routes).get("/v1/dividends", params={"symbol": "gulf, ptt,GULF"})
    assert r.status_code == 200
    body = r.json()
    assert [x["symbol"] for x in body["results"]] == ["GULF", "PTT"]  # request order, de-duplicated
    first = body["results"][0]
    assert first["dps"] == "2.5" and first["xd_date"] == "2026-11-20"
    assert first["paid_up_shares"] == 100 and body["errors"] == []
    assert "fetched_at" in body


def test_partial_failure_is_200_with_errors():
    routes = {**routes_for("PTT"), **routes_for("ZZZ", ca=SetNotFound("x"))}
    r = make_client(routes).get("/v1/dividends", params={"symbol": "PTT,ZZZ"})
    assert r.status_code == 200
    assert r.json()["errors"] == [{"symbol": "ZZZ", "code": "NOT_FOUND", "detail": None}]


def test_all_not_found_is_404():
    routes = routes_for("ZZZ", ca=SetNotFound("x"), pf=SetNotFound("x"))
    assert make_client(routes).get("/v1/dividends", params={"symbol": "ZZZ"}).status_code == 404


@pytest.mark.parametrize("symbol", ["", ",,", "BAD SYMBOL!", ",".join(f"S{i}" for i in range(51))])
def test_bad_symbols_are_400(symbol):
    assert make_client({}).get("/v1/dividends", params={"symbol": symbol}).status_code == 400


def test_missing_symbol_param_is_422():
    assert make_client({}).get("/v1/dividends").status_code == 422


def test_api_key_enforced_when_configured():
    settings = Settings(api_keys=frozenset({"secret"}))
    client = make_client(routes_for("PTT"), settings)
    assert client.get("/v1/dividends", params={"symbol": "PTT"}).status_code == 401
    assert client.get("/v1/dividends", params={"symbol": "PTT"}, headers={"X-API-Key": "wrong"}).status_code == 401
    ok = client.get("/v1/dividends", params={"symbol": "PTT"}, headers={"X-API-Key": "secret"})
    assert ok.status_code == 200


def test_healthz_needs_no_key():
    settings = Settings(api_keys=frozenset({"secret"}))
    assert make_client({}, settings).get("/healthz").status_code == 200
