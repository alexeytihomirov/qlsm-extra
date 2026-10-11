"""stream_telemetry_unified session feed: a batch stays queued until the relay
acknowledges it, so a failed POST does not lose referee calls, pauses or match_end."""
import logging
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _minqlx_stub import import_plugin, bare_instance

pytestmark = pytest.mark.standalone

st = import_plugin("stream_telemetry_unified")
from telemetry_unified_sched import FeedState, ack_batch  # noqa: E402

URL = "http://127.0.0.1:8190/api/ingest/session-events"


def test_ack_removes_only_the_acknowledged_rows():
    a, b, c, d = ({"kind": k} for k in "abcd")
    queue = [a, b, c]
    batch = queue[:2]
    queue.append(d)
    assert ack_batch(queue, batch) == 2
    assert queue[0] is c and queue[1] is d and len(queue) == 2


def test_ack_after_the_cap_dropped_the_oldest_row():
    a, b, c, d = ({"kind": k} for k in "abcd")
    queue = [a, b, c]
    batch = queue[:2]
    queue.pop(0)
    queue.append(d)
    assert ack_batch(queue, batch) == 1
    assert queue[0] is c and queue[1] is d and len(queue) == 2


def test_equal_but_distinct_rows_are_kept():
    first, second = {"kind": "say", "text": "gg"}, {"kind": "say", "text": "gg"}
    queue = [first, second]
    assert ack_batch(queue, [first]) == 1
    assert queue[0] is second and len(queue) == 1


class _Conn:
    status = 200
    fail = False

    def __init__(self, host, port, timeout=None):
        pass

    def request(self, *a, **k):
        if self.fail:
            raise OSError("connection refused")

    def getresponse(self):
        return SimpleNamespace(status=self.status, read=lambda: b"{}")

    def close(self):
        pass


def _sender():
    return bare_instance(
        st.stream_telemetry_unified,
        _session_state=FeedState("session", 12.0, 10), _session_acks=[],
        _record_post_result=lambda state, ok: None, logger=logging.getLogger("test"),
    )


def test_accepted_post_queues_an_ack(monkeypatch):
    monkeypatch.setattr("http.client.HTTPConnection", _Conn)
    p = _sender()
    batch = [{"kind": "say"}]
    gen = p._session_state.begin_post(0.0)
    p._post_session_batch(URL, "", {"events": batch}, gen, batch)
    assert p._session_acks == [batch] and p._session_state.posts_ok == 1


def test_failed_post_keeps_the_batch_queued(monkeypatch):
    monkeypatch.setattr("http.client.HTTPConnection", type("Down", (_Conn,), {"fail": True}))
    p = _sender()
    batch = [{"kind": "match_end"}]
    gen = p._session_state.begin_post(0.0)
    p._post_session_batch(URL, "", {"events": batch}, gen, batch)
    assert p._session_acks == [] and p._session_state.posts_fail == 1


def test_rejected_post_keeps_the_batch_queued(monkeypatch):
    monkeypatch.setattr("http.client.HTTPConnection", type("Reject", (_Conn,), {"status": 503}))
    p = _sender()
    batch = [{"kind": "say"}]
    gen = p._session_state.begin_post(0.0)
    p._post_session_batch(URL, "", {"events": batch}, gen, batch)
    assert p._session_acks == []


def test_lifecycle_row_stays_queued_until_acked():
    posted = []
    p = bare_instance(
        st.stream_telemetry_unified,
        _session_queue=[], _session_acks=[], _session_state=FeedState("session", 12.0, 10),
        _session_enabled=lambda: True, get_cvar=lambda name, *a: "",
        _session_events_url=lambda: URL, _build_session_payload=lambda batch: {"events": batch},
        _post_session_batch=lambda url, token, payload, gen, batch: posted.append(batch),
    )
    p._post_session_lifecycle_now("match_end", game_time_ms=600_000, meta={})
    assert len(p._session_queue) == 1 and posted[0][0] is p._session_queue[0]
    p._session_acks.append(posted[0])
    p._apply_session_acks()
    assert p._session_queue == [] and p._session_acks == []
