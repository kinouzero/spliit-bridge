"""Regression tests for malformed input and fail-closed validation."""
import json

import pytest

import app.server as server
from tests.conftest import request_json
from tests.test_expenses import valid_expense


def test_missing_groups_is_rejected(config_file):
    config_file.write_text('{}', encoding='utf-8')
    with pytest.raises(ValueError, match='Invalid config structure'):
        server.load_config()


def test_group_and_expense_ids_are_not_participants():
    details = {
        'group': {'id': 'group-1', 'name': 'Household',
                  'participants': [{'id': 'p1', 'name': 'Alice'}]},
        'expenses': [{'id': 'expense-1', 'name': 'Lunch'}],
        'participantsWithExpenses': ['old-participant'],
    }
    assert server.participant_ids_from_details(details) == {'p1'}


def test_amount_precision_is_not_silently_rounded():
    with pytest.raises(ValueError, match='two decimal places'):
        server.parse_amount('1.00000000000000000000000000001')


def test_non_ascii_api_key_is_rejected(http_server):
    status, data = request_json(http_server, 'GET', '/api/groups',
                                headers={'X-API-Key': 'é'})
    assert (status, data) == (401, {'error': 'unauthorized'})


def test_stale_rate_limit_clients_are_removed(config_file, monkeypatch):
    monkeypatch.setattr(server.time, 'monotonic', lambda: 0)
    assert not server.rate_limited('old-client')
    monkeypatch.setattr(server.time, 'monotonic', lambda: server.RATE_WINDOW)
    assert not server.rate_limited('new-client')
    assert 'old-client' not in server._requests


def test_invalid_config_is_server_error(http_server, config_file, auth_headers):
    config_file.write_text('{"groups": "invalid"}', encoding='utf-8')
    status, data = request_json(http_server, 'POST', '/api/expenses/preview',
                                body=valid_expense(), headers=auth_headers)
    assert (status, data) == (502, {'error': 'upstream_or_config_error'})


def test_large_content_length_is_rejected_without_conversion_error(http_server, auth_headers):
    http_server.request('POST', '/api/expenses/preview', body=b'', headers={
        **auth_headers, 'Content-Type': 'application/json', 'Content-Length': '9' * 5000,
    })
    response = http_server.getresponse()
    assert response.status == 413
    assert json.loads(response.read()) == {'error': 'request_too_large'}


def test_transfer_encoding_is_rejected(http_server, auth_headers):
    http_server.request('POST', '/api/expenses/preview', body=b'{}', headers={
        **auth_headers, 'Content-Type': 'application/json', 'Transfer-Encoding': 'chunked',
    })
    response = http_server.getresponse()
    assert response.status == 400
    assert json.loads(response.read()) == {'error': 'transfer_encoding_not_supported'}


def test_deep_json_is_rejected(http_server, auth_headers):
    payload = b'[' * 2000 + b'0' + b']' * 2000
    http_server.request('POST', '/api/expenses/preview', body=payload, headers={
        **auth_headers, 'Content-Type': 'application/json',
    })
    response = http_server.getresponse()
    assert response.status == 400
    assert json.loads(response.read())['error'] in {'invalid_json', 'json_object_required'}
