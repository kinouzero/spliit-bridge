
import app.server as server
from tests.conftest import request_json


def test_rate_limit_blocks_after_limit(http_server, auth_headers, monkeypatch):
    monkeypatch.setattr(server, "RATE_LIMIT", 2)

    for _ in range(2):
        status, _ = request_json(
            http_server,
            "GET",
            "/api/groups",
            headers=auth_headers,
        )
        assert status == 200

    status, data = request_json(
        http_server,
        "GET",
        "/api/groups",
        headers=auth_headers,
    )
    assert status == 429
    assert data == {"error": "rate_limited"}
