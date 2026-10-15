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


def test_read_redis_db_from_the_unit_process_cmdline():
    assert hm_readers.read_instance_pids(ROOT, 27960) == [4242]
    assert hm_readers.read_cmdline_cvar(ROOT, 4242, "net_port") == "27960"
    assert hm_readers.read_redis_db(ROOT, 27960) == 1


def test_read_redis_db_skips_a_wrapper_without_the_cvar(tmp_path):
    slice_dir = tmp_path / "sys/fs/cgroup/system.slice/system-qlds.slice/qlds@27962.service"
    slice_dir.mkdir(parents=True)
    (slice_dir / "cgroup.procs").write_text("10\n11\n12\n")
    (tmp_path / "proc/10").mkdir(parents=True)
    (tmp_path / "proc/10/cmdline").write_bytes(b"/bin/sh\0run.sh\0")
    # pid 11 is gone (no /proc entry)
    (tmp_path / "proc/12").mkdir(parents=True)
    (tmp_path / "proc/12/cmdline").write_bytes(
        b"qzeroded.x64\0+set\0qlx_redisDatabase\0003\0+set\0net_port\00027962\0")
    assert hm_readers.read_redis_db(str(tmp_path), 27962) == 3


def test_read_redis_db_none_when_unknown(tmp_path):
    assert hm_readers.read_instance_pids(str(tmp_path), 27961) == []
    assert hm_readers.read_redis_db(str(tmp_path), 27961) is None
    slice_dir = tmp_path / "sys/fs/cgroup/system.slice/system-qlds.slice/qlds@27961.service"
    slice_dir.mkdir(parents=True)
    (slice_dir / "cgroup.procs").write_text("7\n")
    (tmp_path / "proc/7").mkdir(parents=True)
    (tmp_path / "proc/7/cmdline").write_bytes(b"qzeroded.x64\0+set\0qlx_redisDatabase\0")
    assert hm_readers.read_redis_db(str(tmp_path), 27961) is None


def test_parse_bulk():
    assert hm_readers.parse_bulk(b"$3\r\nabc\r\n") == b"abc"
    assert hm_readers.parse_bulk(b"$-1\r\n") is None
    assert hm_readers.parse_bulk(b"$0\r\n\r\n") == b""


def test_parse_bulk_incomplete_raises():
    with pytest.raises(ValueError):
        hm_readers.parse_bulk(b"$5\r\nab")


@pytest.mark.skipif(not hasattr(socket, "AF_UNIX"), reason="needs unix sockets")
def test_redis_socket_get_against_fake_server():
    stores = {b"1": {b"minqlx:server_status:27960": b'{"state": "in_progress"}'},
              b"2": {b"minqlx:server_status:27961": b'{"state": "warmup"}'}}
    seen = []

    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            db = b"0"
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
                    db = args[1]
                    self.wfile.write(b"+OK\r\n")
                elif args[0] == b"GET":
                    v = stores.get(db, {}).get(args[1])
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
        # per-instance db: SELECT only when the db changes
        n = len(seen)
        assert r.get("minqlx:server_status:27961", db=2) == b'{"state": "warmup"}'
        assert r.get("minqlx:server_status:27960", db=2) is None
        assert seen[n:] == [[b"SELECT", b"2"], [b"GET", b"minqlx:server_status:27961"],
                            [b"GET", b"minqlx:server_status:27960"]]
        assert r.get("minqlx:server_status:27960", db=1) == b'{"state": "in_progress"}'
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


# ---- hardware ----

def test_read_hardware_germany_fixture():
    hw = hm_readers.read_hardware(ROOT)
    assert hw == {
        "cpu_model": "AMD EPYC-Rome Processor", "vcpus": 2, "threads_per_core": 1,
        "sockets": 1, "mhz": 2495.312, "cache": "512 KB", "hypervisor": True,
        "sys_vendor": "Hetzner", "product_name": "vServer", "provider": "Hetzner",
        "mem_total": 3911572 * 1024, "swap_total": 0, "disk_total": 80003072 * 512,
        "disk_rotational": False, "kernel": "6.8.0-137-generic", "os": "Ubuntu 24.04.4 LTS",
        "boot_time": 1787262499,
    }


def test_read_hardware_empty_root_gives_all_none(tmp_path):
    hw = hm_readers.read_hardware(str(tmp_path))
    assert set(hw) == set(hm_readers.HARDWARE_KEYS)
    assert all(v is None for v in hw.values())


def _write(root, rel, text):
    p = Path(root) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def test_read_hardware_nvme_partition_and_amazon_provider(tmp_path):
    _write(tmp_path, "proc/mounts", "/dev/nvme0n1p1 / ext4 rw 0 0\n")
    _write(tmp_path, "sys/block/nvme0n1/queue/rotational", "0\n")
    _write(tmp_path, "sys/block/nvme0n1/size", "16777216\n")
    _write(tmp_path, "sys/class/dmi/id/sys_vendor", "Amazon EC2\n")
    hw = hm_readers.read_hardware(str(tmp_path))
    assert hw["provider"] == "Amazon EC2"
    assert hw["disk_rotational"] is False and hw["disk_total"] == 8 * 1024 ** 3


def test_read_hardware_provider_map_and_raw_vendor(tmp_path):
    for vendor, want in (("Vultr", "Vultr"), ("Hetzner", "Hetzner"), ("QEMU", "QEMU")):
        _write(tmp_path, "sys/class/dmi/id/sys_vendor", vendor + "\n")
        assert hm_readers.read_hardware(str(tmp_path))["provider"] == want


def test_read_hardware_rotational_disk_and_smt_sockets(tmp_path):
    _write(tmp_path, "proc/mounts", "/dev/sda2 / ext4 rw 0 0\n")
    _write(tmp_path, "sys/block/sda/queue/rotational", "1\n")
    block = ("processor\t: %d\nmodel name\t: X CPU\nphysical id\t: %d\nsiblings\t: 4\n"
             "cpu cores\t: 2\nflags\t\t: fpu\n\n")
    _write(tmp_path, "proc/cpuinfo", "".join(block % (i, i // 4) for i in range(8)))
    hw = hm_readers.read_hardware(str(tmp_path))
    assert hw["disk_rotational"] is True and hw["disk_total"] is None
    assert (hw["vcpus"], hw["sockets"], hw["threads_per_core"]) == (8, 2, 2)
    assert hw["hypervisor"] is False and hw["mhz"] is None and hw["cache"] is None


def test_read_hardware_overlay_root_has_no_disk(tmp_path):
    _write(tmp_path, "proc/mounts", "overlay / overlay rw 0 0\n")
    hw = hm_readers.read_hardware(str(tmp_path))
    assert hw["disk_total"] is None and hw["disk_rotational"] is None


# ---- root disk through major:minor ----

# ':' is not allowed in Windows file names: there the fixture tree uses '_' and the reader is
# patched to match (the mountinfo parsing itself is still exercised).
_SEP = "_" if sys.platform == "win32" else ":"


@pytest.fixture(autouse=True)
def _majmin_name(monkeypatch):
    if _SEP != ":":
        real = hm_readers._root_majmin
        monkeypatch.setattr(hm_readers, "_root_majmin",
                            lambda root: (real(root) or "").replace(":", _SEP) or None)

def _dev(root, name, majmin, size=None, rotational=None, partition=False, parent_dir="sys/devices/virt"):
    """sysfs device dir under parent_dir plus the sys/dev/block/<maj:min> symlink to it."""
    rel = "%s/%s" % (parent_dir, name)
    (Path(root) / rel).mkdir(parents=True, exist_ok=True)
    if size is not None:
        _write(root, rel + "/size", "%d\n" % size)
    if rotational is not None:
        _write(root, rel + "/queue/rotational", "%d\n" % rotational)
    if partition:
        _write(root, rel + "/partition", "1\n")
    link = Path(root) / "sys/dev/block" / majmin.replace(":", _SEP)
    link.parent.mkdir(parents=True, exist_ok=True)
    if not link.exists():
        os.symlink(os.path.relpath(Path(root) / rel, link.parent), link, target_is_directory=True)
    return Path(root) / rel


def _mountinfo(root, majmin):
    _write(root, "proc/self/mountinfo",
           "22 1 %s / / rw,relatime shared:1 - ext4 /dev/whatever rw\n"
           "23 22 0:21 / /run rw - tmpfs tmpfs rw\n" % majmin)


def test_root_disk_partition_sda1(tmp_path):
    disk = _dev(tmp_path, "sda", "8:0", size=2048, rotational=1)
    _write(tmp_path, "proc/mounts", "/dev/sda1 / ext4 rw 0 0\n")
    _mountinfo(tmp_path, "8:1")
    _dev(tmp_path, "sda/sda1", "8:1", size=1024, partition=True)
    hw = hm_readers.read_hardware(str(tmp_path))
    assert hw["disk_total"] == 2048 * 512 and hw["disk_rotational"] is True


def test_root_disk_nvme_via_dev_root(tmp_path):
    _dev(tmp_path, "nvme0n1", "259:0", size=62914560, rotational=0)
    _dev(tmp_path, "nvme0n1/nvme0n1p1", "259:1", size=62912512, partition=True)
    _write(tmp_path, "proc/mounts", "/dev/root / ext4 rw 0 0\n")
    _mountinfo(tmp_path, "259:1")
    hw = hm_readers.read_hardware(str(tmp_path))
    assert hw["disk_total"] == 30 * 1024 ** 3 and hw["disk_rotational"] is False


def test_root_disk_lvm_on_raid1_rotational_from_slaves(tmp_path):
    _write(tmp_path, "proc/mounts", "/dev/mapper/vg0-lv--root / ext4 rw 0 0\n")
    _mountinfo(tmp_path, "253:0")
    dm = _dev(tmp_path, "dm-0", "253:0", size=65 * 1024 ** 3 // 512)   # no queue/rotational
    md = _dev(tmp_path, "md0", "9:0", size=1)
    sda = _dev(tmp_path, "sda", "8:0", size=1, rotational=1)
    sdb = _dev(tmp_path, "sdb", "8:16", size=1, rotational=1)
    _dev(tmp_path, "sda/sda2", "8:2", partition=True)
    _dev(tmp_path, "sdb/sdb2", "8:18", partition=True)
    for owner, slaves in ((dm, [md]), (md, [sda / "sda2", sdb / "sdb2"])):
        (owner / "slaves").mkdir()
        for s in slaves:
            os.symlink(os.path.relpath(s, owner / "slaves"), owner / "slaves" / s.name,
                       target_is_directory=True)
    hw = hm_readers.read_hardware(str(tmp_path))
    assert hw["disk_total"] == 65 * 1024 ** 3 and hw["disk_rotational"] is True


def test_root_disk_lvm_on_ssd_slaves_not_rotational(tmp_path):
    _mountinfo(tmp_path, "253:0")
    dm = _dev(tmp_path, "dm-0", "253:0", size=8)
    ssd = _dev(tmp_path, "nvme0n1", "259:0", size=8, rotational=0)
    (dm / "slaves").mkdir()
    os.symlink(os.path.relpath(ssd, dm / "slaves"), dm / "slaves" / "nvme0n1", target_is_directory=True)
    assert hm_readers.read_hardware(str(tmp_path))["disk_rotational"] is False


def test_root_disk_missing_everything_is_none(tmp_path):
    _mountinfo(tmp_path, "253:7")   # no sys tree at all
    hw = hm_readers.read_hardware(str(tmp_path))
    assert hw["disk_total"] is None and hw["disk_rotational"] is None
