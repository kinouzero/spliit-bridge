"""Verify the tRPC wire contract and bounded, sanitized failure handling."""
import io
import json
from http.client import IncompleteRead
from unittest.mock import Mock
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit

import pytest

import app.server as server
from tests.conftest import request_json
from tests.test_expenses import valid_expense


@pytest.mark.parametrize('input_value', [None, {'groupId': 'été /&?'}])
def test_query_encoding(monkeypatch, input_value):
    opener = Mock(return_value=io.BytesIO(b'{"result":{"data":{"json":{"ok":true}}}}'))
    monkeypatch.setattr(server, 'urlopen', opener)
    assert server.spliit_query('groups.getDetails', input_value) == {'ok': True}
    request = opener.call_args.args[0]
    assert opener.call_args.kwargs == {'timeout': 10}
    assert request.get_method() == 'GET'
    assert request.data is None
    assert request.get_header('Accept') == 'application/json'
    url = urlsplit(request.full_url)
    assert url.path == '/api/trpc/groups.getDetails'
    if input_value is None:
        assert url.query == ''
    else:
        assert json.loads(parse_qs(url.query)['input'][0]) == {'json': input_value}


@pytest.mark.parametrize('date_paths', [None, ['expenseFormValues.expenseDate']])
def test_mutation_encoding(monkeypatch, date_paths):
    opener = Mock(return_value=io.BytesIO(b'{"result":{"data":{"json":{"id":"created"}}}}'))
    monkeypatch.setattr(server, 'urlopen', opener)
    payload = {'expenseFormValues': {'title': 'Déjeuner', 'expenseDate': '2026-10-07T12:00:00'}}
    assert server.spliit_mutation('groups.expenses.create', payload, date_paths) == {'id': 'created'}
    request = opener.call_args.args[0]
    assert opener.call_args.kwargs == {'timeout': 15}
    assert request.get_method() == 'POST'
    assert request.get_header('Content-type') == 'application/json'
    expected = {'json': payload}
    if date_paths:
        expected['meta'] = {'values': {date_paths[0]: ['Date']}}
    assert json.loads(request.data) == expected


@pytest.mark.parametrize('raw,error', [
    (b'x' * (1024 * 1024 + 1), 'upstream_response_too_large'),
    (b'{"error":{"message":"private data"}}', 'upstream_rejected_request'),
    (b'invalid', 'upstream_unavailable'), (b'\xff', 'upstream_unavailable'),
])
def test_bad_upstream_responses_are_sanitized(monkeypatch, raw, error):
    response = io.BytesIO(raw)
    monkeypatch.setattr(server, 'urlopen', Mock(return_value=response))
    with pytest.raises(RuntimeError, match=f'^{error}$'):
        server.spliit_query('categories.list')
    assert response.closed


@pytest.mark.parametrize('failure', [
    URLError('private address'), TimeoutError('private address'), ConnectionResetError(),
    IncompleteRead(b'partial secret'), RecursionError(),
])
def test_network_and_parser_errors_are_sanitized(monkeypatch, failure):
    opener = Mock(side_effect=failure)
    monkeypatch.setattr(server, 'urlopen', opener)
    with pytest.raises(RuntimeError, match='^upstream_unavailable$'):
        server.spliit_mutation('groups.expenses.create', {})
    assert opener.call_count == 1  # Never retry a potentially completed expense creation.


@pytest.mark.parametrize('close_error', [None, OSError('close failed')])
def test_http_error_response_is_closed_and_sanitized(monkeypatch, close_error):
    error = HTTPError('http://private', 503, 'private error', {}, io.BytesIO(b'private response'))
    close = Mock(side_effect=close_error, wraps=error.close)
    error.close = close
    monkeypatch.setattr(server, 'urlopen', Mock(side_effect=error))
    with pytest.raises(RuntimeError, match='^upstream_http_503$'):
        server.spliit_query('categories.list')
    close.assert_called_once_with()


@pytest.mark.parametrize('payload', [None, [], 'text', {'result': None}, {'result': {'data': {}}}])
def test_unknown_trpc_shapes_are_preserved(payload):
    assert server.unwrap_trpc(payload) == payload


def test_exact_response_size_limit_is_accepted(monkeypatch):
    raw = b'"' + b'x' * (1024 * 1024 - 2) + b'"'
    monkeypatch.setattr(server, 'urlopen', Mock(return_value=io.BytesIO(raw)))
    assert len(server.spliit_query('test')) == 1024 * 1024 - 2


@pytest.mark.parametrize('mutation', [False, True])
def test_non_finite_input_is_never_sent(monkeypatch, mutation):
    opener = Mock()
    monkeypatch.setattr(server, 'urlopen', opener)
    with pytest.raises(ValueError):
        server.upstream_call('test', {'value': float('nan')}, mutation=mutation)
    opener.assert_not_called()


def test_create_sends_complete_expense_and_date_metadata(http_server, auth_headers, upstream, monkeypatch):
    monkeypatch.setattr(server, 'ALLOW_CREATE', True)
    status, data = request_json(http_server, 'POST', '/bridge/api/expenses', valid_expense(), auth_headers)
    assert (status, data) == (201, {'created': True, 'result': {'id': 'created'}})
    mutations = [(path, json.loads(body)) for method, path, body in upstream.requests if method == 'POST']
    assert len(mutations) == 1
    path, envelope = mutations[0]
    assert path == '/api/trpc/groups.expenses.create'
    assert envelope['meta'] == {'values': {'expenseFormValues.expenseDate': ['Date']}}
    payload = envelope['json']
    assert payload['groupId'] == 'group-1'
    assert payload['participantId'] == 'p1'
    assert len(payload['expenseId']) == 21
    assert server.ID_RE.fullmatch(payload['expenseId'])
    assert payload['expenseFormValues'] == {
        'title': 'Lunch', 'amount': 1250, 'expenseDate': '2026-10-07T12:00:00Z',
        'category': 1, 'paidBy': 'p1',
        'paidFor': [{'participant': 'p1', 'shares': '1'}, {'participant': 'p2', 'shares': '1'}],
        'splitMode': 'EVENLY', 'saveDefaultSplittingOptions': False,
        'isReimbursement': False, 'documents': [], 'notes': 'Test expense', 'recurrenceRule': 'NONE',
    }


def test_preview_remains_read_only_when_creation_enabled(http_server, auth_headers, upstream, monkeypatch):
    monkeypatch.setattr(server, 'ALLOW_CREATE', True)
    status, data = request_json(http_server, 'POST', '/api/expenses/preview?trace=1', valid_expense(), auth_headers)
    assert status == 200
    assert data['creation_enabled'] is True
    assert [method for method, _, _ in upstream.requests] == ['GET']


def test_preview_serializes_explicit_utc(http_server, auth_headers, upstream):
    body = valid_expense()
    body['expenseDate'] = '2026-10-07T01:30:00+02:00'
    status, data = request_json(http_server, 'POST', '/api/expenses/preview', body, auth_headers)
    assert status == 200
    assert data['would_create']['expenseDate'] == '2026-10-06T23:30:00Z'


def test_failed_creation_is_not_retried(http_server, auth_headers, upstream, monkeypatch):
    monkeypatch.setattr(server, 'ALLOW_CREATE', True)
    mutation = Mock(side_effect=RuntimeError('upstream_unavailable'))
    monkeypatch.setattr(server, 'spliit_mutation', mutation)
    assert request_json(http_server, 'POST', '/api/expenses', valid_expense(), auth_headers) == (
        502, {'error': 'upstream_or_config_error'})
    assert mutation.call_count == 1
