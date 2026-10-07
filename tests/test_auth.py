
from tests.conftest import request_json


def test_missing_api_key_returns_401(http_server):
    status, data = request_json(http_server, "GET", "/api/groups")
    assert status == 401
    assert data == {"error": "unauthorized"}


def test_invalid_api_key_returns_401(http_server):
    status, data = request_json(
        http_server,
        "GET",
        "/api/groups",
        headers={"X-API-Key": "wrong"},
    )
    assert status == 401
    assert data == {"error": "unauthorized"}


def test_x_api_key_is_accepted(http_server, auth_headers):
    status, data = request_json(
        http_server,
        "GET",
        "/api/groups",
        headers=auth_headers,
    )
    assert status == 200
    assert data["data"]["groups"][0]["id"] == "group-1"


def test_bearer_token_is_accepted(http_server):
    status, data = request_json(
        http_server,
        "GET",
        "/api/groups",
        headers={"Authorization": "Bearer " + ("test-" + "x" * 40)},
    )
    assert status == 200
    assert len(data["data"]["groups"]) == 2


def test_conflicting_credentials_are_rejected(http_server):
    status, data = request_json(
        http_server,
        "GET",
        "/api/groups",
        headers={
            "X-API-Key": "test-" + ("x" * 40),
            "Authorization": "Bearer different",
        },
    )
    assert status == 401
    assert data == {"error": "unauthorized"}
