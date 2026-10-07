
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
