import io
import runpy
from unittest.mock import Mock

import pytest

import app.server as server


@pytest.mark.parametrize('setting,value,message', [
    ('API_KEY', '', 'API_KEY'), ('API_KEY', 'x' * 31, 'API_KEY'),
    ('API_KEY', 'é' * 32, 'API_KEY'),
    ('PORT', 0, 'PORT'), ('PORT', 65536, 'PORT'),
    ('RATE_LIMIT', 0, 'RATE_LIMIT_PER_MINUTE'), ('RATE_LIMIT', -1, 'RATE_LIMIT_PER_MINUTE'),
    *[('SPLIIT_BASE_URL', url, 'SPLIIT_BASE_URL') for url in [
        'ftp://host', 'http://', 'http://user:password@host', 'http://user@host',
        'http://:password@host', 'http://host?x=1', 'http://host#fragment',
        'http://[broken', 'http://host:99999', 'http://host:0', 'http://host:abc',
        'http://bad host', 'http://host\n',
    ]],
])
def test_startup_rejects_invalid_settings(config_file, monkeypatch, setting, value, message):
    monkeypatch.setattr(server, setting, value)
    with pytest.raises(SystemExit, match=message):
        server.main()


@pytest.mark.parametrize('failure', [None, KeyboardInterrupt(), RuntimeError('server failure')])
def test_server_is_always_closed(config_file, monkeypatch, failure):
    httpd = Mock()
    httpd.serve_forever.side_effect = failure
    factory = Mock(return_value=httpd)
    monkeypatch.setattr(server, 'BridgeHTTPServer', factory)
    monkeypatch.setattr(server, 'SPLIIT_BASE_URL', 'https://localhost:3000/spliit')
    if isinstance(failure, RuntimeError):
        with pytest.raises(RuntimeError, match='server failure'):
            server.main()
    else:
        server.main()
    factory.assert_called_once_with((server.HOST, server.PORT), server.BridgeHandler)
    httpd.serve_forever.assert_called_once_with(poll_interval=0.5)
    httpd.server_close.assert_called_once_with()


def test_startup_validates_config_before_binding(config_file, monkeypatch):
    config_file.unlink()
    factory = Mock()
    monkeypatch.setattr(server, 'BridgeHTTPServer', factory)
    with pytest.raises(FileNotFoundError):
        server.main()
    factory.assert_not_called()


def test_script_entrypoint_requires_key(monkeypatch):
    monkeypatch.setenv('API_KEY', '')
    with pytest.raises(SystemExit, match='API_KEY'):
        runpy.run_path(server.__file__, run_name='__main__')


@pytest.mark.parametrize('error', [BrokenPipeError, ConnectionResetError])
def test_disconnected_client_does_not_escape_response_handler(error):
    handler = object.__new__(server.BridgeHandler)
    handler.send_response = Mock()
    handler.send_header = Mock()
    handler.end_headers = Mock()
    handler.wfile = Mock(spec=io.BufferedIOBase)
    handler.wfile.write.side_effect = error
    handler.send_json(200, {'ok': True})
    assert handler.close_connection is True
    handler.wfile.write.assert_called_once_with(b'{"ok":true}')
