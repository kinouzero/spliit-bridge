
import json
import threading
from http.client import HTTPConnection

import pytest

import app.server as server


@pytest.fixture
def config_file(tmp_path, monkeypatch):
    config = {
        "groups": [
            {"id": "group-1", "name": "Test Group"},
            {"id": "group_2", "name": "Second Group"},
        ]
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setattr(server, "CONFIG_FILE", str(path))
    monkeypatch.setattr(server, "API_KEY", "test-" + ("x" * 40))
    monkeypatch.setattr(server, "ALLOW_CREATE", False)
    monkeypatch.setattr(server, "RATE_LIMIT", 120)
    with server._rate_lock:
        server._requests.clear()
    return path


class FakeUpstream:
    def __init__(self, handler):
        self.handler = handler
        self.requests = []
        self.httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)

    @property
    def base_url(self):
        return f"http://127.0.0.1:{self.httpd.server_port}"

    def start(self):
        self.thread.start()

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)


class UpstreamHandler(server.BaseHTTPRequestHandler):
    server_version = "FakeSpliit"
    sys_version = ""

    def log_message(self, *_args):
        pass

    def do_GET(self):
        self.server.requests.append((self.command, self.path, b""))
        if self.path.startswith("/api/trpc/categories.list"):
            body = b'{"result":{"data":{"json":[{"id":1,"name":"Food"}]}}}'
            self.send_response(200)
        elif self.path.startswith("/api/trpc/groups.getDetails"):
            body = (
                b'{"result":{"data":{"json":'
                b'{"group":{"id":"group-1","name":"Group","participants":['
                b'{"id":"p1","name":"Alice","email":"a@example.com"},'
                b'{"id":"p2","name":"Bob","email":"b@example.com"}]},"participantsWithExpenses":[]}}}}'
            )
            self.send_response(200)
        else:
            body = b'{"error":"not_found"}'
            self.send_response(404)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        data = self.rfile.read(length)
        self.server.requests.append((self.command, self.path, data))
        body = b'{"result":{"data":{"json":{"id":"created"}}}}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def upstream(monkeypatch):
    fake = FakeUpstream(UpstreamHandler)
    fake.httpd.requests = fake.requests
    fake.start()
    monkeypatch.setattr(server, "SPLIIT_BASE_URL", fake.base_url)
    yield fake
    fake.stop()


@pytest.fixture
def http_server(config_file):
    httpd = server.BridgeHTTPServer(("127.0.0.1", 0), server.BridgeHandler)
    thread = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()

    host, port = httpd.server_address
    connection = HTTPConnection(host, port, timeout=3)
    yield connection

    connection.close()
    httpd.shutdown()
    httpd.server_close()
    thread.join(timeout=2)


@pytest.fixture
def auth_headers():
    return {"X-API-Key": "test-" + ("x" * 40)}


def request_json(connection, method, path, body=None, headers=None):
    headers = dict(headers or {})
    if body is not None:
        payload = json.dumps(body).encode()
        headers.setdefault("Content-Type", "application/json")
        headers.setdefault("Content-Length", str(len(payload)))
    else:
        payload = None
    connection.request(method, path, body=payload, headers=headers)
    response = connection.getresponse()
    raw = response.read()
    data = json.loads(raw) if raw else None
    return response.status, data
