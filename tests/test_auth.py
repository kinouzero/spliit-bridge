
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


def test_disabled_api_key_rejects_all_credentials(http_server, auth_headers, monkeypatch):
    import app.server as server

    monkeypatch.setattr(server, 'API_KEY', '')
    assert request_json(http_server, 'GET', '/api/groups', headers=auth_headers) == (
        401, {'error': 'unauthorized'})


def test_matching_credential_sources_are_accepted(http_server, auth_headers):
    headers = {**auth_headers, 'Authorization': f"bEaReR   {auth_headers['X-API-Key']}  "}
    assert request_json(http_server, 'GET', '/api/groups', headers=headers)[0] == 200


def test_other_auth_schemes_are_rejected(http_server):
    assert request_json(http_server, 'GET', '/api/groups', headers={'Authorization': 'Basic dGVzdA=='}) == (
        401, {'error': 'unauthorized'})


def test_non_ascii_bearer_is_rejected(http_server):
    assert request_json(http_server, 'GET', '/api/groups', headers={'Authorization': 'Bearer é'}) == (
        401, {'error': 'unauthorized'})
