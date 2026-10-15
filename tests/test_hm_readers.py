"""Host readers: /proc, cgroup v2 and the minimal Redis client."""
import os
import socket
import socketserver
import sys
import tempfile
import threading
from pathlib import Path

import pytest

pytestmark = pytest.mark.standalone

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "addons" / "host-metrics" / "assets"))

import hm_readers  # noqa: E402

ROOT = str(REPO / "tests" / "fixtures" / "host-metrics" / "germany")


def test_read_cpu_times_two_cores_plus_aggregate():
    cpus = hm_readers.read_cpu_times(ROOT)
    assert sorted(cpus) == [-1, 0, 1]
    agg = cpus[-1]
    assert agg == hm_readers.CpuTimes(48075231, 59663, 19512832, 883474885, 688454, 0, 3228592, 0)
    assert cpus[1].idle == 448094586
    assert cpus[0].softirq == 1523411


def _bump(t, **kw):
    d = t._asdict()
    for k, v in kw.items():
        d[k] += v
    return hm_readers.CpuTimes(**d)


def test_cpu_percent_sums_to_100():
    prev = hm_readers.read_cpu_times(ROOT)[0]
    cur = _bump(prev, user=300, system=100, iowait=50, steal=50, idle=500)
    pct = hm_readers.cpu_percent(prev, cur)
    assert pct["idle"] == pytest.approx(50.0, abs=0.1)
    assert pct["busy"] == pytest.approx(45.0, abs=0.1)
    assert pct["user"] == pytest.approx(30.0, abs=0.1)
    assert pct["system"] == pytest.approx(10.0, abs=0.1)
    assert pct["iowait"] == pytest.approx(5.0, abs=0.1)
    assert pct["steal"] == pytest.approx(5.0, abs=0.1)
    assert pct["idle"] + pct["iowait"] + pct["busy"] == pytest.approx(100.0, abs=0.1)


def test_cpu_percent_reset_returns_none():
    prev = hm_readers.read_cpu_times(ROOT)[0]
    cur = _bump(prev, user=-1, idle=1000)
    assert hm_readers.cpu_percent(prev, cur) is None


def test_cpu_percent_no_elapsed_ticks_returns_none():
    prev = hm_readers.read_cpu_times(ROOT)[0]
    assert hm_readers.cpu_percent(prev, prev) is None


def test_read_mem():
    mem = hm_readers.read_mem(ROOT)
    assert mem["total"] == 3911572 * 1024
    assert mem["available"] == 3285692 * 1024
    assert mem["swap_used"] == 0


def test_read_load_and_psi():
    assert hm_readers.read_load(ROOT) == pytest.approx(0.08)
    assert hm_readers.read_psi_cpu_some10(ROOT) == pytest.approx(0.77)


def test_missing_files_are_handled(tmp_path):
    assert hm_readers.read_psi_cpu_some10(str(tmp_path)) is None
    assert hm_readers.default_iface(str(tmp_path)) is None
    assert hm_readers.list_instances(str(tmp_path)) == []


def test_default_iface_and_net():
    assert hm_readers.default_iface(ROOT) == "eth0"
    net = hm_readers.read_net(ROOT, "eth0")
    assert net == {
        "rx_bytes": 29897441311,
        "tx_bytes": 28879310461,
        "rx_packets": 243348380,
        "tx_packets": 174163540,
    }


def test_read_oom_kills():
    assert hm_readers.read_oom_kills(ROOT) == 0


@pytest.mark.skipif(not hasattr(os, "statvfs"), reason="needs statvfs")
def test_read_disk():
    d = hm_readers.read_disk(os.getcwd())
    assert d["total"] > 0
    assert 0 <= d["used"] <= d["total"]


def test_list_instances_and_read_instance():
    assert hm_readers.list_instances(ROOT) == [27960]
    inst = hm_readers.read_instance(ROOT, 27960)
    assert inst == {"usage_usec": 1425058855, "mem_bytes": 90624000, "oom_kills": 0}


def test_read_instance_gone_returns_none(tmp_path):
    assert hm_readers.read_instance(str(tmp_path), 27961) is None


def test_parse_bulk():
    assert hm_readers.parse_bulk(b"$3\r\nabc\r\n") == b"abc"
    assert hm_readers.parse_bulk(b"$-1\r\n") is None
    assert hm_readers.parse_bulk(b"$0\r\n\r\n") == b""


def test_parse_bulk_incomplete_raises():
    with pytest.raises(ValueError):
        hm_readers.parse_bulk(b"$5\r\nab")


@pytest.mark.skipif(not hasattr(socket, "AF_UNIX"), reason="needs unix sockets")
def test_redis_socket_get_against_fake_server():
    store = {b"minqlx:server_status:27960": b'{"state": "in_progress"}'}
    seen = []

    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            while True:
                line = self.rfile.readline()
                if not line:
                    return
                n = int(line[1:])
                args = []
                for _ in range(n):
                    ln = int(self.rfile.readline()[1:])
                    args.append(self.rfile.read(ln + 2)[:-2])
                seen.append(args)
                if args[0] == b"SELECT":
                    self.wfile.write(b"+OK\r\n")
                elif args[0] == b"GET":
                    v = store.get(args[1])
                    if v is None:
                        self.wfile.write(b"$-1\r\n")
                    else:
                        self.wfile.write(b"$%d\r\n%s\r\n" % (len(v), v))

    d = tempfile.mkdtemp()
    path = os.path.join(d, "r.sock")
    srv = socketserver.ThreadingUnixStreamServer(path, Handler)
    srv.daemon_threads = True
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        r = hm_readers.RedisSocket(path, 1)
        assert r.get("minqlx:server_status:27960") == b'{"state": "in_progress"}'
        assert r.get("minqlx:missing") is None
        assert seen[0] == [b"SELECT", b"1"]
        r.close()
        # reconnects after the connection was dropped
        assert r.get("minqlx:server_status:27960") == b'{"state": "in_progress"}'
    finally:
        srv.shutdown()
        srv.server_close()


@pytest.mark.skipif(not hasattr(socket, "AF_UNIX"), reason="needs unix sockets")
def test_redis_socket_unreachable_raises_oserror(tmp_path):
    r = hm_readers.RedisSocket(str(tmp_path / "none.sock"), 1)
    with pytest.raises(OSError):
        r.get("k")
