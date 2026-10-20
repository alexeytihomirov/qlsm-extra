"""The telemetry relay must not fall behind a slow link (a host far from the hub sent its
positions hours late): a telemetry sample is the server's state, so a newer sample of the
same server replaces one still queued, and the forwarder keeps one connection open
instead of opening one per sample.
"""
import importlib.util
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

pytestmark = pytest.mark.standalone

RELAY_PATH = Path(__file__).resolve().parent.parent / 'addons' / 'telemetry-relay' / 'assets' / 'relay.py'


@pytest.fixture
def relay():
    spec = importlib.util.spec_from_file_location('ql_telemetry_relay_backlog', RELAY_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Hub:
    """A hub that records bodies and client ports; `gate` holds every answer until set."""

    def __init__(self, drop_after_answer=False):
        self.bodies = []
        self.ports = set()
        self.gate = threading.Event()
        self.gate.set()
        hub = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'

            def do_POST(self):
                body = self.rfile.read(int(self.headers.get('Content-Length') or 0))
                hub.gate.wait(5)
                hub.bodies.append(json.loads(body))
                hub.ports.add(self.client_address[1])
                self.send_response(200)
                self.send_header('Content-Length', '0')
                self.end_headers()
                # an idle timeout: the hub closes a kept-open connection without saying so
                self.close_connection = drop_after_answer

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f'http://127.0.0.1:{self.server.server_address[1]}/api/ingest/telemetry'

    def wait_for(self, count):
        deadline = time.time() + 5
        while len(self.bodies) < count and time.time() < deadline:
            time.sleep(0.01)


def _enqueue(relay, forwarder, hub, server_id, n):
    forwarder.enqueue(url=hub.url, token='tok', body=json.dumps({'server_id': server_id, 'n': n}).encode(),
                      timeout=2.0, counter_key='telemetry_forwarded', key=str(server_id))


def test_newer_sample_replaces_the_queued_one_of_the_same_server(relay):
    hub = _Hub()
    hub.gate.clear()  # the first sample is in flight, the rest wait in the queue
    fw = relay._StreamForwarder('telemetry')
    _enqueue(relay, fw, hub, 9, 1)
    time.sleep(0.1)
    for n in (2, 3, 4):
        _enqueue(relay, fw, hub, 9, n)
    _enqueue(relay, fw, hub, 8, 1)
    _enqueue(relay, fw, hub, 9, 5)
    hub.gate.set()
    hub.wait_for(3)
    time.sleep(0.1)
    assert [(b['server_id'], b['n']) for b in hub.bodies] == [(9, 1), (9, 5), (8, 1)]
    assert relay._stats['telemetry_coalesced'] == 3
    assert relay._stats['telemetry_forwarded'] == 3


def test_samples_share_one_connection(relay):
    hub = _Hub()
    fw = relay._StreamForwarder('telemetry')
    for n in range(5):
        _enqueue(relay, fw, hub, 9, n)
        hub.wait_for(n + 1)
    assert len(hub.bodies) == 5
    assert len(hub.ports) == 1


def test_a_connection_the_hub_closed_is_opened_again(relay):
    hub = _Hub(drop_after_answer=True)
    fw = relay._StreamForwarder('session-events')
    fw.forward_now(url=hub.url, token='tok', body=b'{"n": 1}', timeout=2.0, counter_key='session_events_forwarded')
    time.sleep(0.1)
    fw.forward_now(url=hub.url, token='tok', body=b'{"n": 2}', timeout=2.0, counter_key='session_events_forwarded')
    assert [b['n'] for b in hub.bodies] == [1, 2]


def test_health_reports_the_telemetry_queue(relay):
    hub = _Hub()
    hub.gate.clear()
    fw = relay._telemetry_forwarder_get()
    _enqueue(relay, fw, hub, 9, 1)
    time.sleep(0.1)
    _enqueue(relay, fw, hub, 8, 1)
    _enqueue(relay, fw, hub, 7, 1)
    stats = relay._health_payload()['stats']
    assert stats['telemetry_queue_depth'] == 2
    assert stats['telemetry_queue_oldest_sec'] >= 0
    hub.gate.set()
    hub.wait_for(3)
