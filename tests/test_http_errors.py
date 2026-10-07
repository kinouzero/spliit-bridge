"""Exercise HTTP boundaries over real local sockets, without external services."""
import json
import socket
from unittest.mock import Mock

import pytest

import app.server as server
from tests.conftest import request_json
from tests.test_expenses import valid_expense


@pytest.mark.parametrize('raw', [b'{', b'\xff', b'{"amount":NaN}', b'{"amount":Infinity}'])
def test_bad_json(http_server, auth_headers, raw):
    http_server.request('POST', '/api/expenses/preview', body=raw,
                        headers={**auth_headers, 'Content-Type': 'application/json'})
    response = http_server.getresponse()
    assert response.status == 400
    assert json.loads(response.read()) == {'error': 'invalid_json'}


@pytest.mark.parametrize('body', [[], 'text', 1, True])
def test_json_must_be_object(http_server, auth_headers, body):
    assert request_json(http_server, 'POST', '/api/expenses/preview', body, auth_headers) == (
        400, {'error': 'json_object_required'})


@pytest.mark.parametrize('length,status,error', [
    (None, 411, 'content_length_required'), ('-1', 411, 'content_length_required'),
    ('abc', 411, 'content_length_required'), ('²', 411, 'content_length_required'),
    ('1,2', 411, 'content_length_required'), ('0', 400, 'empty_body'),
    ('000', 400, 'empty_body'), (str(server.MAX_BODY + 1), 413, 'request_too_large'),
])
def test_content_length_validation(http_server, auth_headers, length, status, error):
    http_server.putrequest('POST', '/api/expenses/preview')
    for name, value in {**auth_headers, 'Content-Type': 'application/json'}.items():
        http_server.putheader(name, value)
    if length is not None:
        http_server.putheader('Content-Length', length)
    http_server.endheaders()
    response = http_server.getresponse()
    assert response.status == status
    assert json.loads(response.read()) == {'error': error}


def test_duplicate_content_length(http_server, auth_headers):
    http_server.putrequest('POST', '/api/expenses/preview')
    for name, value in {**auth_headers, 'Content-Type': 'application/json'}.items():
        http_server.putheader(name, value)
    http_server.putheader('Content-Length', '2')
    http_server.putheader('Content-Length', '3')
    http_server.endheaders(b'{}')
    response = http_server.getresponse()
    assert response.status == 400
    assert json.loads(response.read()) == {'error': 'ambiguous_content_length'}


def test_incomplete_body(http_server, auth_headers):
    http_server.request('POST', '/api/expenses/preview', body=b'{', headers={
        **auth_headers, 'Content-Type': 'application/json', 'Content-Length': '2',
    })
    http_server.sock.shutdown(socket.SHUT_WR)
    response = http_server.getresponse()
    assert response.status == 400
    assert json.loads(response.read()) == {'error': 'incomplete_body'}


def test_body_read_timeout(http_server, auth_headers, monkeypatch):
    monkeypatch.setattr(server, 'REQUEST_TIMEOUT', 0.05)
    http_server.request('POST', '/api/expenses/preview', body=b'{', headers={
        **auth_headers, 'Content-Type': 'application/json', 'Content-Length': '2',
    })
    response = http_server.getresponse()
    assert response.status == 408
    assert json.loads(response.read()) == {'error': 'request_timeout'}


@pytest.mark.parametrize('method', ['PUT', 'PATCH', 'DELETE', 'OPTIONS'])
def test_unsupported_methods(http_server, method):
    assert request_json(http_server, method, '/api/expenses') == (405, {'error': 'method_not_allowed'})


@pytest.mark.parametrize('path', ['/bridge', '/bridge?x=1', '/api/groups/bad%20id/details', '/[broken'])
def test_unknown_paths(http_server, auth_headers, path):
    assert request_json(http_server, 'GET', path, headers=auth_headers) == (404, {'error': 'not_found'})


def test_post_unknown_path(http_server, auth_headers):
    assert request_json(http_server, 'POST', '/api/nope', headers=auth_headers) == (404, {'error': 'not_found'})


def test_post_requires_authentication(http_server):
    assert request_json(http_server, 'POST', '/api/expenses/preview', valid_expense()) == (
        401, {'error': 'unauthorized'})


def test_post_is_rate_limited(http_server, auth_headers, monkeypatch):
    monkeypatch.setattr(server, 'RATE_LIMIT', 1)
    request_json(http_server, 'GET', '/api/groups', headers=auth_headers)
    assert request_json(http_server, 'POST', '/api/expenses', valid_expense(), auth_headers) == (
        429, {'error': 'rate_limited'})
    assert request_json(http_server, 'GET', '/health')[0] == 200


def test_security_headers_and_utf8_length(http_server, auth_headers, config_file):
    config_file.write_text(json.dumps({'groups': [{'id': 'a', 'name': 'Café ☕'}]}), encoding='utf-8')
    http_server.request('GET', '/api/groups', headers=auth_headers)
    response = http_server.getresponse()
    raw = response.read()
    assert response.status == 200
    assert len(raw) == int(response.getheader('Content-Length'))
    assert response.getheader('Content-Type') == 'application/json; charset=utf-8'
    assert response.getheader('Cache-Control') == 'no-store'
    assert response.getheader('X-Content-Type-Options') == 'nosniff'
    assert response.getheader('Referrer-Policy') == 'no-referrer'
    assert response.getheader('Connection') == 'close'
    assert 'Python' not in response.getheader('Server')
    assert json.loads(raw)['data']['groups'][0]['name'] == 'Café ☕'


@pytest.mark.parametrize('path', ['/api/groups', '/api/groups/group-1/details'])
def test_config_error_is_fail_closed(http_server, auth_headers, config_file, path):
    config_file.unlink()
    assert request_json(http_server, 'GET', path, headers=auth_headers) == (
        502, {'error': 'upstream_or_config_error'})


@pytest.mark.parametrize('method,path', [('GET', '/api/categories'), ('POST', '/api/expenses/preview')])
def test_upstream_failure_is_sanitized(http_server, auth_headers, monkeypatch, method, path):
    def fail(*args):
        raise RuntimeError('secret upstream response')
    monkeypatch.setattr(server, 'spliit_query', fail)
    status, data = request_json(http_server, method, path,
                                valid_expense() if method == 'POST' else None, auth_headers)
    assert (status, data) == (502, {'error': 'upstream_or_config_error'})


@pytest.mark.parametrize('details,field,value,error', [
    ({}, 'paidBy', 'p1', 'participant_validation_unavailable'),
    ({'group': {'id': 'group-1', 'name': 'Group'}}, 'paidBy', 'group-1', 'participant_validation_unavailable'),
    ({'participants': [{'id': 'p1'}]}, 'paidBy', 'p2', 'invalid_paidBy'),
    ({'participants': [{'id': 'p1'}]}, 'paidFor', [{'participant': 'p2'}], 'invalid_paidFor_participant'),
    ({'group': {'id': 'group-1', 'name': 'Group', 'participants': [{'id': 'p1'}]}},
     'paidBy', 'group-1', 'invalid_paidBy'),
])
def test_participants_validated_before_mutation(
    http_server, auth_headers, monkeypatch, details, field, value, error,
):
    monkeypatch.setattr(server, 'ALLOW_CREATE', True)
    monkeypatch.setattr(server, 'spliit_query', lambda *args: details)
    mutation = Mock()
    monkeypatch.setattr(server, 'spliit_mutation', mutation)
    body = valid_expense()
    body[field] = value
    assert request_json(http_server, 'POST', '/api/expenses', body, auth_headers) == (
        502 if error == 'participant_validation_unavailable' else 400, {'error': error})
    mutation.assert_not_called()


def test_invalid_expense_returns_400(http_server, auth_headers):
    assert request_json(http_server, 'POST', '/api/expenses/preview', {}, auth_headers) == (
        400, {'error': 'invalid_expense', 'message': 'Missing required fields'})


def test_non_serializable_upstream_result(http_server, auth_headers, monkeypatch):
    monkeypatch.setattr(server, 'spliit_query', lambda *args: {'bad': {1, 2}})
    assert request_json(http_server, 'GET', '/api/categories', headers=auth_headers) == (
        500, {'error': 'internal_error'})


def test_maximum_body_size_is_accepted(http_server, auth_headers):
    payload = b'{}' + b' ' * (server.MAX_BODY - 2)
    http_server.request('POST', '/api/expenses/preview', body=payload, headers={
        **auth_headers, 'Content-Type': 'application/json; charset=utf-8',
    })
    response = http_server.getresponse()
    assert response.status == 400
    assert json.loads(response.read()) == {'error': 'invalid_expense', 'message': 'Missing required fields'}


def test_content_length_leading_zeroes_are_safe(http_server, auth_headers):
    http_server.request('POST', '/api/expenses/preview', body=b'{}', headers={
        **auth_headers, 'Content-Type': 'application/json', 'Content-Length': '0' * 5000 + '2',
    })
    response = http_server.getresponse()
    assert response.status == 400
    assert json.loads(response.read())['error'] == 'invalid_expense'
