
from tests.conftest import request_json
import app.server as server


def valid_expense():
    return {
        "groupId": "group-1",
        "title": "Lunch",
        "amount": "12.50",
        "expenseDate": "2026-10-07T12:00:00Z",
        "paidBy": "p1",
        "paidFor": [
            {"participant": "p1", "shares": 1},
            {"participant": "p2", "shares": 1},
        ],
        "category": 1,
        "splitMode": "EVENLY",
        "notes": "Test expense",
    }


def test_preview_does_not_create_expense(
    http_server, auth_headers, upstream
):
    status, data = request_json(
        http_server,
        "POST",
        "/api/expenses/preview",
        body=valid_expense(),
        headers=auth_headers,
    )
    assert status == 200
    assert data["mode"] == "dry-run"
    assert data["creation_enabled"] is False
    assert data["would_create"]["amount"] == 1250
    assert not any(
        method == "POST" and "groups.expenses.create" in path
        for method, path, _ in upstream.requests
    )


def test_creation_is_disabled_by_default(
    http_server, auth_headers, upstream
):
    status, data = request_json(
        http_server,
        "POST",
        "/api/expenses",
        body=valid_expense(),
        headers=auth_headers,
    )
    assert status == 403
    assert data == {"error": "creation_disabled"}
    assert not any(
        method == "POST" and "groups.expenses.create" in path
        for method, path, _ in upstream.requests
    )


def test_creation_can_be_enabled(
    http_server, auth_headers, upstream, monkeypatch
):
    monkeypatch.setattr(server, "ALLOW_CREATE", True)

    status, data = request_json(
        http_server,
        "POST",
        "/api/expenses",
        body=valid_expense(),
        headers=auth_headers,
    )
    assert status == 201
    assert data["created"] is True
    assert any(
        method == "POST" and "groups.expenses.create" in path
        for method, path, _ in upstream.requests
    )


def test_invalid_json_is_rejected(http_server, auth_headers):
    raw = b"{invalid"
    headers = {
        **auth_headers,
        "Content-Type": "application/json",
        "Content-Length": str(len(raw)),
    }
    http_server.request("POST", "/api/expenses/preview", body=raw, headers=headers)
    response = http_server.getresponse()
    response.read()
    assert response.status == 400


def test_oversized_body_is_rejected(http_server, auth_headers):
    raw = b"x" * (server.MAX_BODY + 1)
    headers = {
        **auth_headers,
        "Content-Type": "application/json",
        "Content-Length": str(len(raw)),
    }
    http_server.request("POST", "/api/expenses/preview", body=raw, headers=headers)
    response = http_server.getresponse()
    response.read()
    assert response.status == 413


def test_non_json_body_is_rejected(http_server, auth_headers):
    raw = b"{}"
    headers = {
        **auth_headers,
        "Content-Type": "text/plain",
        "Content-Length": str(len(raw)),
    }
    http_server.request("POST", "/api/expenses/preview", body=raw, headers=headers)
    response = http_server.getresponse()
    response.read()
    assert response.status == 415


def test_method_not_allowed(http_server):
    http_server.request("DELETE", "/health")
    response = http_server.getresponse()
    response.read()
    assert response.status == 405
