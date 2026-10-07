
from decimal import Decimal
import pytest
import app.server as server


def test_valid_amounts_are_parsed():
    assert server.parse_amount("12.34") == (Decimal("12.34"), 1234)
    assert server.parse_amount("12,34") == (Decimal("12.34"), 1234)
    assert server.parse_amount(100000) == (Decimal("100000"), 10000000)


@pytest.mark.parametrize("value", [0, -1, 100000.01, "NaN", "Infinity", True, None, [], {}])
def test_invalid_amounts_are_rejected(value):
    with pytest.raises(ValueError):
        server.parse_amount(value)


@pytest.mark.parametrize("value", ["12.345", "0.001", "1.999"])
def test_more_than_two_decimal_places_are_rejected(value):
    with pytest.raises(ValueError):
        server.parse_amount(value)


def test_group_id_regex():
    assert server.ID_RE.fullmatch("group-1")
    assert server.ID_RE.fullmatch("ABC_123")
    assert not server.ID_RE.fullmatch("group 1")
    assert not server.ID_RE.fullmatch("group/1")


@pytest.mark.parametrize(
    "mode",
    ["EVENLY", "BY_SHARES", "BY_AMOUNT", "BY_PERCENTAGE"],
)
def test_supported_split_modes(mode):
    assert mode in server.ALLOWED_SPLIT_MODES


def test_invalid_split_mode_is_not_allowed():
    assert "INVALID" not in server.ALLOWED_SPLIT_MODES


@pytest.mark.parametrize("value", [0, -1, 1000001, "NaN", "Infinity", True, [], {}])
def test_invalid_shares_are_rejected(config_file, value):
    body = {
        "groupId": "group-1",
        "title": "Lunch",
        "amount": "10.00",
        "expenseDate": "2026-10-07T12:00:00Z",
        "paidBy": "p1",
        "paidFor": [{"participant": "p1", "shares": value}],
        "category": 1,
        "splitMode": "EVENLY",
    }
    with pytest.raises(ValueError):
        server.parse_expense(body)


def test_parse_expense_normalizes_valid_payload(config_file):
    body = {
        "groupId": "group-1",
        "title": "  Lunch  ",
        "amount": "12.50",
        "expenseDate": "2026-10-07T12:00:00Z",
        "paidBy": "p1",
        "paidFor": [{"participant": "p1", "shares": 1}],
        "category": 1,
        "splitMode": "EVENLY",
        "notes": "Test",
    }
    result = server.parse_expense(body)
    assert result["title"] == "Lunch"
    assert result["amountCents"] == 1250
    assert result["paidFor"] == [{"participant": "p1", "shares": "1"}]


@pytest.mark.parametrize(
    "field,value",
    [
        ("title", ""),
        ("title", "x"),
        ("title", "x" * 201),
        ("expenseDate", "not-a-date"),
        ("category", True),
        ("category", -1),
        ("paidBy", "bad id"),
        ("paidFor", []),
        ("paidFor", [{"participant": "p1"}, {"participant": "p1"}]),
    ],
)
def test_invalid_expense_fields_are_rejected(config_file, field, value):
    body = {
        "groupId": "group-1",
        "title": "Lunch",
        "amount": "10.00",
        "expenseDate": "2026-10-07T12:00:00Z",
        "paidBy": "p1",
        "paidFor": [{"participant": "p1"}],
        "category": 1,
        "splitMode": "EVENLY",
    }
    body[field] = value
    with pytest.raises(ValueError):
        server.parse_expense(body)


def test_notes_allow_newlines(config_file):
    body = {
        "groupId": "group-1",
        "title": "Lunch",
        "amount": "10",
        "expenseDate": "2026-10-07",
        "paidBy": "p1",
        "paidFor": [{"participant": "p1"}],
        "category": 1,
        "splitMode": "EVENLY",
        "notes": "line 1\nline 2",
    }
    assert server.parse_expense(body)["notes"] == "line 1\nline 2"
