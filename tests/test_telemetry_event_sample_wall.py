"""Session and item events carry the plugin's own clock (`sample_wall_ms`, int ms of
time.time() in the hook), as positions do, so the hub can put them on the positions'
time line instead of stamping them when they arrive. The relay passes the field on.
"""
import importlib.util
import json
import logging
import sys
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _minqlx_stub import import_plugin, bare_instance

pytestmark = pytest.mark.standalone

st = import_plugin("stream_telemetry_unified")

NOW = 1792616068.4275
NOW_MS = 1792616068427
RELAY_PATH = Path(__file__).resolve().parent.parent / 'addons' / 'telemetry-relay' / 'assets' / 'relay.py'


@pytest.fixture
def clock(monkeypatch):
    monkeypatch.setattr(st.time, "time", lambda: NOW)


def _session_plugin(**attrs):
    return bare_instance(
        st.stream_telemetry_unified,
        _session_queue=[], _session_queue_warned=False, _session_enabled=lambda: True,
        _is_bot=lambda p: False, _steam_str=lambda p: "76561198000000001",
        _display_name=lambda p: "daz", _game_time_ms=lambda **k: 5000,
        logger=logging.getLogger("test"), **attrs,
    )


def test_session_event_carries_sample_wall_ms(clock):
    p = _session_plugin()
    p.on_death(SimpleNamespace(), None, "ROCKET_SPLASH")
    row = p._session_queue[0]
    assert row["kind"] == "death"
    assert row["sample_wall_ms"] == NOW_MS and type(row["sample_wall_ms"]) is int


def test_lifecycle_event_carries_sample_wall_ms(clock):
    posted = []
    p = _session_plugin(_post_session_events_now=posted.append)
    p._post_session_lifecycle_now("match_start", game_time_ms=0, meta={})
    row = posted[0][0]
    assert row["kind"] == "match_start"
    assert row["sample_wall_ms"] == NOW_MS and type(row["sample_wall_ms"]) is int


def test_item_event_carries_sample_wall_ms(clock):
    p = bare_instance(
        st.stream_telemetry_unified,
        _items_enabled=lambda: True, game=SimpleNamespace(state="in_progress"),
        _steam_str=lambda p: "76561198000000001", _items_queue=[],
        _warn_items_queue_pressure=lambda: None, _flush_items_async=lambda: None,
    )
    p._on_item_event_inner("pickup", 12, SimpleNamespace(name="daz"), "item_armor_body",
                           3, 0, 100, 1.0, 2.0, 3.0, 64000)
    row = p._items_queue[0]
    assert row["sample_wall_ms"] == NOW_MS and type(row["sample_wall_ms"]) is int


@pytest.mark.parametrize('path, key', [
    ('/api/ingest/session-events', 'session_events'),
    ('/api/ingest/item-events', 'item_events'),
])
def test_relay_passes_sample_wall_ms_through(monkeypatch, path, key):
    spec = importlib.util.spec_from_file_location('ql_telemetry_relay_sample_wall', RELAY_PATH)
    relay = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(relay)
    bodies = []

    class Hub(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def do_POST(self):
            bodies.append(json.loads(self.rfile.read(int(self.headers.get('Content-Length') or 0))))
            self.send_response(200)
            self.send_header('Content-Length', '0')
            self.end_headers()

        def log_message(self, *args):
            pass

    servers = [ThreadingHTTPServer(('127.0.0.1', 0), h) for h in (Hub, relay.RelayHandler)]
    for server in servers:
        threading.Thread(target=server.serve_forever, daemon=True).start()
    hub, relay_server = servers
    try:
        monkeypatch.setitem(relay._config, 'enabled', True)
        monkeypatch.setitem(relay._config, 'token', 'tok')
        monkeypatch.setitem(relay._config, 'routes', {
            '7': {'server_id': '7', key: f'http://127.0.0.1:{hub.server_address[1]}/ingest'},
        })
        event = {'kind': 'death', 'game_time_ms': 5000, 'meta': {}, 'sample_wall_ms': NOW_MS}
        req = urllib.request.Request(
            f'http://127.0.0.1:{relay_server.server_address[1]}{path}',
            data=json.dumps({'server_id': 7, 'match_id': 'm', 'events': [event]}).encode('utf-8'),
            headers={'Content-Type': 'application/json'},
            method='POST',
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            assert resp.status == 202
        assert bodies[0]['events'] == [event]
    finally:
        for server in servers:
            server.shutdown()
