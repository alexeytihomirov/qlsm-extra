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
    if [ -n "${FAKE_LSJSON_RAW:-}" ]; then cat "$FAKE_LSJSON_RAW"; exit 0; fi
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
        # Even with a missing config the script falls back to $STATE_DIR: keep that inside
        # the temp dir so a test can never write under the real default (/home/ql).
        env['STATE_DIR'] = self.state.as_posix()
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


OLD_DELIVERY = '2026-01-01T00:00:00Z'    # far longer ago than DELIVERED_GRACE_HOURS (24)


def iso_ago(seconds):
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(time.time() - seconds))


def seed_ledger(host, files, remote_dir='raw', delivered_at=OLD_DELIVERY, remote=True):
    """Ledger the given files as delivered (current size and mtime) at
    `delivered_at` and, with `remote`, put a matching copy on the fake remote,
    as if an earlier run had sent them."""
    host.state.mkdir(exist_ok=True)
    (host.remote / remote_dir).mkdir(parents=True, exist_ok=True)
    with open(host.state / 'delivered.tsv', 'a', encoding='utf-8', newline='\n') as f:
        for p in files:
            st = p.stat()
            f.write(f'{p.name}\t{st.st_size}\t{int(st.st_mtime)}\t{delivered_at}\n')
            if remote:
                (host.remote / remote_dir / p.name).write_bytes(p.read_bytes())


def test_run_deletes_expired_raw_by_ledger_without_remote_copy(host):
    # the NAS MOVE sync already took it off the VPS: the ledger alone decides in run mode
    f = host.put('moved.dm_91', b'aaaa', age=VERY_OLD)
    seed_ledger(host, [f], remote=False)
    r = host.run()
    assert not f.exists(), r.stdout + r.stderr
    last = host.last_run()
    assert last['deleted'] == '1' and last['kept_unconfirmed'] == '0' and last['exit'] == '0'
    assert r.returncode == 0


def test_file_delivered_in_this_run_is_not_deleted_in_this_run(host):
    f = host.put('backlog.dm_91', b'old demo', age=VERY_OLD)     # unledgered backlog file
    r = host.run()
    assert r.returncode == 0, r.stdout + r.stderr
    assert host.remote_names('raw') == ['backlog.dm_91']
    assert f.exists()
    assert host.last_run()['deleted'] == '0'
    assert host.run().returncode == 0                            # still inside the grace
    assert f.exists()
    # once its delivery is older than the grace, the next run deletes it
    ledger = host.state / 'delivered.tsv'
    rows = [line.split('\t') for line in ledger.read_text(encoding='utf-8').splitlines()]
    ledger.write_text(''.join('\t'.join(row[:3] + [iso_ago(25 * 3600)]) + '\n' for row in rows),
                      encoding='utf-8', newline='\n')
    assert host.run().returncode == 0
    assert not f.exists()


def test_delivery_younger_than_the_grace_keeps_the_file(host):
    fresh = host.put('fresh.dm_91', b'aaaa', age=VERY_OLD)
    older = host.put('older.dm_91', b'bbbb', age=VERY_OLD)
    seed_ledger(host, [fresh], delivered_at=iso_ago(3600), remote=False)
    seed_ledger(host, [older], delivered_at=iso_ago(3 * 3600), remote=False)
    host.write_conf(DELIVERED_GRACE_HOURS='2')
    r = host.run()
    assert r.returncode == 0, r.stdout + r.stderr
    assert fresh.exists() and not older.exists()
    last = host.last_run()
    assert last['deleted'] == '1' and last['kept_unconfirmed'] == '0'


@pytest.mark.parametrize('delivered_at', [
    'garbage', '', '2026-13-01T00:00:00Z', '2026-01-01 00:00:00', '2026-01-01T00:00:00', None,
])
def test_unparseable_delivered_at_keeps_the_file(host, delivered_at):
    f = host.put('odd.dm_91', b'aaaa', age=VERY_OLD)
    host.state.mkdir(exist_ok=True)
    st = f.stat()
    key = f'{f.name}\t{st.st_size}\t{int(st.st_mtime)}'
    line = key if delivered_at is None else f'{key}\t{delivered_at}'
    (host.state / 'delivered.tsv').write_text(line + '\n', encoding='utf-8', newline='\n')
    r = host.run()
    assert f.exists(), r.stdout + r.stderr
    assert host.last_run()['deleted'] == '0'
    assert r.returncode == 0
    # the same file with a readable old delivery time goes
    (host.state / 'delivered.tsv').write_text(f'{key}\t{OLD_DELIVERY}\n', encoding='utf-8', newline='\n')
    assert host.run().returncode == 0
    assert not f.exists()


def test_purge_deletes_expire_row_absent_from_remote_only_after_the_grace(host):
    old = host.put('old.dm_91', b'aaaa', age=OLD)
    fresh = host.put('fresh.dm_91', b'bbbb', age=OLD)
    seed_ledger(host, [old], remote=False)
    seed_ledger(host, [fresh], delivered_at=iso_ago(600), remote=False)
    r = host.run('purge')
    assert not old.exists() and fresh.exists(), r.stdout + r.stderr
    last = host.last_run()
    assert last['deleted'] == '1' and last['kept_unconfirmed'] == '1'
    assert r.returncode == 0


def test_remote_raw_over_budget_skips_raw_uploads(host):
    host.write_conf(MAX_RAW_REMOTE_MB='1')
    (host.remote / 'raw').mkdir()
    (host.remote / 'raw' / 'waiting.dm_91').write_bytes(b'w' * (1024 * 1024 + 10))
    host.put('new.dm_91', b'demo')
    host.put('new.qlmatch', b'pack')
    r = host.run()
    assert r.returncode == 0, r.stdout + r.stderr
    assert host.remote_names('raw') == ['waiting.dm_91']
    assert host.remote_names('qlmatch') == ['new.qlmatch']
    last = host.last_run()
    assert last['uploaded'] == '1' and last['failed'] == '0' and last['exit'] == '0'
    assert 'MAX_RAW_REMOTE_MB' in r.stdout
    # once the NAS has pulled raw/, the demo goes
    (host.remote / 'raw' / 'waiting.dm_91').unlink()
    assert host.run().returncode == 0
    assert host.remote_names('raw') == ['new.dm_91']


def test_cleanup_deletes_only_expired_ledgered_expire_rows(host):
    expired = host.put('expired.dm_91', b'aaa', age=VERY_OLD)
    young = host.put('young.dm_91', b'ddd', age=OLD)
    changed = host.put('changed.dm_91', b'ccc', age=VERY_OLD)
    old_keep = host.put('old.qlmatch', b'eee', age=VERY_OLD)
    dotdot = host.put('a..b.dm_91', b'fff', age=VERY_OLD)       # a name with `..` is an ordinary name
    touched = host.put('touched.dm_91', b'ggg', age=VERY_OLD)
    seed_ledger(host, [expired, young, changed, dotdot, touched])
    seed_ledger(host, [old_keep], remote_dir='qlmatch')
    changed.write_bytes(b'cccc')                     # size differs from its ledger line
    os.utime(changed, (time.time() - VERY_OLD,) * 2)
    os.utime(touched, (time.time() - VERY_OLD - 1000,) * 2)   # only the mtime differs
    unledgered = host.put('unledgered.dm_91', b'bbb', age=VERY_OLD)
    # uploads fail, so `unledgered` and the re-sent `changed`/`touched` never get a line
    r = host.run(FAKE_RCLONE_FAIL='copyto')
    assert not expired.exists() and not dotdot.exists()
    assert unledgered.exists() and changed.exists() and touched.exists()
    assert young.exists() and old_keep.exists()
    assert host.last_run()['deleted'] == '2'
    assert r.returncode == 1


def test_purge_keeps_confirmable_keep_row_file_when_listing_fails(host):
    f = host.put('listed.qlmatch', b'aaaa', age=VERY_OLD)
    seed_ledger(host, [f], remote_dir='qlmatch')     # ledgered, remote copy present
    r = host.run('purge', FAKE_RCLONE_FAIL='1')      # but lsjson fails right now
    assert f.exists()
    last = host.last_run()
    assert last['kept_unconfirmed'] == '1' and last['deleted'] == '0' and last['failed'] == '0'
    assert r.returncode == 0


def test_same_name_in_two_source_dirs_is_never_sent_or_deleted(host):
    a = host.put('dup.dm_91', b'same', age=VERY_OLD, dirindex=0)
    b = host.put('dup.dm_91', b'same', age=VERY_OLD + 500, dirindex=1)   # same size, other mtime
    seed_ledger(host, [a])                           # one copy was ledgered earlier
    ok = host.put('fine.qlmatch', b'ok')
    r = host.run()
    assert a.exists() and b.exists() and ok.exists()
    assert host.remote_names('qlmatch') == ['fine.qlmatch']
    assert [row[0] for row in host.ledger()].count('dup.dm_91') == 1      # only the seeded line
    last = host.last_run()
    assert last['uploaded'] == '1' and last['failed'] == '2' and last['deleted'] == '0'
    assert 'collision' in r.stdout and a.as_posix() in r.stdout and b.as_posix() in r.stdout
    assert r.returncode == 1


def test_lsjson_go_style_json_confirms_the_right_files_only(host):
    # purge confirms `keep` rows by the remote listing only
    def mk(name, content):
        return host.put(name, content, age=VERY_OLD)
    amp = mk('a&b.qlmatch', b'1234')           # remote name is a&b.qlmatch
    brace = mk('c}d.qlmatch', b'12345')        # literal brace in the name
    bad_brace = mk('x}y.qlmatch', b'123')      # remote has another size
    ghost = mk('ghost.qlmatch', b'1234')       # a record with a Name but no Size, then a Size alone
    cafe = mk('café.qlmatch', b'123456')       # remote name uses a non-ASCII escape: unconfirmed
    hashes = mk('h.qlmatch', b'12')            # nested Hashes object after Size
    late = mk('s.qlmatch', b'1234567')         # Size after a nested Hashes object
    seed_ledger(host, [amp, brace, bad_brace, ghost, cafe, hashes, late], remote_dir='qlmatch')
    raw = host.root / 'lsjson.json'
    # "@U" stands for a backslash-u escape, as rclone (Go) writes & and non-ASCII letters
    raw.write_bytes('''[
{"Path":"sub","Name":"sub","Size":-1,"IsDir":true},
{"Path":"a@U0026b.qlmatch","Name":"a@U0026b.qlmatch","Size":4,"IsDir":false},
{"Path":"c}d.qlmatch","Name":"c}d.qlmatch","Size":5,"IsDir":false},
{"Path":"x}y.qlmatch","Name":"x}y.qlmatch","Size":9,"IsDir":false},
{"Name":"ghost.qlmatch","IsDir":false},
{"Size":4,"IsDir":false},
{"Path":"caf@U00e9.qlmatch","Name":"caf@U00e9.qlmatch","Size":6,"IsDir":false},
{"Path":"h.qlmatch","Name":"h.qlmatch","Size":2,"Hashes":{"md5":"abc"},"IsDir":false},
{"Name":"s.qlmatch","Hashes":{"md5":"x"},"Size":7,"IsDir":false}
]
'''.replace('@U', chr(92) + 'u').encode('utf-8'))
    r = host.run('purge', FAKE_LSJSON_RAW=raw.as_posix())
    assert not amp.exists() and not brace.exists() and not hashes.exists() and not late.exists()
    assert bad_brace.exists() and ghost.exists() and cafe.exists()
    last = host.last_run()
    assert last['deleted'] == '4' and last['kept_unconfirmed'] == '3'
    assert r.returncode == 0


def test_stale_tmp_dirs_of_killed_runs_are_removed(host):
    stale = host.state / 'tmp.12345'
    stale.mkdir(parents=True)
    (stale / 'keys').write_text('x')
    assert host.run().returncode == 0
    assert not stale.exists()


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


def test_purge_keep_rows_require_remote_confirmation(host):
    gone = host.put('gone.qlmatch', b'aaaa', age=VERY_OLD)
    wrong = host.put('wrong.qlmatch', b'bbbb', age=VERY_OLD)
    good = host.put('good.qlmatch', b'cccc', age=VERY_OLD)
    seed_ledger(host, [gone, wrong, good], remote_dir='qlmatch', remote=False)
    (host.remote / 'qlmatch' / 'wrong.qlmatch').write_bytes(b'bb')       # other size
    (host.remote / 'qlmatch' / 'good.qlmatch').write_bytes(b'cccc')
    assert host.run().returncode == 0                # run mode never deletes keep rows
    assert gone.exists() and wrong.exists() and good.exists()
    r = host.run('purge')
    assert gone.exists() and wrong.exists()          # old delivery, but keep rows need the remote
    assert not good.exists()
    last = host.last_run()
    assert last['kept_unconfirmed'] == '2'
    assert last['deleted'] == '1'
    assert r.returncode == 0


def test_purge_deletes_every_confirmed_file_regardless_of_age_and_pattern(host):
    q = host.put('a.qlmatch', b'q', age=OLD)
    rp = host.put('a.replay.json.gz', b'rp', age=OLD)
    dm = host.put('young.dm_91', b'dm', age=OLD)
    unconfirmed = host.put('b.dm_91', b'zz', age=OLD)
    (host.demos[0] / 'ignored.txt').write_bytes(b'not a pattern')
    assert host.run().returncode == 0
    assert q.exists() and rp.exists() and dm.exists()      # nothing expired
    (host.remote / 'raw' / 'b.dm_91').unlink()             # remote lost this one, delivered just now
    r = host.run('purge')
    assert not q.exists() and not rp.exists() and not dm.exists()
    assert unconfirmed.exists()
    assert (host.demos[0] / 'ignored.txt').exists()
    last = host.last_run()
    assert last['mode'] == 'purge' and last['deleted'] == '3' and last['kept_unconfirmed'] == '1'
    assert r.returncode == 0


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


def test_dash_space_and_non_ascii_names_are_sent(host):
    host.put('-dash.qlmatch', b'1')
    host.put('with space äö.qlmatch', b'22')
    r = host.run()
    assert r.returncode == 0, r.stdout + r.stderr
    assert host.remote_names('qlmatch') == sorted(['-dash.qlmatch', 'with space äö.qlmatch'])


@pytest.mark.skipif(os.name == 'nt', reason='Windows cannot create a file name with a newline')
def test_newline_name_is_skipped_and_counted_failed(host):
    host.put('bad\nname.qlmatch', b'333')
    host.put('good.qlmatch', b'1')
    r = host.run()
    assert host.remote_names('qlmatch') == ['good.qlmatch']
    assert host.last_run()['failed'] == '1'
    assert r.returncode == 1


def test_missing_config_or_rclone_exits_2_and_deletes_nothing(host):
    old = host.put('x.dm_91', age=VERY_OLD)
    r = host.run(FORWARDER_CONF=(host.root / 'nope.conf').as_posix())
    assert r.returncode == 2
    assert host.last_run()['exit'] == '2'            # written into the test STATE_DIR
    host.write_conf(PATTERNS='*.dm_91:ra/w:expire')
    assert host.run().returncode == 2
    host.write_conf(RCLONE='no-such-rclone-binary')
    r = host.run()
    assert r.returncode == 2
    host.write_conf(RETENTION_DAYS='abc')
    assert host.run().returncode == 2
    host.write_conf(PATTERNS='*.dm_91:raw:sometimes')
    assert host.run().returncode == 2
    for key, value in (('DELIVERED_GRACE_HOURS', '0'), ('DELIVERED_GRACE_HOURS', '1h'),
                       ('MAX_RAW_REMOTE_MB', ''), ('MAX_RAW_REMOTE_MB', '0')):
        host.write_conf(**{key: value})
        assert host.run().returncode == 2, (key, value)
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
