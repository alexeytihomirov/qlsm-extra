"""Readers for host metrics: /proc, cgroup v2 and a minimal Redis client.

Pure functions, stdlib only (Python 3.10+). Every reader takes `root` so tests
can point it at a fixture tree that mirrors `/`.
"""
import os
import re
import socket
import subprocess
from collections import namedtuple

CGROUP_QLDS = "sys/fs/cgroup/system.slice/system-qlds.slice"
_INSTANCE_RE = re.compile(r"^qlds@(\d+)\.service$")

CpuTimes = namedtuple("CpuTimes", "user nice system idle iowait irq softirq steal")


def _path(root, rel):
    return os.path.join(root, rel)


def _read(root, rel):
    with open(_path(root, rel), "r", encoding="utf-8", errors="replace") as f:
        return f.read()


# ---- CPU ----

def read_cpu_times(root="/"):
    """Return {cpu_index: CpuTimes}; key -1 is the aggregate `cpu` line."""
    out = {}
    for line in _read(root, "proc/stat").splitlines():
        parts = line.split()
        if not parts or not parts[0].startswith("cpu"):
            continue
        name = parts[0]
        idx = -1 if name == "cpu" else int(name[3:])
        vals = [int(v) for v in parts[1:9]]
        vals += [0] * (8 - len(vals))
        out[idx] = CpuTimes(*vals)
    return out


def cpu_percent(prev, cur):
    """Percent of elapsed ticks between two snapshots, or None on reset.

    user = user+nice, system = system+irq+softirq, busy = user+system+steal,
    so idle + iowait + busy = 100.
    """
    deltas = [c - p for p, c in zip(prev, cur)]
    if any(d < 0 for d in deltas):
        return None
    d = CpuTimes(*deltas)
    total = sum(d)
    if total <= 0:
        return None

    def pct(v):
        return v * 100.0 / total

    user = pct(d.user + d.nice)
    system = pct(d.system + d.irq + d.softirq)
    steal = pct(d.steal)
    return {
        "user": user,
        "system": system,
        "iowait": pct(d.iowait),
        "steal": steal,
        "idle": pct(d.idle),
        "busy": user + system + steal,
    }


# ---- memory, load, pressure ----

def read_mem(root="/"):
    """Bytes: total, available, swap_used."""
    kb = {}
    for line in _read(root, "proc/meminfo").splitlines():
        key, _, rest = line.partition(":")
        fields = rest.split()
        if fields:
            kb[key] = int(fields[0])
    return {
        "total": kb.get("MemTotal", 0) * 1024,
        "available": kb.get("MemAvailable", 0) * 1024,
        "swap_used": max(kb.get("SwapTotal", 0) - kb.get("SwapFree", 0), 0) * 1024,
    }


def read_load(root="/"):
    return float(_read(root, "proc/loadavg").split()[0])


def read_psi_cpu_some10(root="/"):
    """avg10 of the `some` line in /proc/pressure/cpu, None if PSI is absent."""
    try:
        text = _read(root, "proc/pressure/cpu")
    except OSError:
        return None
    for line in text.splitlines():
        parts = line.split()
        if parts and parts[0] == "some":
            for p in parts[1:]:
                if p.startswith("avg10="):
                    return float(p[6:])
    return None


# ---- network ----

def default_iface(root="/"):
    """Interface of the default route (destination 00000000), else None."""
    try:
        lines = _read(root, "proc/net/route").splitlines()
    except OSError:
        return None
    for line in lines[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "00000000":
            return parts[0]
    return None


def read_net(root, iface):
    """Counters of one interface from /proc/net/dev."""
    for line in _read(root, "proc/net/dev").splitlines():
        name, sep, rest = line.partition(":")
        if sep and name.strip() == iface:
            f = rest.split()
            return {
                "rx_bytes": int(f[0]),
                "rx_packets": int(f[1]),
                "tx_bytes": int(f[8]),
                "tx_packets": int(f[9]),
            }
    raise KeyError(iface)


def read_oom_kills(root="/"):
    for line in _read(root, "proc/vmstat").splitlines():
        if line.startswith("oom_kill "):
            return int(line.split()[1])
    return 0


def read_disk(path="/"):
    """Bytes used and total of the filesystem holding `path` (not root-relative)."""
    st = os.statvfs(path)
    total = st.f_blocks * st.f_frsize
    used = (st.f_blocks - st.f_bfree) * st.f_frsize
    return {"used": used, "total": total}


# ---- hardware ----

HARDWARE_KEYS = ("cpu_model", "vcpus", "threads_per_core", "sockets", "mhz", "cache",
                 "hypervisor", "sys_vendor", "product_name", "provider", "mem_total",
                 "swap_total", "disk_total", "disk_rotational", "kernel", "os", "boot_time")
_PROVIDERS = (("hetzner", "Hetzner"), ("amazon ec2", "Amazon EC2"), ("vultr", "Vultr"))
_PART_RE = re.compile(r"^(.*\d)p\d+$")


def _first_line(root, rel):
    try:
        return _read(root, rel).strip() or None
    except OSError:
        return None


def _cpuinfo(root):
    """CPU fields from /proc/cpuinfo: processors are blank-line separated blocks."""
    out = {}
    try:
        text = _read(root, "proc/cpuinfo")
    except OSError:
        return out
    blocks = []
    for chunk in re.split(r"\n\s*\n", text):
        fields = {}
        for line in chunk.splitlines():
            key, sep, val = line.partition(":")
            if sep:
                fields.setdefault(key.strip(), val.strip())
        if "processor" in fields:
            blocks.append(fields)
    if not blocks:
        return out
    first = blocks[0]
    out["vcpus"] = len(blocks)
    out["cpu_model"] = first.get("model name") or None
    out["cache"] = first.get("cache size") or None
    try:
        out["mhz"] = float(first["cpu MHz"])
    except (KeyError, ValueError):
        pass
    phys = {b["physical id"] for b in blocks if "physical id" in b}
    if phys:
        out["sockets"] = len(phys)
    try:
        out["threads_per_core"] = max(int(first["siblings"]) // int(first["cpu cores"]), 1)
    except (KeyError, ValueError, ZeroDivisionError):
        pass
    out["hypervisor"] = "hypervisor" in first.get("flags", "").split()
    return out


def _provider(vendor):
    if not vendor:
        return None
    low = vendor.lower()
    for prefix, name in _PROVIDERS:
        if low.startswith(prefix):
            return name
    return vendor


def _root_block_device(root):
    """Whole-disk name of `/` from /proc/mounts (sda1 -> sda, nvme0n1p1 -> nvme0n1), else None."""
    try:
        lines = _read(root, "proc/mounts").splitlines()
    except OSError:
        return None
    for line in lines:
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "/" and parts[0].startswith("/dev/"):
            name = parts[0][len("/dev/"):]
            if "/" in name:
                return None   # /dev/mapper/..., /dev/disk/by-...
            if os.path.isdir(_path(root, "sys/block/" + name)):
                return name
            m = _PART_RE.match(name)
            return m.group(1) if m else (name.rstrip("0123456789") or None)
    return None


def _root_majmin(root):
    """major:minor of the filesystem mounted on `/` from /proc/self/mountinfo, else None."""
    try:
        lines = _read(root, "proc/self/mountinfo").splitlines()
    except OSError:
        return None
    found = None
    for line in lines:
        parts = line.split()
        if len(parts) >= 5 and parts[4] == "/":
            found = parts[2]   # the last mount on / wins
    return found


def _disk_dir(path):
    """Resolve a sysfs device dir; a partition maps to its parent disk dir."""
    real = os.path.realpath(path)
    if os.path.exists(os.path.join(real, "partition")):
        real = os.path.dirname(real)
    return real


def _dev_rotational(devdir, depth=0):
    """queue/rotational of a device dir, else of its slaves (rotational if any is); None if unknown."""
    try:
        with open(os.path.join(devdir, "queue", "rotational"), "r", encoding="utf-8") as f:
            return int(f.read().strip()) == 1
    except (OSError, ValueError):
        pass
    if depth > 8:
        return None
    try:
        names = sorted(os.listdir(os.path.join(devdir, "slaves")))
    except OSError:
        return None
    vals = [_dev_rotational(_disk_dir(os.path.join(devdir, "slaves", n)), depth + 1) for n in names]
    vals = [v for v in vals if v is not None]
    return any(vals) if vals else None


def _root_disk_by_majmin(root, hw):
    """Fill disk_total/disk_rotational from the device of `/` (works for LVM, RAID, /dev/root)."""
    majmin = _root_majmin(root)
    if not majmin:
        return False
    devdir = _disk_dir(_path(root, "sys/dev/block/" + majmin))
    if not os.path.isdir(devdir):
        return False
    try:
        with open(os.path.join(devdir, "size"), "r", encoding="utf-8") as f:
            hw["disk_total"] = int(f.read().strip()) * 512
    except (OSError, ValueError):
        pass
    hw["disk_rotational"] = _dev_rotational(devdir)
    return True


def read_hardware(root="/"):
    """Static facts about the host; every key of HARDWARE_KEYS is present, None when unknown.

    Never raises: each source is read on its own so one missing file only blanks its fields.
    """
    hw = dict.fromkeys(HARDWARE_KEYS)
    hw.update(_cpuinfo(root))
    hw["sys_vendor"] = _first_line(root, "sys/class/dmi/id/sys_vendor")
    hw["product_name"] = _first_line(root, "sys/class/dmi/id/product_name")
    hw["provider"] = _provider(hw["sys_vendor"])
    try:
        kb = {}
        for line in _read(root, "proc/meminfo").splitlines():
            key, _, rest = line.partition(":")
            fields = rest.split()
            if fields:
                kb[key] = int(fields[0])
        if "MemTotal" in kb:
            hw["mem_total"] = kb["MemTotal"] * 1024
        if "SwapTotal" in kb:
            hw["swap_total"] = kb["SwapTotal"] * 1024
    except (OSError, ValueError):
        pass
    dev = None
    try:
        by_majmin = _root_disk_by_majmin(root, hw)
    except Exception:
        by_majmin = False
    if not by_majmin:
        dev = _root_block_device(root)   # fallback: name from /proc/mounts
    if dev:
        try:
            hw["disk_rotational"] = int(_read(root, "sys/block/%s/queue/rotational" % dev)) == 1
        except (OSError, ValueError):
            pass
        try:
            hw["disk_total"] = int(_read(root, "sys/block/%s/size" % dev)) * 512
        except (OSError, ValueError):
            pass
    hw["kernel"] = _first_line(root, "proc/sys/kernel/osrelease")
    try:
        for line in _read(root, "etc/os-release").splitlines():
            if line.startswith("PRETTY_NAME="):
                hw["os"] = line.partition("=")[2].strip().strip("\"'") or None
    except OSError:
        pass
    try:
        for line in _read(root, "proc/stat").splitlines():
            if line.startswith("btime "):
                hw["boot_time"] = int(line.split()[1])
    except (OSError, ValueError, IndexError):
        pass
    return hw


# ---- per-instance cgroup ----

def list_instances(root="/"):
    """Ports of the qlds@<port>.service cgroups, sorted."""
    try:
        names = os.listdir(_path(root, CGROUP_QLDS))
    except OSError:
        return []
    ports = []
    for n in names:
        m = _INSTANCE_RE.match(n)
        if m:
            ports.append(int(m.group(1)))
    return sorted(ports)


def read_instance(root, port):
    """cgroup counters of one instance, None when its cgroup is gone."""
    base = "%s/qlds@%d.service" % (CGROUP_QLDS, port)
    try:
        usage = None
        for line in _read(root, base + "/cpu.stat").splitlines():
            if line.startswith("usage_usec "):
                usage = int(line.split()[1])
        mem = int(_read(root, base + "/memory.current").strip())
        oom = 0
        for line in _read(root, base + "/memory.events").splitlines():
            if line.startswith("oom_kill "):
                oom = int(line.split()[1])
    except (OSError, ValueError):
        return None
    if usage is None:
        return None
    return {"usage_usec": usage, "mem_bytes": mem, "oom_kills": oom}


def read_instance_pids(root, port):
    """Pids in the instance's unit cgroup (cgroup.procs), [] when it is gone."""
    try:
        text = _read(root, "%s/qlds@%d.service/cgroup.procs" % (CGROUP_QLDS, port))
    except OSError:
        return []
    return [int(t) for t in text.split() if t.isdigit()]


def read_cmdline_cvar(root, pid, name):
    """Value after the token `name` in /proc/<pid>/cmdline (NUL-separated argv), else None."""
    try:
        with open(_path(root, "proc/%d/cmdline" % pid), "rb") as f:
            argv = f.read().split(b"\0")
    except OSError:
        return None
    key = name.encode()
    for i, tok in enumerate(argv[:-1]):
        if tok == key:
            return argv[i + 1].decode("utf-8", errors="replace")
    return None


def read_redis_db(root, port):
    """`qlx_redisDatabase` the instance was started with (qlsm passes `+set qlx_redisDatabase N`
    on the command line, one DB per instance), None when no process of the unit carries it."""
    for pid in read_instance_pids(root, port):
        value = read_cmdline_cvar(root, pid, "qlx_redisDatabase")
        value = (value or "").strip().strip('"')
        if value.isdigit():
            return int(value)
    return None


def read_affinity(port):
    """First CPU if the unit is pinned to exactly one, else None."""
    try:
        res = subprocess.run(
            ["systemctl", "show", "-p", "CPUAffinity", "--value", "qlds@%d.service" % int(port)],
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if res.returncode != 0:
        return None
    cpus = set()
    for tok in res.stdout.split():
        lo, sep, hi = tok.partition("-")
        try:
            if sep:
                cpus.update(range(int(lo), int(hi) + 1))
            else:
                cpus.add(int(lo))
        except ValueError:
            return None
    return next(iter(cpus)) if len(cpus) == 1 else None


# ---- minimal Redis (RESP) ----

def parse_bulk(data):
    """Parse one RESP bulk string; None for the nil reply `$-1`."""
    if not data.startswith(b"$"):
        raise ValueError("not a bulk reply: %r" % data[:20])
    end = data.find(b"\r\n")
    if end < 0:
        raise ValueError("incomplete reply")
    n = int(data[1:end])
    if n < 0:
        return None
    start = end + 2
    if len(data) < start + n + 2:
        raise ValueError("incomplete bulk")
    return data[start:start + n]


def _encode(*args):
    out = [b"*%d\r\n" % len(args)]
    for a in args:
        b = a if isinstance(a, bytes) else str(a).encode()
        out.append(b"$%d\r\n%s\r\n" % (len(b), b))
    return b"".join(out)


class RedisSocket:
    """Tiny Redis client over a unix socket: SELECT db, GET key.

    `get(key, db)` re-selects only when the db differs from the connection's current one."""

    def __init__(self, path, db, timeout=1.0):
        self.path = path
        self.db = db
        self.timeout = timeout
        self._sock = None
        self._buf = b""
        self._cur_db = None

    def close(self):
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
        self._sock = None
        self._buf = b""
        self._cur_db = None

    def _connect(self):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(self.timeout)
        try:
            s.connect(self.path)
        except OSError:
            s.close()
            raise
        self._sock = s
        self._buf = b""
        self._cur_db = None

    def _select(self, db):
        if db == self._cur_db:
            return
        line = self._send_line(_encode("SELECT", db))
        if not line.startswith(b"+OK"):
            raise OSError("redis SELECT failed: %r" % line)
        self._cur_db = db

    def _fill(self):
        chunk = self._sock.recv(65536)
        if not chunk:
            raise OSError("redis connection closed")
        self._buf += chunk

    def _read_line(self):
        while b"\r\n" not in self._buf:
            self._fill()
        line, _, self._buf = self._buf.partition(b"\r\n")
        return line

    def _send_line(self, payload):
        self._sock.sendall(payload)
        return self._read_line()

    def _get_once(self, key, db):
        if self._sock is None:
            self._connect()
        self._select(self.db if db is None else db)
        head = self._send_line(_encode("GET", key))
        if head.startswith(b"-"):
            raise OSError("redis error: %r" % head)
        if not head.startswith(b"$"):
            raise OSError("unexpected redis reply: %r" % head)
        n = int(head[1:])
        if n < 0:
            return None
        while len(self._buf) < n + 2:
            self._fill()
        val = self._buf[:n]
        self._buf = self._buf[n + 2:]
        return val

    def get(self, key, db=None):
        """Value as bytes from `db` (default: the constructor's), None when the key is
        missing. Retries once on a broken connection; raises OSError when Redis stays
        unreachable."""
        try:
            return self._get_once(key, db)
        except (OSError, ValueError):
            self.close()
        try:
            return self._get_once(key, db)
        except (OSError, ValueError) as e:
            self.close()
            raise OSError(str(e))
