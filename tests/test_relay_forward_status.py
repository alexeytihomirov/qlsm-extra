"""The telemetry relay passes the hub's permanent rejects (4xx other than 408
and 429) through to the plugin with the same status, so the plugin's
post_outcome drops the batch instead of resending it forever. Transport
errors, 5xx, 408 and 429 stay 502 (the plugin retries those).
"""
import importlib.util
import json
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

RELAY_PATH = Path(__file__).resolve().parent.parent / 'addons' / 'telemetry-relay' / 'assets' / 'relay.py'


@pytest.fixture(scope='module')
def relay():
    spec = importlib.util.spec_from_file_location('ql_telemetry_relay_under_test', RELAY_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('hub_status, expected', [
    (400, 400),
    (408, 502),
    (422, 422),
    (429, 502),
    (500, 502),
    (503, 502),
])
def test_upstream_reply_status(relay, hub_status, expected):
    assert relay.upstream_reply_status(hub_status) == expected


def _serve(handler_cls):
    server = ThreadingHTTPServer(('127.0.0.1', 0), handler_cls)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


@pytest.mark.parametrize('path', ['/api/ingest/session-events', '/api/ingest/item-events'])
@pytest.mark.parametrize('hub_status, expected', [(422, 422), (503, 502)])
def test_relay_answers_with_the_hub_reject(relay, monkeypatch, path, hub_status, expected):
    class Hub(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers.get('Content-Length') or 0))
            self.send_response(hub_status)
            self.send_header('Content-Length', '0')
            self.end_headers()

        def log_message(self, *args):
            pass

    hub = _serve(Hub)
    relay_server = _serve(relay.RelayHandler)
    try:
        upstream = f'http://127.0.0.1:{hub.server_address[1]}/ingest'
        monkeypatch.setitem(relay._config, 'enabled', True)
        monkeypatch.setitem(relay._config, 'token', 'tok')
        monkeypatch.setitem(relay._config, 'routes', {
            '7': {'server_id': '7', 'session_events': upstream, 'item_events': upstream},
        })
        req = urllib.request.Request(
            f'http://127.0.0.1:{relay_server.server_address[1]}{path}',
            data=json.dumps({'server_id': 7, 'events': [{}]}).encode('utf-8'),
            headers={'Content-Type': 'application/json'},
            method='POST',
        )
        with pytest.raises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(req, timeout=5)
        assert err.value.code == expected
        body = json.loads(err.value.read().decode('utf-8'))
        if expected == 502:
            assert body['error'] == f'upstream HTTP {hub_status}'
        else:
            assert body['error'] == 'upstream rejected' and body['status'] == hub_status
    finally:
        relay_server.shutdown()
        hub.shutdown()
