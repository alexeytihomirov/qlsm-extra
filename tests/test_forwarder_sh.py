"""Tests for addons/file-forwarder/assets/forwarder.sh.

The script is POSIX sh and runs on the game host; here it runs under whatever
`sh` is on PATH (Git Bash on Windows) against a fake `rclone` that implements
exactly the two calls the script makes:

    rclone copyto <file> <remote>:<dir>/<name>
    rclone lsjson <remote>:<dir>

The "remote" is a temp directory. FAKE_RCLONE_FAIL=1 makes every call fail (=copyto only uploads),
FAKE_RCLONE_DELAY=<seconds> makes copyto slow (for the lock test).
"""
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.standalone

SH = shutil.which('sh')
if SH is None:
    pytest.skip('no sh on PATH', allow_module_level=True)

SCRIPT = Path(__file__).resolve().parent.parent / 'addons' / 'file-forwarder' / 'assets' / 'forwarder.sh'

FAKE_RCLONE = r'''#!/bin/sh
if [ -n "${FAKE_RCLONE_FAIL:-}" ] && { [ "$FAKE_RCLONE_FAIL" != copyto ] || [ "$1" = copyto ]; }; then
    echo "fake rclone: forced failure" >&2
    exit 1
fi
case "$1" in
copyto)
    if [ -n "${FAKE_RCLONE_DELAY:-}" ]; then sleep "$FAKE_RCLONE_DELAY"; fi
    rest="${3#*:}"
    mkdir -p "$FAKE_REMOTE/${rest%/*}"
    cp -- "$2" "$FAKE_REMOTE/$rest"
    ;;
lsjson)
    d="$FAKE_REMOTE/${2#*:}"
    [ -d "$d" ] || { echo "directory not found" >&2; exit 3; }
    first=1
    printf '['
    for f in "$d"/* "$d"/.[!.]*; do
        [ -f "$f" ] || continue
        [ "$first" = 1 ] || printf ','
        first=0
        printf '{"Path":"%s","Name":"%s","Size":%s,"IsDir":false}' "${f##*/}" "${f##*/}" "$(wc -c < "$f" | tr -d ' ')"
    done
    printf ']\n'
    ;;
*)
    echo "fake rclone: unsupported $*" >&2
    exit 64
    ;;
esac
'''

OLD = 3 * 3600          # seconds: older than MIN_AGE_MIN
VERY_OLD = 20 * 86400   # seconds: older than RETENTION_DAYS (14)


class Host:
    def __init__(self, tmp_path):
        self.root = tmp_path
        self.demos = [tmp_path / 'qlds-27960' / 'demos', tmp_path / 'qlds-27961' / 'demos']
        for d in self.demos:
            d.mkdir(parents=True)
        self.remote = tmp_path / 'remote'
        self.remote.mkdir()
        self.state = tmp_path / 'state'
        self.bin = tmp_path / 'bin'
        self.bin.mkdir()
        fake = self.bin / 'rclone'
        fake.write_bytes(FAKE_RCLONE.encode())
        fake.chmod(0o755)
        self.conf = tmp_path / 'forwarder.conf'
        self.max_raw_mb = 2048
        self.write_conf()

    def write_conf(self, **over):
        values = {
            'REMOTE': 'qldemos',
            'SRC_GLOBS': ' '.join(d.as_posix() for d in self.demos),
            'PATTERNS': '*.qlmatch:qlmatch:keep *.replay.json.gz:qlmatch:keep *.dm_91:raw:expire',
            'RETENTION_DAYS': '14',
            'MIN_AGE_MIN': '2',
            'MAX_RAW_MB_PER_RUN': str(self.max_raw_mb),
            'STATE_DIR': self.state.as_posix(),
            'RCLONE': 'rclone',
        }
        values.update(over)
        self.conf.write_text(''.join(f'{k}="{v}"\n' for k, v in values.items()), encoding='utf-8')

    def env(self, **extra):
        env = dict(os.environ)
        env['PATH'] = str(self.bin) + os.pathsep + env['PATH']
        env['FAKE_REMOTE'] = self.remote.as_posix()
        env['FORWARDER_CONF'] = self.conf.as_posix()
        env.update(extra)
        return env

    def put(self, name, content=b'x', age=OLD, dirindex=0):
        path = self.demos[dirindex] / name
        path.write_bytes(content)
        t = time.time() - age
        os.utime(path, (t, t))
        return path

    def run(self, mode='run', **extra_env):
        return subprocess.run([SH, SCRIPT.as_posix(), mode], env=self.env(**extra_env),
                              capture_output=True, text=True, encoding='utf-8')

    def last_run(self):
        text = (self.state / 'last-run').read_text(encoding='utf-8').strip()
        return dict(kv.split('=', 1) for kv in text.split())

    def ledger(self):
        path = self.state / 'delivered.tsv'
        if not path.exists():
            return []
        return [line.split('\t') for line in path.read_text(encoding='utf-8').splitlines() if line]

    def remote_names(self, sub):
        d = self.remote / sub
        return sorted(p.name for p in d.iterdir()) if d.is_dir() else []


@pytest.fixture
def host(tmp_path):
    return Host(tmp_path)


def test_uploads_new_files_and_records_ledger(host):
    host.put('m1.qlmatch', b'pack')
    host.put('m1.dm_91', b'demo!', dirindex=1)
    r = host.run()
    assert r.returncode == 0, r.stdout + r.stderr
    assert host.remote_names('qlmatch') == ['m1.qlmatch']
    assert host.remote_names('raw') == ['m1.dm_91']
    ledger = host.ledger()
    assert sorted(row[0] for row in ledger) == ['m1.dm_91', 'm1.qlmatch']
    sizes = {row[0]: row[1] for row in ledger}
    assert sizes == {'m1.qlmatch': '4', 'm1.dm_91': '5'}
    assert all(len(row) == 4 for row in ledger)
    last = host.last_run()
    assert last['uploaded'] == '2' and last['exit'] == '0' and last['mode'] == 'run'


def test_skips_young_and_partial_files(host):
    host.put('young.qlmatch', age=10)
    host.put('half.qlmatch.partial')
    host.put('half2.dm_91.partial')
    host.put('ok.replay.json.gz')
    r = host.run()
    assert r.returncode == 0, r.stdout + r.stderr
    assert host.remote_names('qlmatch') == ['ok.replay.json.gz']
    assert host.remote_names('raw') == []
    assert host.last_run()['uploaded'] == '1'


def test_second_run_uploads_nothing_and_changed_file_is_resent(host):
    host.put('a.qlmatch', b'one')
    host.put('b.qlmatch', b'two')
    assert host.run().returncode == 0
    r = host.run()
    assert r.returncode == 0
    assert host.last_run()['uploaded'] == '0'
    assert len(host.ledger()) == 2
    # b: other size; a: same size, other mtime
    host.put('b.qlmatch', b'twotwo')
    a = host.demos[0] / 'a.qlmatch'
    t = time.time() - OLD - 500
    os.utime(a, (t, t))
    assert host.run().returncode == 0
    assert host.last_run()['uploaded'] == '2'
    assert len(host.ledger()) == 4
    assert (host.remote / 'qlmatch' / 'b.qlmatch').read_bytes() == b'twotwo'


def seed_ledger(host, files, remote_dir='raw', remote_content=None):
    """Ledger the given files as delivered (current size and mtime) and put a
    matching copy on the fake remote, as if an earlier run had sent them."""
    host.state.mkdir(exist_ok=True)
    (host.remote / remote_dir).mkdir(parents=True, exist_ok=True)
    with open(host.state / 'delivered.tsv', 'a', encoding='utf-8', newline='\n') as f:
        for p in files:
            st = p.stat()
            f.write(f'{p.name}\t{st.st_size}\t{int(st.st_mtime)}\t2026-01-01T00:00:00Z\n')
            (host.remote / remote_dir / p.name).write_bytes(p.read_bytes())


def test_cleanup_deletes_only_expired_ledgered_expire_rows(host):
    expired = host.put('expired.dm_91', b'aaa', age=VERY_OLD)
    young = host.put('young.dm_91', b'ddd', age=OLD)
    changed = host.put('changed.dm_91', b'ccc', age=VERY_OLD)
    old_keep = host.put('old.qlmatch', b'eee', age=VERY_OLD)
    seed_ledger(host, [expired, young, changed])
    seed_ledger(host, [old_keep], remote_dir='qlmatch')
    changed.write_bytes(b'cccc')                     # size differs from its ledger line
    os.utime(changed, (time.time() - VERY_OLD,) * 2)
    unledgered = host.put('unledgered.dm_91', b'bbb', age=VERY_OLD)
    # uploads fail, so `unledgered` and the re-sent `changed` never get a line
    r = host.run(FAKE_RCLONE_FAIL='copyto')
    assert not expired.exists()
    assert unledgered.exists() and changed.exists() and young.exists() and old_keep.exists()
    assert host.last_run()['deleted'] == '1'
    assert r.returncode == 1


def test_failed_upload_keeps_everything_and_exits_1(host):
    old = host.put('x.dm_91', age=VERY_OLD)
    host.put('y.qlmatch')
    r = host.run(FAKE_RCLONE_FAIL='1')
    assert r.returncode == 1, r.stdout + r.stderr
    assert host.ledger() == []
    assert old.exists()
    last = host.last_run()
    assert last['exit'] == '1' and last['failed'] == '2' and last['deleted'] == '0'
    # next run with a working remote retries and succeeds
    assert host.run().returncode == 0


def test_cleanup_requires_remote_confirmation(host):
    gone = host.put('gone.dm_91', b'aaaa', age=VERY_OLD)
    wrong = host.put('wrong.dm_91', b'bbbb', age=VERY_OLD)
    good = host.put('good.dm_91', b'cccc', age=VERY_OLD)
    # first run uploads and ledgers all three; the cleanup in that same run
    # would delete them, so ledger by hand instead and keep them on disk
    stat = lambda p: (p.stat().st_size, int(p.stat().st_mtime))
    host.state.mkdir()
    with open(host.state / 'delivered.tsv', 'w', encoding='utf-8', newline='\n') as f:
        for p in (gone, wrong, good):
            size, mt = stat(p)
            f.write(f'{p.name}\t{size}\t{mt}\t2026-01-01T00:00:00Z\n')
    (host.remote / 'raw').mkdir(parents=True)
    (host.remote / 'raw' / 'wrong.dm_91').write_bytes(b'bb')       # other size
    (host.remote / 'raw' / 'good.dm_91').write_bytes(b'cccc')
    r = host.run(FAKE_RCLONE_FAIL='')
    assert gone.exists() and wrong.exists()
    assert not good.exists()
    last = host.last_run()
    assert last['kept_unconfirmed'] == '2'
    assert last['deleted'] == '1'
    assert r.returncode == 1


def test_purge_deletes_every_confirmed_file_regardless_of_age_and_pattern(host):
    q = host.put('a.qlmatch', b'q', age=OLD)
    rp = host.put('a.replay.json.gz', b'rp', age=OLD)
    dm = host.put('young.dm_91', b'dm', age=OLD)
    unconfirmed = host.put('b.dm_91', b'zz', age=OLD)
    (host.demos[0] / 'ignored.txt').write_bytes(b'not a pattern')
    assert host.run().returncode == 0
    assert q.exists() and rp.exists() and dm.exists()      # nothing expired
    (host.remote / 'raw' / 'b.dm_91').unlink()             # remote lost this one
    r = host.run('purge')
    assert not q.exists() and not rp.exists() and not dm.exists()
    assert unconfirmed.exists()
    assert (host.demos[0] / 'ignored.txt').exists()
    last = host.last_run()
    assert last['mode'] == 'purge' and last['deleted'] == '3' and last['kept_unconfirmed'] == '1'
    assert r.returncode == 1


def test_backlog_cap_sends_newest_raw_first(host):
    host.max_raw_mb = 1
    host.write_conf(MAX_RAW_MB_PER_RUN='1')
    blob = b'x' * 600 * 1024
    host.put('old.dm_91', blob, age=OLD + 3000)
    host.put('mid.dm_91', blob, age=OLD + 2000, dirindex=1)
    host.put('new.dm_91', blob, age=OLD + 1000)
    for i in range(3):
        host.put(f'p{i}.qlmatch', b'p' * 10)               # not capped
    assert host.run().returncode == 0
    assert host.remote_names('raw') == ['mid.dm_91', 'new.dm_91']
    assert len(host.remote_names('qlmatch')) == 3
    assert host.last_run()['uploaded'] == '5'
    assert host.run().returncode == 0
    assert host.remote_names('raw') == ['mid.dm_91', 'new.dm_91', 'old.dm_91']


def test_unsafe_names_are_not_sent(host):
    host.put('-dash.qlmatch', b'1')
    host.put('with space äö.qlmatch', b'22')
    newline_created = True
    try:
        host.put('bad\nname.qlmatch', b'333')
    except OSError:
        newline_created = False
    r = host.run()
    assert host.remote_names('qlmatch') == sorted(['-dash.qlmatch', 'with space äö.qlmatch'])
    if newline_created:
        assert r.returncode == 1
        assert host.last_run()['failed'] == '1'
    else:
        pytest.skip('this filesystem cannot hold a newline in a file name '
                    '(the other two names were checked)')


def test_missing_config_or_rclone_exits_2_and_deletes_nothing(host):
    old = host.put('x.dm_91', age=VERY_OLD)
    r = host.run(FORWARDER_CONF=(host.root / 'nope.conf').as_posix())
    assert r.returncode == 2
    host.write_conf(RCLONE='no-such-rclone-binary')
    r = host.run()
    assert r.returncode == 2
    host.write_conf(RETENTION_DAYS='abc')
    assert host.run().returncode == 2
    host.write_conf(PATTERNS='*.dm_91:raw:sometimes')
    assert host.run().returncode == 2
    assert old.exists() and host.remote_names('raw') == []


def test_two_concurrent_runs_do_not_overlap(host):
    host.put('slow.qlmatch', b'z')
    first = subprocess.Popen([SH, SCRIPT.as_posix(), 'run'], env=host.env(FAKE_RCLONE_DELAY='3'),
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        for _ in range(50):
            if (host.state / 'lock').exists():
                break
            time.sleep(0.1)
        second = host.run()
        assert second.returncode == 0
        assert 'locked' in second.stdout.lower()
    finally:
        out, err = first.communicate(timeout=60)
    assert first.returncode == 0, out + err
    assert host.remote_names('qlmatch') == ['slow.qlmatch']
    assert not (host.state / 'lock').exists()
