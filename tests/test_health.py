
from tests.conftest import request_json


def test_health_does_not_require_auth(http_server):
    status, data = request_json(http_server, "GET", "/health")
    assert status == 200
    assert data == {"status": "ok", "service": "spliit-bridge"}


def test_healthz_does_not_require_auth(http_server):
    status, data = request_json(http_server, "GET", "/healthz")
    assert status == 200
    assert data["status"] == "ok"


def test_bridge_prefix_is_supported(http_server):
    status, data = request_json(http_server, "GET", "/bridge/health")
    assert status == 200
    assert data["status"] == "ok"
