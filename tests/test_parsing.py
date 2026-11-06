from datetime import date
from decimal import Decimal

import pytest

from app.errors import SetParseError
from app.parsing import (
    extract_paid_up,
    parse_date,
    parse_decimal,
    parse_share_count,
    select_dividend,
    unwrap_list,
)

TODAY = date(2026, 11, 6)


# ---- parse_date -------------------------------------------------------------
def test_parse_date_iso_date_only():
    assert parse_date("2026-08-20") == date(2026, 8, 20)


def test_parse_date_iso_with_bangkok_offset():
    assert parse_date("2026-08-20T00:00:00+07:00") == date(2026, 8, 20)


def test_parse_date_utc_midnight_thai_is_next_day_logic():
    # 17:00Z on the 19th is 00:00 on the 20th in Bangkok
    assert parse_date("2026-08-19T17:00:00Z") == date(2026, 8, 20)


def test_parse_date_dd_mm_yyyy():
    assert parse_date("06/11/2026") == date(2026, 11, 6)


def test_parse_date_buddhist_year_converted():
    assert parse_date("06/11/2569") == date(2026, 11, 6)
    assert parse_date("2569-11-06") == date(2026, 11, 6)


@pytest.mark.parametrize("empty", [None, "", "-", "N/A"])
def test_parse_date_empty_is_none(empty):
    assert parse_date(empty) is None


def test_parse_date_garbage_raises():
    with pytest.raises(SetParseError):
        parse_date("tomorrow")
    with pytest.raises(SetParseError):
        parse_date("2026-13-40")


# ---- numbers ----------------------------------------------------------------
def test_parse_decimal_keeps_precision():
    assert parse_decimal("1,234.5600") == Decimal("1234.5600")
    assert parse_decimal(0.1) == Decimal("0.1")


def test_parse_decimal_rejects_negative_and_nan():
    with pytest.raises(SetParseError):
        parse_decimal("-1")
    with pytest.raises(SetParseError):
        parse_decimal("NaN")
    with pytest.raises(SetParseError):
        parse_decimal("abc")


def test_parse_share_count():
    assert parse_share_count("2,973,095,330") == 2973095330
    assert parse_share_count(1000.0) == 1000
    assert parse_share_count(None) is None
    with pytest.raises(SetParseError):
        parse_share_count("1.5")
    with pytest.raises(SetParseError):
        parse_share_count("0")


# ---- select_dividend --------------------------------------------------------
def ca(x, pay, div, t="XD"):
    return {"caType": t, "xDate": x, "paymentDate": pay, "dividend": div, "currency": "Baht"}


def test_picks_nearest_upcoming_over_past():
    actions = [
        ca("2026-03-10", "2026-04-10", "5.00"),
        ca("2026-11-20", "2026-12-18", "2.50"),
        ca("2026-12-30", "2027-01-20", "1.00"),
    ]
    ev = select_dividend(actions, TODAY)
    assert ev["xd_date"] == date(2026, 11, 20)
    assert ev["dps"] == Decimal("2.50")
    assert ev["payment_date"] == date(2026, 12, 18)


def test_falls_back_to_latest_past_when_none_upcoming():
    actions = [ca("2025-08-20", "2025-09-10", "4.00"), ca("2026-08-20", "2026-09-10", "4.30")]
    assert select_dividend(actions, TODAY)["dps"] == Decimal("4.30")


def test_xd_today_counts_as_upcoming():
    ev = select_dividend([ca("2026-11-06", "2026-11-30", "1.00"), ca("2026-05-01", "2026-05-20", "9")], TODAY)
    assert ev["xd_date"] == TODAY


def test_ignores_non_xd_events_and_meetings():
    actions = [{"caType": "XM", "xDate": "2026-11-10", "agenda": "AGM"}, ca("2026-08-20", "2026-09-10", "4.30")]
    assert select_dividend(actions, TODAY)["xd_date"] == date(2026, 8, 20)


def test_prefers_cash_over_stock_dividend():
    actions = [ca("2026-11-20", None, None), ca("2026-08-20", "2026-09-10", "4.30")]
    ev = select_dividend(actions, TODAY)
    assert ev["dps"] == Decimal("4.30")


def test_stock_dividend_only_returns_event_without_dps():
    ev = select_dividend([ca("2026-11-20", None, "-")], TODAY)
    assert ev["dps"] is None and ev["xd_date"] == date(2026, 11, 20)


def test_no_events_returns_none():
    assert select_dividend([], TODAY) is None
    assert select_dividend([{"caType": "XM", "xDate": "2026-11-10"}], TODAY) is None


def test_payment_before_xd_is_parse_error():
    with pytest.raises(SetParseError):
        select_dividend([ca("2026-11-20", "2026-11-01", "1")], TODAY)


def test_key_variants_are_tolerated():
    actions = [{"ca_type": "XD", "x_date": "2026-11-20", "payment_date": "2026-12-01", "Dividend": "3"}]
    ev = select_dividend(actions, TODAY)
    assert ev["dps"] == Decimal("3") and ev["xd_date"] == date(2026, 11, 20)


# ---- payload helpers --------------------------------------------------------
def test_unwrap_list_variants():
    assert unwrap_list([{"a": 1}]) == [{"a": 1}]
    assert unwrap_list({"data": [{"a": 1}]}) == [{"a": 1}]
    with pytest.raises(SetParseError):
        unwrap_list({"unexpected": 1})
    with pytest.raises(SetParseError):
        unwrap_list("html error page")


def test_extract_paid_up_top_level_and_nested():
    assert extract_paid_up({"paidUpShare": 2973095330}) == 2973095330
    assert extract_paid_up({"profile": {"issuedShare": "1,000"}}) == 1000
    assert extract_paid_up({"name": "x"}) is None
    with pytest.raises(SetParseError):
        extract_paid_up([1, 2])
