from datetime import datetime, timezone
from decimal import Decimal

import pytest

import app.server as server
from tests.test_expenses import valid_expense


@pytest.mark.parametrize('value', ['', 'not-a-number', '1.2.3', 'sNaN', '1e1000000000', '1e-1000000000'])
def test_malformed_or_extreme_amounts(value):
    with pytest.raises(ValueError):
        server.parse_amount(value)


@pytest.mark.parametrize('value,cents', [('0.01', 1), (' 1,20 ', 120), ('1e2', 10000),
                                         ('1.00000000000000000000000000000', 100), (12.5, 1250)])
def test_amount_boundaries(value, cents):
    amount, actual = server.parse_amount(value)
    assert actual == cents
    assert amount == Decimal(cents) / 100


@pytest.mark.parametrize('body', [None, [], True, 'text'])
def test_expense_must_be_object(body):
    with pytest.raises(ValueError, match='object'):
        server.parse_expense(body)


@pytest.mark.parametrize('field', ['groupId', 'title', 'amount', 'expenseDate', 'paidBy',
                                   'paidFor', 'category', 'splitMode'])
def test_each_required_field(config_file, field):
    body = valid_expense()
    del body[field]
    with pytest.raises(ValueError, match='Missing required fields'):
        server.parse_expense(body)


@pytest.mark.parametrize('field,value,message', [
    ('groupId', None, 'Group not allowed'), ('groupId', 'unknown', 'Group not allowed'),
    ('title', None, 'Invalid title'), ('title', 'a\x00b', 'printable'),
    ('title', 'a\nb', 'printable'), ('title', '  ', 'printable'),
    ('splitMode', [], 'splitMode'), ('splitMode', 'invalid', 'splitMode'),
    ('expenseDate', None, 'expenseDate'), ('expenseDate', 'x' * 65, 'expenseDate'),
    ('expenseDate', '1999-12-31', 'accepted range'),
    ('expenseDate', '9999-01-01', 'accepted range'),
    ('expenseDate', '2025-02-29', 'valid ISO date'),
    ('expenseDate', '0001-01-01T00:00:00+23:00', 'valid ISO date'),
    ('expenseDate', '9999-12-31T23:59:59-23:00', 'valid ISO date'),
    ('category', '1', 'category'), ('category', 1.5, 'category'), ('category', 10001, 'category'),
    ('paidBy', None, 'paidBy'), ('paidBy', 'x' * 129, 'paidBy'),
    ('paidFor', {}, 'between'), ('paidFor', [{}] * 101, 'between'),
    ('paidFor', [None], 'entry'), ('paidFor', [{}], 'participant ID'),
    ('paidFor', [{'participant': 'bad/id'}], 'participant ID'),
    ('paidFor', [{'participant': 'p1', 'shares': 'garbage'}], 'shares value'),
    ('paidFor', [{'participant': 'p1', 'shares': None}], 'shares value'),
    ('notes', None, 'Notes'), ('notes', 'x' * 2001, 'Notes'), ('notes', '\x00', 'Notes'),
])
def test_field_validation(config_file, field, value, message):
    body = valid_expense()
    body[field] = value
    with pytest.raises(ValueError, match=message):
        server.parse_expense(body)


@pytest.mark.parametrize('mode', sorted(server.ALLOWED_SPLIT_MODES))
def test_all_modes_are_parsed(config_file, mode):
    body = valid_expense()
    body['splitMode'] = mode
    shares = {'BY_AMOUNT': 625, 'BY_PERCENTAGE': 50}.get(mode, 1)
    body['paidFor'] = [{'participant': 'p1', 'shares': shares}, {'participant': 'p2', 'shares': shares}]
    assert server.parse_expense(body)['splitMode'] == mode


def test_boundary_fields_and_default_notes(config_file):
    body = valid_expense()
    body.update(title='é' * 200, category=10000, expenseDate='2000-01-01',
                paidFor=[{'participant': f'p{i}'} for i in range(100)])
    del body['notes']
    expense = server.parse_expense(body)
    assert len(expense['paidFor']) == 100
    assert expense['paidFor'][0]['shares'] == '1'
    assert expense['notes'] == ''
    assert expense['expenseDate'] == datetime(2000, 1, 1)


def test_timezone_is_converted_to_utc(config_file):
    body = valid_expense()
    body['expenseDate'] = '2026-10-07T01:30:00+02:00'
    assert server.parse_expense(body)['expenseDate'] == datetime(2026, 10, 6, 23, 30)


def test_latest_allowed_year(config_file):
    body = valid_expense()
    year = datetime.now(timezone.utc).year + 2
    body['expenseDate'] = f'{year}-12-31'
    assert server.parse_expense(body)['expenseDate'].year == year
    body['expenseDate'] = f'{year + 1}-01-01'
    with pytest.raises(ValueError, match='accepted range'):
        server.parse_expense(body)


@pytest.mark.parametrize('shares,expected', [(' 1,50 ', '1.50'), ('1000000', '1000000')])
def test_shares_preserve_value(config_file, shares, expected):
    body = valid_expense()
    body['paidFor'] = [{'participant': 'p1', 'shares': shares}]
    assert server.parse_expense(body)['paidFor'] == [{'participant': 'p1', 'shares': expected}]


@pytest.mark.parametrize('details,expected', [
    (None, set()), ([], set()), ({'group': None}, set()), ({'participants': {}}, set()),
    ({'participants': [None, {}, {'id': 1}, {'id': 'bad/id'}, {'id': 'p1'}]}, {'p1'}),
    ({'members': [{'id': 'p1', 'user': {'id': 'user1', 'name': 'User'}}]}, {'p1'}),
    ({'group': {'participants': [{'id': 'p1'}, {'id': 'p1'}]}}, {'p1'}),
    ({'group': {'participants': []}, 'members': [{'id': 'other'}]}, set()),
])
def test_participant_list_shapes(details, expected):
    assert server.participant_ids_from_details(details) == expected


@pytest.mark.parametrize('mode,shares,message', [
    ('BY_AMOUNT', [600, 600], 'sum to the expense amount'),
    ('BY_PERCENTAGE', [40, 40], 'sum to 100'),
    ('BY_AMOUNT', ['625.1', '624.9'], 'whole cents'),
    ('BY_SHARES', ['0.001', '1'], 'two decimal places'),
    ('BY_PERCENTAGE', ['50.001', '49.999'], 'two decimal places'),
    ('EVENLY', ['1e-1000000000', '1'], 'two decimal places'),
    ('BY_SHARES', ['1.000000000000000000000000001', '1'], 'two decimal places'),
])
def test_split_precision_and_totals(config_file, mode, shares, message):
    body = valid_expense()
    body['splitMode'] = mode
    for item, share in zip(body['paidFor'], shares):
        item['shares'] = share
    with pytest.raises(ValueError, match=message):
        server.parse_expense(body)


@pytest.mark.parametrize('mode,shares', [('BY_PERCENTAGE', ['33.33', '66.67']), ('BY_AMOUNT', ['624', '626'])])
def test_valid_split_totals_are_exact(config_file, mode, shares):
    body = valid_expense()
    body['splitMode'] = mode
    for item, share in zip(body['paidFor'], shares):
        item['shares'] = share
    assert [item['shares'] for item in server.parse_expense(body)['paidFor']] == shares
