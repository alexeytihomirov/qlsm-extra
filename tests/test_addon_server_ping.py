"""The server-ping addon inside qlsm: manifest, routes, the shared DTLS certificate,
payload sync / apply, status parsing, and the host firewall script (standalone)."""
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ADDON_DIR = Path(__file__).resolve().parent.parent / 'addons' / 'server-ping'
VERSION = json.loads((ADDON_DIR / 'qlsm-addon.json').read_text(encoding='utf-8'))['version'] \
    if (ADDON_DIR / 'qlsm-addon.json').is_file() else None
API = '/api/addons/server-ping'
MODULE = 'qlsm_addon_server_ping'
FINGERPRINT_RE = re.compile(r'^[0-9A-F]{2}(:[0-9A-F]{2}){31}$')


@pytest.fixture
def addon_id():
    return 'server-ping'


def _backend():
    return sys.modules[MODULE]


def test_manifest_validates(app):
    from ui.addons import get_addon
    from ui.addons.manifest import read_manifest

    manifest, errors = read_manifest(str(ADDON_DIR))
    assert errors == []
    assert manifest['id'] == 'server-ping'
    assert manifest['scopes'] == ['global', 'host']
    assert manifest['ui_api'] == 3
    fields = {f['key']: f for f in manifest['settings']['global']}
    assert fields['port']['type'] == 'string' and fields['port']['default'] == '28111'
    assert fields['dtls_cert']['type'] == 'secret'
    host_fields = {f['key']: f for f in manifest['settings']['host']}
    assert host_fields['enabled']['type'] == 'bool' and host_fields['enabled']['default'] is True
    with app.app_context():
        addon = get_addon('server-ping', app)
        assert addon.loaded, addon.errors
        assert addon.errors == []


ROUTES = [
    ('GET', 'settings'),
    ('PUT', 'settings'),
    ('POST', 'generate-cert'),
    ('GET', 'fingerprint'),
    ('GET', 'hosts'),
    ('PUT', 'hosts/1'),
    ('POST', 'hosts/1/apply'),
    ('GET', 'hosts/1/status'),
]


@pytest.mark.parametrize('method, path', ROUTES)
def test_every_route_needs_a_logged_in_operator(client, method, path):
    assert client.open(f'{API}/{path}', method=method, json={}).status_code == 401


@pytest.fixture
def auth(app):
    from conftest import auth_headers, make_user
    make_user(app, 'spop', 'pw')
    return auth_headers(app, 'spop')


def _host(app, name='game-1'):
    from ui import db
    from ui.models import Host, HostStatus
    with app.app_context():
        host = Host(name=name, ip_address='10.0.0.1', provider='standalone',
                    runtime='minqlxtended', status=HostStatus.ACTIVE)
        db.session.add(host)
        db.session.commit()
        return host.id


def _ctx(app):
    from ui.addons import get_addon
    return get_addon('server-ping', app).ctx


def _enable(app, host_id=None, host_enabled=True, global_enabled=True):
    with app.app_context():
        settings = _ctx(app).settings
        settings.set_enabled('global', 0, global_enabled)
        if host_id is not None:
            settings.set('host', host_id, {'enabled': host_enabled})


def _stored_cert(app):
    with app.app_context():
        return _ctx(app).settings.get('global', 0)['dtls_cert']


class FakePlaybook:
    def __init__(self, success=True, stdout='', stderr=''):
        self.calls = []
        self.result = (success, stdout, stderr)

    def __call__(self, host, name, extravars=None):
        extravars = dict(extravars or {})
        cert_file = extravars.get('sp_cert_file')
        # The PEM travels as a private temp file, never as an extravar (core logs those).
        self.cert_pem = Path(cert_file).read_text(encoding='ascii') if cert_file else None
        self.cert_file = cert_file
        self.calls.append((host.id, name, extravars))
        return self.result


# ---- settings and the certificate ------------------------------------------------

def test_settings_round_trip_and_validation(app, client, auth):
    assert client.get(f'{API}/settings', headers=auth).get_json()['data'] == {'port': '28111'}
    assert client.put(f'{API}/settings', headers=auth, json={'port': '28200'}).status_code == 200
    assert client.get(f'{API}/settings', headers=auth).get_json()['data'] == {'port': '28200'}
    for bad in ('abc', '80', '70000', '', '28111; rm'):
        assert client.put(f'{API}/settings', headers=auth, json={'port': bad}).status_code == 400, bad
    assert client.put(f'{API}/settings', headers=auth, json={'dtls_cert': 'x'}).status_code == 400
    assert client.get(f'{API}/settings', headers=auth).get_json()['data'] == {'port': '28200'}


def test_generate_cert_then_fingerprint(app, client, auth):
    before = client.get(f'{API}/fingerprint', headers=auth).get_json()['data']
    assert before['fingerprint'] is None

    response = client.post(f'{API}/generate-cert', headers=auth)
    assert response.status_code == 200, response.get_json()
    generated = response.get_json()['data']['fingerprint']
    assert FINGERPRINT_RE.match(generated), generated

    pem = _stored_cert(app)
    assert '-----BEGIN EC PRIVATE KEY-----' in pem and '-----BEGIN CERTIFICATE-----' in pem
    after = client.get(f'{API}/fingerprint', headers=auth).get_json()['data']
    assert after['fingerprint'] == generated

    # The fingerprint is the SHA-256 of the certificate (what the browser's SDP carries),
    # and the key is P-256 and matches it; the certificate lives ten years.
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    cert = x509.load_pem_x509_certificate(pem.encode())
    assert ':'.join(f'{b:02X}' for b in cert.fingerprint(hashes.SHA256())) == generated
    key = serialization.load_pem_private_key(pem.encode(), password=None)
    assert isinstance(key.curve, ec.SECP256R1)
    assert key.public_key().public_numbers() == cert.public_key().public_numbers()
    lifetime = cert.not_valid_after_utc - cert.not_valid_before_utc
    assert lifetime.days >= 3650


def test_generate_cert_refuses_to_overwrite(app, client, auth):
    assert client.post(f'{API}/generate-cert', headers=auth).status_code == 200
    first = _stored_cert(app)
    response = client.post(f'{API}/generate-cert', headers=auth)
    assert response.status_code == 409
    assert _stored_cert(app) == first


def test_a_broken_stored_cert_has_no_fingerprint(app, client, auth):
    with app.app_context():
        _ctx(app).settings.set('global', 0, {'dtls_cert': 'not a pem'})
    data = client.get(f'{API}/fingerprint', headers=auth).get_json()['data']
    assert data['fingerprint'] is None and data['error']


# ---- payload sync and apply --------------------------------------------------------

def _payload_sync(app, host_id):
    from ui.addons import dispatch
    with app.app_context():
        dispatch('host.payload_sync', host_id, host_id)


def _with_cert(app, client, auth):
    assert client.post(f'{API}/generate-cert', headers=auth).status_code == 200
    return _stored_cert(app)


def test_payload_sync_skips_a_disabled_host(app, client, auth, monkeypatch):
    _with_cert(app, client, auth)
    host_id = _host(app)
    _enable(app, host_id, host_enabled=False)
    fake = FakePlaybook()
    monkeypatch.setattr(_ctx(app), 'run_playbook', fake)
    _payload_sync(app, host_id)
    assert fake.calls == []


def test_payload_sync_skips_when_the_addon_is_off(app, client, auth, monkeypatch):
    _with_cert(app, client, auth)
    host_id = _host(app)
    _enable(app, host_id, global_enabled=False)
    fake = FakePlaybook()
    monkeypatch.setattr(_ctx(app), 'run_playbook', fake)
    _payload_sync(app, host_id)
    assert fake.calls == []


def test_payload_sync_deploys_an_enabled_host(app, client, auth, monkeypatch):
    pem = _with_cert(app, client, auth)
    host_id = _host(app)
    _enable(app, host_id)
    fake = FakePlaybook()
    monkeypatch.setattr(_ctx(app), 'run_playbook', fake)
    _payload_sync(app, host_id)

    assert len(fake.calls) == 1
    called_host, name, extravars = fake.calls[0]
    assert (called_host, name) == (host_id, 'sync_server_ping.yml')
    assert extravars['sp_enabled'] is True
    assert extravars['sp_port'] == '28111'
    assert extravars['sp_version'] == VERSION
    assert 'sp_cert_pem' not in extravars and 'PRIVATE KEY' not in json.dumps(extravars)
    assert fake.cert_pem.strip() == pem.strip()
    assert not os.path.exists(fake.cert_file)   # removed after the run


def test_payload_sync_without_a_cert_runs_nothing(app, monkeypatch):
    host_id = _host(app)
    _enable(app, host_id)
    fake = FakePlaybook()
    monkeypatch.setattr(_ctx(app), 'run_playbook', fake)
    _payload_sync(app, host_id)
    assert fake.calls == []


def test_apply_of_a_switched_off_host_removes_without_the_cert(app, monkeypatch):
    host_id = _host(app)
    _enable(app, host_id, host_enabled=False)
    fake = FakePlaybook()
    monkeypatch.setattr(_ctx(app), 'run_playbook', fake)
    with app.app_context():
        result = _backend().apply_host(host_id)
    assert result['success'] is True
    extravars = fake.calls[0][2]
    assert extravars['sp_enabled'] is False and extravars['sp_cert_file'] == ''


def test_a_failed_playbook_is_reported(app, client, auth, monkeypatch):
    _with_cert(app, client, auth)
    host_id = _host(app)
    monkeypatch.setattr(_ctx(app), 'run_playbook', FakePlaybook(success=False, stderr='boom'))
    with app.app_context():
        result = _backend().apply_host(host_id)
    assert result['success'] is False


# ---- routes: hosts, apply queue, status ------------------------------------------

@pytest.fixture
def queue(monkeypatch):
    import ui.task_lock
    import ui.tasks
    calls = []
    monkeypatch.setattr(ui.task_lock, 'acquire_lock', lambda *a, **k: True)
    monkeypatch.setattr(ui.task_lock, 'release_lock', lambda *a, **k: True)
    monkeypatch.setattr(ui.tasks, 'enqueue_task',
                        lambda task, *args, **kwargs: calls.append((task.__name__, args, kwargs)))
    return calls


def test_hosts_list_and_switch(app, client, auth):
    host_id = _host(app)
    hosts = client.get(f'{API}/hosts', headers=auth).get_json()['data']['hosts']
    assert hosts == [{'id': host_id, 'name': 'game-1', 'enabled': True}]
    assert client.put(f'{API}/hosts/{host_id}', headers=auth, json={'enabled': False}).status_code == 200
    hosts = client.get(f'{API}/hosts', headers=auth).get_json()['data']['hosts']
    assert hosts[0]['enabled'] is False
    assert client.put(f'{API}/hosts/{host_id}', headers=auth, json={'enabled': 'no'}).status_code == 400
    assert client.put(f'{API}/hosts/9999', headers=auth, json={'enabled': True}).status_code == 404


def test_apply_enqueues_the_apply_task(app, client, auth, queue):
    _with_cert(app, client, auth)
    host_id = _host(app)
    response = client.post(f'{API}/hosts/{host_id}/apply', headers=auth)
    assert response.status_code == 202, response.get_json()
    assert len(queue) == 1
    name, args, kwargs = queue[0]
    assert name == 'apply_task' and args[0] == host_id and kwargs['lock_token']


def test_apply_of_an_enabled_host_needs_a_cert(app, client, auth, queue):
    host_id = _host(app)
    response = client.post(f'{API}/hosts/{host_id}/apply', headers=auth)
    assert response.status_code == 409
    assert queue == []
    assert client.post(f'{API}/hosts/9999/apply', headers=auth).status_code == 404


def test_a_busy_host_gets_409(app, client, auth, monkeypatch):
    import ui.task_lock
    _with_cert(app, client, auth)
    monkeypatch.setattr(ui.task_lock, 'acquire_lock', lambda *a, **k: False)
    host_id = _host(app)
    assert client.post(f'{API}/hosts/{host_id}/apply', headers=auth).status_code == 409


FP = ':'.join(['AB'] * 32)
STATUS_STDOUT = f'''
ok: [game-1] => {{
    "msg": [
        "SP_VERSION=1.0.0",
        "SP_SERVICE=active",
        "SP_FIREWALL=yes",
        "SP_FINGERPRINT=sha256 Fingerprint={FP}"
    ]
}}
'''


def test_status_is_parsed_from_the_playbook(app, client, auth, monkeypatch):
    host_id = _host(app)
    fake = FakePlaybook(stdout=STATUS_STDOUT)
    monkeypatch.setattr(_ctx(app), 'run_playbook', fake)
    response = client.get(f'{API}/hosts/{host_id}/status', headers=auth)
    assert response.status_code == 200
    data = response.get_json()['data']
    assert data == {'version': '1.0.0', 'service': 'active', 'firewall': True,
                    'fingerprint': FP, 'expected_version': VERSION,
                    'expected_fingerprint': None, 'error': None}
    assert fake.calls == [(host_id, 'status_server_ping.yml', {})]


@pytest.mark.parametrize('stdout, expected', [
    ('"SP_VERSION=1.0.0; rm -rf /"\n"SP_SERVICE=ACTIVE;x"\n"SP_FIREWALL=maybe"',
     {'version': None, 'service': None, 'firewall': None, 'fingerprint': None}),
    ('"SP_VERSION="\n"SP_SERVICE=inactive"\n"SP_FIREWALL=no"\n"SP_FINGERPRINT="',
     {'version': None, 'service': 'inactive', 'firewall': False, 'fingerprint': None}),
    ('garbage', {'version': None, 'service': None, 'firewall': None, 'fingerprint': None}),
])
def test_parse_status_is_strict(app, stdout, expected):
    status = _backend().parse_status(stdout, '1.0.0', None)
    assert {k: status[k] for k in expected} == expected


def test_status_of_an_unreachable_host_is_200_with_nulls(app, client, auth, monkeypatch):
    host_id = _host(app)
    monkeypatch.setattr(_ctx(app), 'run_playbook', FakePlaybook(success=False, stderr='unreachable'))
    response = client.get(f'{API}/hosts/{host_id}/status', headers=auth)
    assert response.status_code == 200
    data = response.get_json()['data']
    assert data['version'] is None and data['service'] is None and data['error']
    assert client.get(f'{API}/hosts/9999/status', headers=auth).status_code == 404


# ---- host-side files --------------------------------------------------------------

def test_service_unit_has_the_agreed_shape():
    unit = (ADDON_DIR / 'assets' / 'ql-ping-echo.service').read_text(encoding='utf-8')
    for line in ('User=ql-ping', 'Nice=19', 'CPUWeight=1',
                 'ExecStartPre=+/opt/ql-ping-echo/ql-ping-firewall', 'AmbientCapabilities=',
                 'Restart=always', 'RestartSec=10'):
        assert re.search(rf'^{re.escape(line)}\s*$', unit, re.M), line
    assert '/etc/ql-ping-echo/cert.pem' in unit and '/etc/ql-ping-echo/port' in unit


@pytest.mark.standalone
def test_playbooks_install_the_binary_executable():
    sync = (ADDON_DIR / 'playbooks' / 'sync_server_ping.yml').read_text(encoding='utf-8')
    assert 'ql-ping-echo' in sync and 'mode: "0755"' in sync
    assert 'QLPING-INPUT' in sync or 'ql-ping-firewall remove' in sync
    assert 'NRestarts' in sync and 'rescue:' in sync
    assert (ADDON_DIR / 'playbooks' / 'status_server_ping.yml').is_file()


FAKE_IPTABLES = r'''#!/usr/bin/env bash
# Fake iptables: one file per chain under $FAKE_IPT_STATE, every call logged.
state="$FAKE_IPT_STATE"
echo "$*" >> "$state/log"
args=()
for a in "$@"; do [ "$a" = "-w" ] || args+=("$a"); done
op="${args[0]}"; chain="${args[1]}"
file="$state/chain.$chain"
case "$op" in
  -N) [ -e "$file" ] && exit 1; : > "$file" ;;
  -X) [ -e "$file" ] || exit 1; rm -f "$file" ;;
  -F) [ -e "$file" ] || exit 1; : > "$file" ;;
  -C) [ -e "$file" ] || exit 1; grep -Fxq -- "${args[*]:2}" "$file" ;;
  -A) [ -e "$file" ] || exit 1; echo "${args[*]:2}" >> "$file" ;;
  -I) [ -e "$file" ] || exit 1; { echo "${args[*]:3}"; cat "$file"; } > "$file.new"; mv "$file.new" "$file" ;;
  -D) [ -e "$file" ] || exit 1
      rule="${args[*]:2}"
      grep -Fxq -- "$rule" "$file" || exit 1
      awk -v r="$rule" 'done || $0 != r { print; next } { done = 1 }' "$file" > "$file.new"
      mv "$file.new" "$file" ;;
  *) exit 2 ;;
esac
'''


def _bash():
    """Git Bash on Windows (never WSL's System32 bash), plain bash elsewhere."""
    for candidate in (r'C:\Program Files\Git\usr\bin\bash.exe', r'C:\Program Files\Git\bin\bash.exe'):
        if os.name == 'nt' and os.path.isfile(candidate):
            return candidate
    found = shutil.which('bash')
    if not found or 'system32' in found.lower():
        pytest.skip('no bash')
    return found


def _firewall(tmp_path, *args, port='28111'):
    bin_dir = tmp_path / 'bin'
    state = tmp_path / 'state'
    if not bin_dir.exists():
        bin_dir.mkdir()
        state.mkdir()
        (state / 'chain.INPUT').write_text('', encoding='utf-8')
        fake = bin_dir / 'iptables'
        fake.write_text(FAKE_IPTABLES, encoding='utf-8', newline='\n')
        fake.chmod(0o755)
    (tmp_path / 'port').write_text(port + '\n', encoding='utf-8', newline='\n')
    env = dict(os.environ, FAKE_IPT_STATE=state.as_posix(),
               QLPING_PORT_FILE=(tmp_path / 'port').as_posix(),
               PATH=str(bin_dir) + os.pathsep + os.environ.get('PATH', ''))
    script = (ADDON_DIR / 'assets' / 'ql-ping-firewall').as_posix()
    result = subprocess.run([_bash(), script, *args], env=env, capture_output=True, text=True,
                            timeout=30)
    return result, state


def _chain(state, name):
    path = state / f'chain.{name}'
    return path.read_text(encoding='utf-8').splitlines() if path.exists() else None


@pytest.mark.standalone
def test_firewall_script_is_idempotent(tmp_path):
    for _ in range(2):
        result, state = _firewall(tmp_path)
        assert result.returncode == 0, result.stderr
    assert _chain(state, 'INPUT') == ['-j QLPING-INPUT']
    assert _chain(state, 'QLPING-INPUT') == ['-p udp --dport 28111 -j ACCEPT']
    log = (state / 'log').read_text(encoding='utf-8').splitlines()
    assert sum(1 for line in log if '-I INPUT' in line) == 1
    assert not any('QLSM-INPUT' in line for line in log)

    # A port change replaces the rule, the hook stays single.
    result, state = _firewall(tmp_path, port='28200')
    assert result.returncode == 0, result.stderr
    assert _chain(state, 'INPUT') == ['-j QLPING-INPUT']
    assert _chain(state, 'QLPING-INPUT') == ['-p udp --dport 28200 -j ACCEPT']

    result, state = _firewall(tmp_path, 'remove')
    assert result.returncode == 0, result.stderr
    assert _chain(state, 'INPUT') == []
    assert _chain(state, 'QLPING-INPUT') is None
    result, state = _firewall(tmp_path, 'remove')
    assert result.returncode == 0, result.stderr


@pytest.mark.standalone
@pytest.mark.parametrize('port', ['', 'abc', '80', '70000'])
def test_firewall_script_refuses_a_bad_port(tmp_path, port):
    result, state = _firewall(tmp_path, port=port)
    assert result.returncode != 0
    assert _chain(state, 'QLPING-INPUT') is None
