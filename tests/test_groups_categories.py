
from tests.conftest import request_json


def test_list_groups(http_server, auth_headers):
    status, data = request_json(http_server, "GET", "/api/groups", headers=auth_headers)
    assert status == 200
    assert data["data"]["groups"] == [
        {"id": "group-1", "name": "Test Group"},
        {"id": "group_2", "name": "Second Group"},
    ]


def test_unknown_route_returns_404(http_server, auth_headers):
    status, data = request_json(http_server, "GET", "/api/nope", headers=auth_headers)
    assert status == 404
    assert data == {"error": "not_found"}


def test_unknown_group_details_returns_404(http_server, auth_headers):
    status, data = request_json(
        http_server,
        "GET",
        "/api/groups/unknown/details",
        headers=auth_headers,
    )
    assert status == 404
    assert data == {"error": "not_found"}


def test_categories_are_forwarded_to_spliit(http_server, auth_headers, upstream):
    status, data = request_json(
        http_server,
        "GET",
        "/api/categories",
        headers=auth_headers,
    )
    assert status == 200
    assert data["data"] == [{"id": 1, "name": "Food"}]
    assert any("categories.list" in path for _, path, _ in upstream.requests)


def test_group_details_are_forwarded_to_spliit(
    http_server, auth_headers, upstream
):
    status, data = request_json(
        http_server,
        "GET",
        "/api/groups/group-1/details",
        headers=auth_headers,
    )
    assert status == 200
    assert data["data"]["members"][0]["id"] == "p1"
