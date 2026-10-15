"""The file-forwarder addon: one install-wide SFTP key, forwarder.conf rendered
from the settings, and the host tasks that deploy and run forwarder.sh.

Two things matter most here. The private key must never leave the addon by
any route other than a 0600 file handed to the sync playbook -- not in a
response, a log line, the manifest, or the extravars (qlsm's ansible runner
logs the whole `-e` JSON at INFO). And every setting that ends up in
forwarder.conf must be validated before it gets there, because the file is
sourced by `sh` on the game host.
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ADDON_DIR = Path(__file__).resolve().parent.parent / 'addons' / 'file-forwarder'
API = '/api/addons/file-forwarder'
MODULE = 'qlsm_addon_file_forwarder'


def _load(name):
    spec = importlib.util.spec_from_file_location(f'ff_test_{name}', ADDON_DIR / f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def addon_id():
    return 'file-forwarder'


@pytest.fixture
def render():
    return _load('config_render')


DEFAULTS = {
    'vps_host': '',
    'retention_days': '14',
    'max_raw_mb_per_run': '2048',
    'interval_minutes': '10',
    'patterns': '*.qlmatch qlmatch keep; *.replay.json.gz qlmatch keep; *.dm_91 raw expire',
}
FAKE_PRIVATE = ('-----BEGIN OPENSSH PRIVATE KEY-----\n'
                'b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAABAAAAMwAAAAtzc2gtZW\n'
                '-----END OPENSSH PRIVATE KEY-----')
PRIVATE_MARKERS = ('PRIVATE KEY', 'b3BlbnNzaC1rZXktdjE')

VPS = 'vps.example.org'
VALID = dict(DEFAULTS, vps_host=VPS)
# A fixed ed25519 key; its fingerprint was computed once with `ssh-keygen -lf`.
ED25519_LINE = f'{VPS} ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIL4aIb56D/YdmM5b3fAmOwwLcxxQj8RGyvz4kITSjJc0'
ED25519_FP = 'ED25519 SHA256:UVIkJQqZ8Wfo+CCX9jNT75O3ymTa10gnGiiZaEgCO/w'
ECDSA_LINE = (f'{VPS} ecdsa-sha2-nistp256 AAAAE2VjZHNhLXNoYTItbmlzdHAyNTYAAAAIbmlzdHAyNTYAAABBBL0mi8s06cBFdiXBcs'
              '+/48Nhefma19x+rMhS0lMWo5jEYvjMj79jEpY6+euQ0qS3OFPD2Si1ML/IMLd8ofrwGqs=')
KNOWN_HOSTS = ED25519_LINE + '\n' + ECDSA_LINE + '\n'


# ---- config rendering (pure, no qlsm needed) ----------------------------------

SH = shutil.which('sh')


@pytest.mark.standalone
@pytest.mark.skipif(SH is None, reason='no sh on PATH')
def test_rendered_conf_sourced_by_sh_gives_the_forwarder_variables(render, tmp_path):
    conf = tmp_path / 'forwarder.conf'
    conf.write_text(render.render_conf(VALID), encoding='utf-8', newline='\n')
    script = ('set -eu; . ./forwarder.conf; '
              'for v in REMOTE SRC_GLOBS PATTERNS RETENTION_DAYS DELIVERED_GRACE_HOURS MIN_AGE_MIN '
              'MAX_RAW_MB_PER_RUN MAX_RAW_REMOTE_MB STATE_DIR RCLONE; do '
              'eval "printf \'%s=%s\\n\' $v \\"\\$$v\\""; done')
    out = subprocess.run([SH, '-c', script], cwd=tmp_path, capture_output=True, text=True, check=True).stdout
    values = dict(line.split('=', 1) for line in out.splitlines())
    assert values == {
        'REMOTE': 'qldemos',
        'SRC_GLOBS': '/home/ql/qlds-*/demos',
        'PATTERNS': '*.qlmatch:qlmatch:keep *.replay.json.gz:qlmatch:keep *.dm_91:raw:expire',
        'RETENTION_DAYS': '14',
        'DELIVERED_GRACE_HOURS': '24',
        'MIN_AGE_MIN': '2',
        'MAX_RAW_MB_PER_RUN': '2048',
        'MAX_RAW_REMOTE_MB': '5000',
        'STATE_DIR': '/home/ql/.forwarder-state',
        'RCLONE': 'rclone',
    }


@pytest.mark.standalone
def test_pinned_conf_values_match_the_script_defaults(render):
    script = (Path(render.ADDON_DIR) / 'assets' / 'forwarder.sh').read_text(encoding='utf-8')
    for name in ('MIN_AGE_MIN', 'DELIVERED_GRACE_HOURS', 'MAX_RAW_REMOTE_MB'):
        assert f'\n{name}={getattr(render, name)}\n' in script, name


@pytest.mark.standalone
def test_defaults_render_the_default_patterns(render):
    text = render.render_conf(dict(render.DEFAULTS, vps_host=VPS))
    assert "PATTERNS='*.qlmatch:qlmatch:keep *.replay.json.gz:qlmatch:keep *.dm_91:raw:expire'" in text
    assert render.DEFAULTS == DEFAULTS


@pytest.mark.standalone
@pytest.mark.parametrize('text', [
    '*.qlmatch qlmatch keep\n*.dm_91 raw expire',
    '*.qlmatch qlmatch keep;*.dm_91 raw expire',
    '  *.qlmatch   qlmatch keep ;\n\n ; *.dm_91\traw expire ; ',
])
def test_pattern_rows_split_on_newline_or_semicolon(render, text):
    assert render.parse_patterns(text) == [('*.qlmatch', 'qlmatch', 'keep'), ('*.dm_91', 'raw', 'expire')]


@pytest.mark.standalone
def test_integers_may_arrive_as_numbers(render):
    text = render.render_conf(dict(VALID, retention_days=7, max_raw_mb_per_run=100, interval_minutes=5))
    assert "RETENTION_DAYS='7'" in text and "MAX_RAW_MB_PER_RUN='100'" in text


@pytest.mark.standalone
@pytest.mark.parametrize('key, value', [
    ('retention_days', 'abc'),
    ('retention_days', '1.5'),
    ('retention_days', '-1'),
    ('retention_days', '0'),
    ('retention_days', ''),
    ('retention_days', True),
    ('retention_days', 1.5),
    ('retention_days', '14; rm -rf /'),
    ('max_raw_mb_per_run', 'x'),
    ('max_raw_mb_per_run', '0'),
    ('interval_minutes', '0'),
    ('interval_minutes', '1441'),
    ('patterns', ''),
    ('patterns', ' ; \n '),
    ('patterns', '*.dm_91 raw'),
    ('patterns', '*.dm_91 raw expire extra'),
    ('patterns', '*.dm_91 raw/x expire'),
    ('patterns', '*.dm_91 .. expire'),
    ('patterns', '*.dm_91 a..b expire'),
    ('patterns', '*.dm_91 .hidden expire'),
    ('patterns', '*.dm_91 -x expire'),
    ('patterns', '*.dm_91 r$w expire'),
    ('patterns', '*.dm_91 räw expire'),
    ('patterns', 'demos/*.dm_91 raw expire'),
    ('patterns', '*.dm 91 raw'),
    ('patterns', '*.dm_91 raw delete'),
    ('patterns', "*.d'm raw keep"),
    ('patterns', '*.d:m raw keep'),
    ('patterns', '*.d$(id)m raw keep'),
    ('vps_host', ''),
    ('vps_host', 'evil host'),
    ('vps_host', 'a;rm'),
    ('vps_host', '-oProxyCommand=x'),
])
def test_a_bad_value_is_refused(render, key, value):
    with pytest.raises(ValueError):
        render.render_conf(dict(VALID, **{key: value}))


@pytest.mark.standalone
def test_playbook_vars_use_stored_keys(render):
    variables = render.playbook_vars(dict(VALID, sftp_private_key=FAKE_PRIVATE,
                                          sftp_public_key='ssh-ed25519 AAAA x',
                                          vps_known_hosts=KNOWN_HOSTS.strip()))
    assert set(variables) >= {'ff_conf_text', 'ff_private_key', 'ff_known_hosts',
                              'ff_version', 'ff_interval_minutes'}
    assert variables['ff_private_key'] == FAKE_PRIVATE + '\n'
    assert variables['ff_conf_text'] == render.render_conf(VALID)
    assert variables['ff_version'] == '1.2.0'
    assert variables['ff_interval_minutes'] == 10
    assert variables['ff_vps_host'] == VPS
    assert variables['ff_sftp_user'] == 'qldemos-in'
    assert variables['ff_remote_name'] == 'qldemos'
    assert variables['ff_known_hosts'] == KNOWN_HOSTS


@pytest.mark.standalone
@pytest.mark.parametrize('settings', [
    dict(VALID, vps_known_hosts=''),
    dict(DEFAULTS, vps_known_hosts=KNOWN_HOSTS),
    dict(VALID, vps_host='other.example.org', vps_known_hosts=KNOWN_HOSTS),
])
def test_playbook_vars_without_the_address_or_its_keys_is_an_error(render, settings):
    with pytest.raises(ValueError):
        render.playbook_vars(dict(settings, sftp_private_key=FAKE_PRIVATE))


@pytest.mark.standalone
def test_no_ip_in_addon():
    for path in ADDON_DIR.rglob('*'):
        if path.is_file() and '__pycache__' not in path.parts:
            text = path.read_text(encoding='utf-8', errors='replace')
            assert '70.34.223.191' not in text, path
    assert not (ADDON_DIR / 'assets' / 'known_hosts_vps').exists()


# ---- host keys (ssh-keyscan) -----------------------------------------------------

@pytest.fixture
def hostkeys():
    return _load('hostkeys')


class FakeRun:
    def __init__(self, returncode=0, stdout='', stderr='', raises=None):
        self.calls = []
        self.returncode, self.stdout, self.stderr, self.raises = returncode, stdout, stderr, raises

    def __call__(self, args, **kwargs):
        self.calls.append((list(args), kwargs))
        if self.raises:
            raise self.raises
        return subprocess.CompletedProcess(args, self.returncode, self.stdout, self.stderr)


@pytest.mark.standalone
def test_scan_returns_key_lines_without_comments(hostkeys, monkeypatch):
    fake = FakeRun(stdout=f'# {VPS}:22 SSH-2.0-OpenSSH_9.6\n{ED25519_LINE}\n# {VPS}:22 SSH-2.0-OpenSSH_9.6\n'
                          f'{ECDSA_LINE}\n\n')
    monkeypatch.setattr(hostkeys.subprocess, 'run', fake)
    assert hostkeys.scan(VPS, timeout=7) == KNOWN_HOSTS
    args, kwargs = fake.calls[0]
    assert args == ['ssh-keyscan', '-T', '7', '-t', 'ed25519,ecdsa,rsa', VPS]
    assert kwargs.get('timeout')


@pytest.mark.standalone
@pytest.mark.parametrize('fake', [
    FakeRun(returncode=1, stdout=ED25519_LINE + '\n', stderr='getaddrinfo: no such host'),
    FakeRun(stdout=''),
    FakeRun(stdout=f'# {VPS}:22 SSH-2.0-OpenSSH_9.6\n'),
    FakeRun(raises=subprocess.TimeoutExpired(['ssh-keyscan'], 30)),
])
def test_scan_failure_raises(hostkeys, monkeypatch, fake):
    monkeypatch.setattr(hostkeys.subprocess, 'run', fake)
    with pytest.raises(hostkeys.HostKeyScanError) as excinfo:
        hostkeys.scan(VPS)
    assert str(excinfo.value)


@pytest.mark.standalone
def test_scan_names_a_missing_ssh_keyscan(hostkeys, monkeypatch):
    monkeypatch.setattr(hostkeys.subprocess, 'run', FakeRun(raises=FileNotFoundError('ssh-keyscan')))
    with pytest.raises(hostkeys.HostKeyScanError, match='ssh-keyscan'):
        hostkeys.scan(VPS)


@pytest.mark.standalone
def test_fingerprint_matches_ssh_keygen(hostkeys):
    assert hostkeys.fingerprints(ED25519_LINE + '\n') == [ED25519_FP]
    prints = hostkeys.fingerprints(KNOWN_HOSTS)
    assert prints[0] == ED25519_FP
    assert prints[1].startswith('ECDSA SHA256:') and not prints[1].endswith('=')


@pytest.mark.standalone
def test_playbook_vars_without_a_key_is_an_error(render):
    with pytest.raises(ValueError):
        render.playbook_vars(dict(DEFAULTS, sftp_private_key=''))


@pytest.mark.standalone
def test_no_private_key_material_ships_in_the_package():
    for path in ADDON_DIR.rglob('*'):
        if path.is_file():
            text = path.read_text(encoding='utf-8', errors='replace')
            assert 'PRIVATE KEY-----' not in text, path


# ---- the install key ----------------------------------------------------------

class FakeSettings:
    def __init__(self, values=None):
        self.values = dict(values or {'sftp_private_key': '', 'sftp_public_key': ''})
        self.writes = []

    def get(self, scope='global', scope_id=0):
        assert scope == 'global'
        return dict(self.values)

    def set(self, scope='global', scope_id=0, values=None, commit=True):
        assert scope == 'global'
        self.writes.append(dict(values))
        self.values.update({k: v.strip() for k, v in values.items()})
        return dict(self.values)


@pytest.fixture
def keypair():
    pytest.importorskip('cryptography')
    return _load('keypair')


def test_ensure_keypair_generates_once_and_returns_only_the_public_half(keypair, caplog):
    caplog.set_level('DEBUG')
    settings = FakeSettings()
    public = keypair.ensure_keypair(settings)
    assert public.startswith('ssh-ed25519 ')
    private = settings.values['sftp_private_key']
    assert private.startswith('-----BEGIN OPENSSH PRIVATE KEY-----')
    assert settings.values['sftp_public_key'] == public
    assert private not in public and 'PRIVATE' not in public
    body = private.splitlines()[1]
    assert body not in caplog.text and 'PRIVATE KEY' not in caplog.text

    again = keypair.ensure_keypair(settings)
    assert again == public
    assert len(settings.writes) == 1
    assert settings.values['sftp_private_key'] == private


def test_the_public_key_belongs_to_the_stored_private_key(keypair):
    from cryptography.hazmat.primitives import serialization
    settings = FakeSettings()
    public = keypair.ensure_keypair(settings)
    loaded = serialization.load_ssh_private_key(settings.values['sftp_private_key'].encode(), None)
    derived = loaded.public_key().public_bytes(serialization.Encoding.OpenSSH,
                                               serialization.PublicFormat.OpenSSH).decode()
    assert public.split()[:2] == derived.split()[:2]


def test_a_missing_public_half_is_derived_not_regenerated(keypair):
    settings = FakeSettings()
    public = keypair.ensure_keypair(settings)
    private = settings.values['sftp_private_key']
    settings.values['sftp_public_key'] = ''
    assert keypair.ensure_keypair(settings) == public
    assert settings.values['sftp_private_key'] == private


def test_an_unreadable_stored_key_is_an_error_without_the_key_in_it(keypair):
    settings = FakeSettings({'sftp_private_key': FAKE_PRIVATE, 'sftp_public_key': ''})
    with pytest.raises(ValueError) as excinfo:
        keypair.ensure_keypair(settings)
    assert 'b3BlbnNzaC1rZXktdjE' not in str(excinfo.value)
    assert settings.writes == []


# ---- the addon inside qlsm ------------------------------------------------------

def test_manifest_validates(app):
    from ui.addons import get_addon
    from ui.addons.manifest import read_manifest

    manifest, errors = read_manifest(str(ADDON_DIR))
    assert errors == []
    assert manifest['id'] == 'file-forwarder'
    assert manifest['version'] == '1.2.0'
    assert manifest['scopes'] == ['global', 'host']
    assert manifest['depends'] == []
    raw = json.loads((ADDON_DIR / 'qlsm-addon.json').read_text(encoding='utf-8'))
    assert 'depends' not in raw
    fields = {f['key']: f for f in manifest['settings']['global']}
    assert set(fields) == {'vps_host', 'retention_days', 'max_raw_mb_per_run', 'interval_minutes',
                           'patterns', 'sftp_private_key', 'sftp_public_key', 'vps_known_hosts'}
    assert fields['sftp_private_key']['type'] == 'secret'
    assert fields['vps_known_hosts']['type'] == 'string'
    assert fields['vps_known_hosts']['label'] == 'internal: pinned VPS host keys'
    assert 'default' not in fields['vps_host']
    for key in DEFAULTS:
        if key != 'vps_host':
            assert fields[key]['default'] == DEFAULTS[key]
    form = raw['ui']['panels']['global_settings']
    assert form['status'] == {'load': 'GET settings/status'}
    form_fields = {f['key']: f for f in form['fields']}
    assert 'default' not in form_fields['vps_host']
    assert form_fields['rescan_keys']['type'] == 'bool'
    assert form_fields['rescan_keys']['label'] == 'Re-scan host keys'
    assert form_fields['rescan_keys']['description']
    host_fields = {f['key']: f for f in manifest['settings']['host']}
    assert host_fields['enabled']['type'] == 'bool'
    with app.app_context():
        addon = get_addon('file-forwarder', app)
        assert addon.loaded, addon.errors
        assert addon.errors == []


def _route_exists(app, method, path):
    adapter = app.url_map.bind('localhost')
    try:
        adapter.match(f'{API}/{path}', method=method)
        return True
    except Exception:
        return False


def test_ui_block_mounts_and_every_route_exists(app):
    raw = json.loads((ADDON_DIR / 'qlsm-addon.json').read_text(encoding='utf-8'))
    ui = raw['ui']
    panels = ui['panels']
    assert all(panel['kind'] in ('form', 'table') for panel in panels.values())

    # One host menu entry: the addon's own dialog (needs ui_api 3).
    assert len(ui['host_menu']) == 1
    host_entry = ui['host_menu'][0]
    assert host_entry['component'] == 'HostPanel.js' and host_entry['renders'] == 'modal'
    assert raw['ui_api'] >= 3

    for entry in ui['host_menu'] + ui['settings_section']:
        if 'component' in entry:
            assert 'panel' not in entry
            assert (ADDON_DIR / 'ui' / entry['component']).is_file(), entry['component']
        else:
            assert entry['panel'] in panels

    host_js = (ADDON_DIR / 'ui' / 'HostPanel.js').read_text(encoding='utf-8')
    for action in ('apply', 'sync', 'purge'):
        assert f"id: '{action}'" in host_js, action
    confirm = host_js.split('PURGE_CONFIRM =', 1)[1].split(';', 1)[0].lower()
    assert 'delete' in confirm and 'host' in confirm
    assert 'confirm: PURGE_CONFIRM' in host_js
    # No Tailwind and no wide content: the table is fixed-layout and wraps.
    assert "tableLayout: 'fixed'" in host_js and 'className' not in host_js

    key_js = (ADDON_DIR / 'ui' / 'PublicKey.js').read_text(encoding='utf-8')
    assert "'public-key'" in key_js and "overflowWrap: 'anywhere'" in key_js

    # Routes the components call (hosts/${hostId}/<action> in HostPanel.js).
    routes = ['GET hosts/1', 'PUT hosts/1', 'GET hosts/1/status', 'POST hosts/1/apply',
              'POST hosts/1/sync', 'POST hosts/1/purge', 'GET public-key']
    for panel in panels.values():
        routes += [panel[k] for k in ('load', 'submit') if k in panel]
        if 'status' in panel:
            routes.append(panel['status']['load'])
    for route in routes:
        method, _, path = route.partition(' ')
        assert _route_exists(app, method, path), route


# ---- helpers for the app tests ---------------------------------------------------

@pytest.fixture
def auth(app):
    from conftest import auth_headers, make_user
    make_user(app, 'ffop', 'pw')
    return auth_headers(app, 'ffop')


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
    return get_addon('file-forwarder', app).ctx


def _enable(app, host_id=None, host_enabled=True, global_enabled=True):
    with app.app_context():
        settings = _ctx(app).settings
        settings.set_enabled('global', 0, global_enabled)
        if host_id is not None:
            settings.set('host', host_id, {'enabled': host_enabled})


def _configure(app, host=VPS, known_hosts=KNOWN_HOSTS):
    """The VPS address and its scanned keys, as a save of the settings form leaves them."""
    with app.app_context():
        _ctx(app).settings.set('global', 0, {'vps_host': host, 'vps_known_hosts': known_hosts})


def _private(app):
    with app.app_context():
        return _ctx(app).settings.get('global', 0)['sftp_private_key']


class FakePlaybook:
    def __init__(self, success=True, stdout='', stderr=''):
        self.calls = []
        self.result = (success, stdout, stderr)
        self.key_file_contents = []

    def __call__(self, host, name, extravars=None):
        self.calls.append((host.id, name, dict(extravars or {})))
        path = (extravars or {}).get('ff_private_key_file')
        if path:
            self.key_file_contents.append(Path(path).read_text(encoding='utf-8'))
        return self.result


def _assert_no_private(text, private):
    assert private
    assert private.splitlines()[1] not in text
    assert 'PRIVATE KEY' not in text


# ---- routes ---------------------------------------------------------------------

@pytest.mark.parametrize('method, path', [
    ('GET', 'public-key'),
    ('GET', 'settings'),
    ('PUT', 'settings'),
    ('GET', 'settings/status'),
    ('GET', 'hosts/1'),
    ('PUT', 'hosts/1'),
    ('GET', 'hosts/1/status'),
    ('POST', 'hosts/1/apply'),
    ('POST', 'hosts/1/sync'),
    ('POST', 'hosts/1/purge'),
])
def test_every_route_needs_a_logged_in_operator(client, method, path):
    assert client.open(f'{API}/{path}', method=method, json={}).status_code == 401


def test_public_key_route_returns_only_the_public_half(app, client, auth, caplog):
    caplog.set_level('DEBUG')
    response = client.get(f'{API}/public-key', headers=auth)
    assert response.status_code == 200
    data = response.get_json()['data']
    assert data['public_key'].startswith('ssh-ed25519 ')
    assert data['keys'][0]['public_key'] == data['public_key']
    assert client.get(f'{API}/public-key', headers=auth).get_json()['data']['public_key'] == data['public_key']
    private = _private(app)
    _assert_no_private(response.get_data(as_text=True), private)
    _assert_no_private(caplog.text, private)


def test_settings_route_shows_the_editable_values_without_keys(app, client, auth):
    client.get(f'{API}/public-key', headers=auth)
    data = client.get(f'{API}/settings', headers=auth).get_json()['data']
    assert data == DEFAULTS


class FakeScan:
    """Stands in for hostkeys.scan: ssh-keyscan never runs in the tests."""

    def __init__(self, error=None):
        self.hosts = []
        self.error = error

    def __call__(self, host, timeout=10):
        self.hosts.append(host)
        if self.error:
            raise self.error
        return KNOWN_HOSTS.replace(VPS, host)


@pytest.fixture
def scan(app, monkeypatch):
    fake = FakeScan()
    monkeypatch.setattr(_backend().hostkeys, 'scan', fake)
    return fake


def _stored(app):
    with app.app_context():
        return _ctx(app).settings.get('global', 0)


def test_settings_route_stores_valid_values(app, client, auth, scan):
    response = client.put(f'{API}/settings', headers=auth, json=dict(
        VALID, retention_days='7', patterns='*.dm_91 raw expire\n*.qlmatch qlmatch keep'))
    assert response.status_code == 200, response.get_json()
    stored = _stored(app)
    assert stored['retention_days'] == '7'
    assert stored['patterns'] == '*.dm_91 raw expire; *.qlmatch qlmatch keep'


@pytest.mark.parametrize('body', [
    dict(VALID, patterns='*.dm_91 ../x expire'),
    dict(VALID, retention_days='soon'),
    dict(VALID, vps_host=''),
    dict(VALID, sftp_private_key='x'),
    dict(VALID, sftp_public_key='x'),
    dict(VALID, vps_known_hosts=ED25519_LINE),
    dict(VALID, rescan_keys='yes'),
    dict(VALID, unknown='x'),
])
def test_settings_route_refuses_bad_input_and_key_fields(app, client, auth, scan, body):
    response = client.put(f'{API}/settings', headers=auth, json=body)
    assert response.status_code == 400
    assert scan.hosts == []
    stored = _stored(app)
    assert stored['patterns'] == DEFAULTS['patterns']
    assert stored['vps_known_hosts'] == ''


def test_put_settings_new_address_scans_and_stores_keys(app, client, auth, scan):
    response = client.put(f'{API}/settings', headers=auth, json=dict(VALID, rescan_keys=False))
    assert response.status_code == 200, response.get_json()
    body = response.get_json()
    assert body['data']['fingerprints'] == [ED25519_FP, body['data']['fingerprints'][1]]
    assert 'vps_known_hosts' not in body['data']
    assert ED25519_FP in body['message']
    assert scan.hosts == [VPS]
    stored = _stored(app)
    assert stored['vps_host'] == VPS
    assert stored['vps_known_hosts'] == KNOWN_HOSTS.strip()
    # The form never shows the stored keys.
    assert 'vps_known_hosts' not in client.get(f'{API}/settings', headers=auth).get_json()['data']


def test_put_settings_same_address_does_not_rescan(app, client, auth, scan):
    assert client.put(f'{API}/settings', headers=auth, json=VALID).status_code == 200
    response = client.put(f'{API}/settings', headers=auth, json=dict(VALID, retention_days='3',
                                                                   rescan_keys=False))
    assert response.status_code == 200, response.get_json()
    assert response.get_json()['data']['fingerprints'][0] == ED25519_FP
    assert scan.hosts == [VPS]
    assert _stored(app)['retention_days'] == '3'


def test_put_settings_new_address_rescans(app, client, auth, scan):
    assert client.put(f'{API}/settings', headers=auth, json=VALID).status_code == 200
    assert client.put(f'{API}/settings', headers=auth, json=dict(VALID, vps_host='10.0.0.9')).status_code == 200
    assert scan.hosts == [VPS, '10.0.0.9']
    assert _stored(app)['vps_known_hosts'].startswith('10.0.0.9 ssh-ed25519 ')


def test_put_settings_rescan_keys_rescans(app, client, auth, scan):
    assert client.put(f'{API}/settings', headers=auth, json=VALID).status_code == 200
    assert client.put(f'{API}/settings', headers=auth, json=dict(VALID, rescan_keys=True)).status_code == 200
    assert scan.hosts == [VPS, VPS]


def test_put_settings_scan_failure_saves_nothing(app, client, auth, monkeypatch):
    error = _backend().hostkeys.HostKeyScanError('ssh-keyscan timed out')
    monkeypatch.setattr(_backend().hostkeys, 'scan', FakeScan(error=error))
    before = _stored(app)
    response = client.put(f'{API}/settings', headers=auth, json=dict(VALID, retention_days='3'))
    assert response.status_code == 409
    message = response.get_json()['error']['message']
    assert 'could not reach' in message and VPS in message and 'timed out' in message
    assert _stored(app) == before


def test_settings_status_reports_the_pinned_keys(app, client, auth, scan):
    data = client.get(f'{API}/settings/status', headers=auth).get_json()['data']
    assert data == {'ok': False, 'label': 'VPS address or host keys not set'}
    client.put(f'{API}/settings', headers=auth, json=VALID)
    data = client.get(f'{API}/settings/status', headers=auth).get_json()['data']
    assert data['ok'] is True
    assert data['label'].startswith(f'Host keys pinned: {ED25519_FP}, ECDSA SHA256:')


def test_host_switch_round_trips(app, client, auth):
    host_id = _host(app)
    assert client.get(f'{API}/hosts/{host_id}', headers=auth).get_json()['data'] == {'enabled': True}
    assert client.put(f'{API}/hosts/{host_id}', headers=auth, json={'enabled': False}).status_code == 200
    assert client.get(f'{API}/hosts/{host_id}', headers=auth).get_json()['data'] == {'enabled': False}
    assert client.get(f'{API}/hosts/9999', headers=auth).status_code == 404


STATUS_STDOUT = '''
TASK [report] ******
ok: [game-1] => {
    "msg": [
        "FF_VERSION=1.2.0",
        "FF_TIMER=active",
        "FF_LAST_RUN=time=2026-10-11T10:00:00Z mode=run uploaded=3 failed=0 deleted=1 kept_unconfirmed=0 exit=0"
    ]
}
leaked: -----BEGIN OPENSSH PRIVATE KEY----- b3BlbnNzaC1rZXktdjEAAAAABG5vbmU
'''


def test_status_is_parsed_from_the_playbook_and_carries_no_key(app, client, auth, monkeypatch):
    host_id = _host(app)
    client.get(f'{API}/public-key', headers=auth)
    fake = FakePlaybook(stdout=STATUS_STDOUT + _private(app))
    monkeypatch.setattr(_ctx(app), 'run_playbook', fake)
    response = client.get(f'{API}/hosts/{host_id}/status', headers=auth)
    assert response.status_code == 200
    data = response.get_json()['data']
    assert data['version'] == '1.2.0'
    assert data['timer_active'] is True
    assert data['up_to_date'] is True
    assert data['last_run'].startswith('time=2026-10-11T10:00:00Z mode=run uploaded=3')
    assert len(data['rows']) == 1
    assert fake.calls == [(host_id, 'status_file_forwarder.yml', {})]
    _assert_no_private(response.get_data(as_text=True), _private(app))


def test_status_of_an_old_or_missing_install(app, client, auth, monkeypatch):
    host_id = _host(app)
    monkeypatch.setattr(_ctx(app), 'run_playbook', FakePlaybook(stdout='"FF_VERSION=0.9.0"\n"FF_TIMER=inactive"'))
    data = client.get(f'{API}/hosts/{host_id}/status', headers=auth).get_json()['data']
    assert data['up_to_date'] is False and data['timer_active'] is False and data['last_run'] is None

    monkeypatch.setattr(_ctx(app), 'run_playbook', FakePlaybook(success=False, stderr='unreachable'))
    response = client.get(f'{API}/hosts/{host_id}/status', headers=auth)
    assert response.status_code == 200
    data = response.get_json()['data']
    assert data['version'] is None and data['up_to_date'] is False
    assert len(data['rows']) == 1  # the actions stay reachable
    assert client.get(f'{API}/hosts/9999/status', headers=auth).status_code == 404


# ---- payload sync and the apply task ----------------------------------------------

def _payload_sync(app, host_id):
    from ui.addons import dispatch
    with app.app_context():
        dispatch('host.payload_sync', host_id, host_id)


def test_payload_sync_skips_a_disabled_host(app, monkeypatch):
    host_id = _host(app)
    _enable(app, host_id, host_enabled=False)
    fake = FakePlaybook()
    monkeypatch.setattr(_ctx(app), 'run_playbook', fake)
    _payload_sync(app, host_id)
    assert fake.calls == []


def test_payload_sync_skips_when_the_addon_is_off(app, monkeypatch):
    host_id = _host(app)
    _enable(app, host_id, global_enabled=False)
    fake = FakePlaybook()
    monkeypatch.setattr(_ctx(app), 'run_playbook', fake)
    _payload_sync(app, host_id)
    assert fake.calls == []


def test_payload_sync_deploys_an_enabled_host_with_the_key_in_a_file(app, monkeypatch, caplog):
    caplog.set_level('DEBUG')
    host_id = _host(app)
    _enable(app, host_id)
    _configure(app)
    fake = FakePlaybook()
    monkeypatch.setattr(_ctx(app), 'run_playbook', fake)
    _payload_sync(app, host_id)

    assert len(fake.calls) == 1
    called_host, name, extravars = fake.calls[0]
    assert (called_host, name) == (host_id, 'sync_file_forwarder.yml')
    private = _private(app)
    assert 'ff_private_key' not in extravars
    _assert_no_private(json.dumps(extravars), private)
    assert fake.key_file_contents == [private + '\n']
    assert not os.path.exists(extravars['ff_private_key_file'])
    assert extravars['ff_version'] == '1.2.0'
    assert extravars['ff_known_hosts'] == KNOWN_HOSTS
    assert extravars['ff_vps_host'] == VPS
    assert "RETENTION_DAYS='14'" in extravars['ff_conf_text']
    _assert_no_private(caplog.text, private)


def test_payload_sync_with_bad_settings_runs_nothing(app, monkeypatch):
    host_id = _host(app)
    _enable(app, host_id)
    with app.app_context():
        _ctx(app).settings.set('global', 0, {'patterns': '*.dm_91 ../x expire'})
    fake = FakePlaybook()
    monkeypatch.setattr(_ctx(app), 'run_playbook', fake)
    _payload_sync(app, host_id)
    assert fake.calls == []


def _backend():
    return sys.modules[MODULE]


def test_apply_logic_runs_the_sync_playbook(app, monkeypatch):
    host_id = _host(app)
    _enable(app, host_id)
    _configure(app)
    fake = FakePlaybook()
    monkeypatch.setattr(_ctx(app), 'run_playbook', fake)
    with app.app_context():
        result = _backend().apply_host(host_id)
    assert result['success'] is True
    assert [c[1] for c in fake.calls] == ['sync_file_forwarder.yml']


RUN_STDOUT = '''
ok: [game-1] => {
    "msg": [
        "[forwarder] uploaded a.qlmatch -> qlmatch/",
        "[forwarder] time=2026-10-11T10:05:00Z mode=purge uploaded=1 failed=0 deleted=4 kept_unconfirmed=0 exit=0"
    ]
}
'''


@pytest.mark.parametrize('purge, mode', [(False, 'run'), (True, 'purge')])
def test_sync_logic_runs_the_forwarder_and_returns_its_summary(app, monkeypatch, purge, mode):
    host_id = _host(app)
    fake = FakePlaybook(stdout=RUN_STDOUT)
    monkeypatch.setattr(_ctx(app), 'run_playbook', fake)
    with app.app_context():
        summary = _backend().sync_host(host_id, purge=purge)
    assert fake.calls == [(host_id, 'run_forwarder.yml', {'ff_mode': mode})]
    assert summary == ('time=2026-10-11T10:05:00Z mode=purge uploaded=1 failed=0 '
                       'deleted=4 kept_unconfirmed=0 exit=0')


def test_sync_logic_reports_a_failed_run(app, monkeypatch):
    host_id = _host(app)
    monkeypatch.setattr(_ctx(app), 'run_playbook', FakePlaybook(success=False, stderr='boom'))
    with app.app_context():
        summary = _backend().sync_host(host_id)
    assert summary.startswith('failed')


# ---- enqueueing ---------------------------------------------------------------------

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


@pytest.mark.parametrize('action, purge', [('sync', False), ('purge', True)])
def test_sync_and_purge_enqueue_the_sync_task(app, client, auth, queue, action, purge):
    host_id = _host(app)
    response = client.post(f'{API}/hosts/{host_id}/{action}', headers=auth)
    assert response.status_code == 202, response.get_json()
    # The host dialog reads the message from `data`.
    assert 'queued for' in response.get_json()['data']['message']
    assert len(queue) == 1
    name, args, kwargs = queue[0]
    assert name == 'sync_task'
    assert args[0] == host_id
    assert kwargs['purge'] is purge
    assert kwargs['lock_token']


def test_apply_enqueues_the_apply_task(app, client, auth, queue):
    host_id = _host(app)
    _enable(app, host_id)
    _configure(app)
    assert client.post(f'{API}/hosts/{host_id}/apply', headers=auth).status_code == 202
    assert [(c[0], c[1][0]) for c in queue] == [('apply_task', host_id)]


@pytest.mark.parametrize('host, known_hosts', [('', ''), (VPS, ''), ('', KNOWN_HOSTS)])
def test_apply_refuses_without_keys(app, client, auth, queue, monkeypatch, host, known_hosts):
    host_id = _host(app)
    _enable(app, host_id)
    _configure(app, host, known_hosts)
    response = client.post(f'{API}/hosts/{host_id}/apply', headers=auth)
    assert response.status_code == 409
    message = response.get_json()['error']['message']
    assert 'Settings -> ' in message and 'File Forwarder' in message
    assert queue == []

    # The task (and host setup) refuse the same way without running anything.
    fake = FakePlaybook()
    monkeypatch.setattr(_ctx(app), 'run_playbook', fake)
    with app.app_context():
        result = _backend().apply_host(host_id)
    assert result['success'] is False and 'File Forwarder' in result['message']
    assert fake.calls == []


def test_apply_refuses_a_disabled_host(app, client, auth, queue):
    host_id = _host(app)
    _enable(app, host_id, host_enabled=False)
    assert client.post(f'{API}/hosts/{host_id}/apply', headers=auth).status_code == 409
    assert queue == []


def test_a_busy_host_gets_409(app, client, auth, monkeypatch):
    import ui.task_lock
    monkeypatch.setattr(ui.task_lock, 'acquire_lock', lambda *a, **k: False)
    host_id = _host(app)
    assert client.post(f'{API}/hosts/{host_id}/sync', headers=auth).status_code == 409


def test_actions_on_an_unknown_host_are_404(client, auth, queue):
    for action in ('apply', 'sync', 'purge'):
        assert client.post(f'{API}/hosts/9999/{action}', headers=auth).status_code == 404
    assert queue == []
