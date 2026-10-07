
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


def test_sliding_window_expires_only_old_requests(config_file, monkeypatch):
    monkeypatch.setattr(server, 'RATE_LIMIT', 2)
    monkeypatch.setattr(server.time, 'monotonic', lambda: 0)
    assert not server.rate_limited('client')
    monkeypatch.setattr(server.time, 'monotonic', lambda: 30)
    assert not server.rate_limited('client')
    assert server.rate_limited('client')
    monkeypatch.setattr(server.time, 'monotonic', lambda: 60)
    assert not server.rate_limited('client')
    assert server.rate_limited('client')
    monkeypatch.setattr(server.time, 'monotonic', lambda: 90)
    assert not server.rate_limited('client')


def test_cleanup_preserves_recently_active_clients(config_file, monkeypatch):
    monkeypatch.setattr(server.time, 'monotonic', lambda: 0)
    assert not server.rate_limited('active')
    assert not server.rate_limited('inactive')
    monkeypatch.setattr(server.time, 'monotonic', lambda: 30)
    assert not server.rate_limited('active')
    monkeypatch.setattr(server.time, 'monotonic', lambda: 60)
    assert not server.rate_limited('new')
    assert 'active' in server._requests
    assert 'inactive' not in server._requests


def test_rate_limit_is_atomic_for_concurrent_requests(config_file, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    monkeypatch.setattr(server, 'RATE_LIMIT', 7)
    monkeypatch.setattr(server.time, 'monotonic', lambda: 0)
    with ThreadPoolExecutor(max_workers=16) as executor:
        results = list(executor.map(server.rate_limited, ['same-client'] * 64))
    assert results.count(False) == 7
    assert results.count(True) == 57
    assert not server.rate_limited('different-client')
