
import json
import pytest
import app.server as server


def test_valid_config_is_loaded(config_file):
    config = server.load_config()
    assert config["groups"][0] == {"id": "group-1", "name": "Test Group"}


@pytest.mark.parametrize(
    "config",
    [
        {"groups": "not-a-list"},
        {"groups": [{"id": "bad id", "name": "Name"}]},
        {"groups": [{"id": "id", "name": ""}]},
        {"groups": [{"id": "id", "name": "x" * 121}]},
        {"groups": [{"id": "id", "name": "A"}, {"id": "id", "name": "B"}]},
        {"groups": ["not-a-dict"]},
    ],
)
def test_invalid_configs_are_rejected(tmp_path, monkeypatch, config):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setattr(server, "CONFIG_FILE", str(path))
    with pytest.raises(ValueError):
        server.load_config()


def test_missing_config_file_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "CONFIG_FILE", str(tmp_path / "missing.json"))
    with pytest.raises(FileNotFoundError):
        server.load_config()


@pytest.mark.parametrize('config', [
    [], None, True, {}, {'groups': None},
    {'groups': [{'id': 1, 'name': 'Name'}]},
    {'groups': [{'id': 'id', 'name': None}]},
    {'groups': [{'id': 'id', 'name': '   '}]},
    {'groups': [{'id': 'x' * 129, 'name': 'Name'}]}])
def test_config_edge_cases(config_file, config):
    config_file.write_text(json.dumps(config), encoding='utf-8')
    with pytest.raises(ValueError):
        server.load_config()


def test_invalid_config_json(config_file):
    config_file.write_text('{bad json', encoding='utf-8')
    with pytest.raises(json.JSONDecodeError):
        server.load_config()
    with pytest.raises(server.ConfigError, match='Configuration unavailable'):
        server.get_config()


def test_empty_allowlist_is_valid(config_file):
    config_file.write_text('{"groups": []}', encoding='utf-8')
    assert server.get_config() == {'groups': []}
    assert server.allowed_group('unknown') is None


@pytest.mark.parametrize('group_id', [None, 1, [], {}])
def test_non_string_group_ids_are_not_allowed(group_id):
    assert server.allowed_group(group_id) is None


def test_config_changes_apply_without_restart(config_file):
    assert server.allowed_group('group-1') is not None
    config_file.write_text('{"groups": [{"id": "new", "name": "New"}]}', encoding='utf-8')
    assert server.allowed_group('group-1') is None
    assert server.allowed_group('new') == {'id': 'new', 'name': 'New'}
