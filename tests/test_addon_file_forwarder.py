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
    'vps_host': '70.34.223.191',
    'retention_days': '14',
    'max_raw_mb_per_run': '2048',
    'interval_minutes': '10',
    'patterns': '*.qlmatch qlmatch keep; *.replay.json.gz qlmatch keep; *.dm_91 raw expire',
}
FAKE_PRIVATE = ('-----BEGIN OPENSSH PRIVATE KEY-----\n'
                'b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAABAAAAMwAAAAtzc2gtZW\n'
                '-----END OPENSSH PRIVATE KEY-----')
PRIVATE_MARKERS = ('PRIVATE KEY', 'b3BlbnNzaC1rZXktdjE')


# ---- config rendering (pure, no qlsm needed) ----------------------------------

SH = shutil.which('sh')


@pytest.mark.standalone
@pytest.mark.skipif(SH is None, reason='no sh on PATH')
def test_rendered_conf_sourced_by_sh_gives_the_forwarder_variables(render, tmp_path):
    conf = tmp_path / 'forwarder.conf'
    conf.write_text(render.render_conf(DEFAULTS), encoding='utf-8', newline='\n')
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
    text = render.render_conf(render.DEFAULTS)
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
    text = render.render_conf(dict(DEFAULTS, retention_days=7, max_raw_mb_per_run=100, interval_minutes=5))
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
        render.render_conf(dict(DEFAULTS, **{key: value}))


@pytest.mark.standalone
def test_playbook_vars(render):
    variables = render.playbook_vars(dict(DEFAULTS, sftp_private_key=FAKE_PRIVATE,
                                          sftp_public_key='ssh-ed25519 AAAA x'))
    assert set(variables) >= {'ff_conf_text', 'ff_private_key', 'ff_known_hosts',
                              'ff_version', 'ff_interval_minutes'}
    assert variables['ff_private_key'] == FAKE_PRIVATE + '\n'
    assert variables['ff_conf_text'] == render.render_conf(DEFAULTS)
    assert variables['ff_version'] == '1.0.0'
    assert variables['ff_interval_minutes'] == 10
    assert variables['ff_vps_host'] == '70.34.223.191'
    assert variables['ff_sftp_user'] == 'qldemos-in'
    assert variables['ff_remote_name'] == 'qldemos'
    known = variables['ff_known_hosts']
    assert known.endswith('\n')
    lines = [line for line in known.splitlines() if line and not line.startswith('#')]
    assert [line.split()[:2] for line in lines] == [
        ['70.34.223.191', 'ssh-ed25519'], ['70.34.223.191', 'ssh-rsa'],
        ['70.34.223.191', 'ecdsa-sha2-nistp256']]


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
    assert manifest['version'] == '1.0.0'
    assert manifest['scopes'] == ['global', 'host']
    assert manifest['depends'] == []
    raw = json.loads((ADDON_DIR / 'qlsm-addon.json').read_text(encoding='utf-8'))
    assert 'depends' not in raw
    fields = {f['key']: f for f in manifest['settings']['global']}
    assert set(fields) == {'vps_host', 'retention_days', 'max_raw_mb_per_run', 'interval_minutes',
                           'patterns', 'sftp_private_key', 'sftp_public_key'}
    assert fields['sftp_private_key']['type'] == 'secret'
    for key in DEFAULTS:
        assert fields[key]['default'] == DEFAULTS[key]
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


def test_ui_block_is_tier1_and_every_route_exists(app):
    raw = json.loads((ADDON_DIR / 'qlsm-addon.json').read_text(encoding='utf-8'))
    ui = raw['ui']
    panels = ui['panels']
    assert all(panel['kind'] in ('form', 'table') for panel in panels.values())
    for mount in ('host_menu', 'settings_section'):
        for entry in ui[mount]:
            assert 'component' not in entry and entry['panel'] in panels
    actions = {}
    for entry in ui['host_menu']:
        for action in panels[entry['panel']].get('row_actions', []):
            actions[action['id']] = action
    assert {'apply', 'sync', 'purge'} <= set(actions)
    confirm = actions['purge']['confirm'].lower()
    assert 'delete' in confirm and 'host' in confirm
    routes = []
    for panel in panels.values():
        routes += [panel[k] for k in ('load', 'submit') if k in panel]
        routes += [a['route'] for a in panel.get('row_actions', [])]
    assert routes
    for route in routes:
        method, _, path = route.partition(' ')
        path = path.replace('{host_id}', '1')
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


def test_settings_route_stores_valid_values(app, client, auth):
    response = client.put(f'{API}/settings', headers=auth, json=dict(
        DEFAULTS, retention_days='7', patterns='*.dm_91 raw expire\n*.qlmatch qlmatch keep'))
    assert response.status_code == 200, response.get_json()
    with app.app_context():
        stored = _ctx(app).settings.get('global', 0)
    assert stored['retention_days'] == '7'
    assert stored['patterns'] == '*.dm_91 raw expire; *.qlmatch qlmatch keep'


@pytest.mark.parametrize('body', [
    dict(DEFAULTS, patterns='*.dm_91 ../x expire'),
    dict(DEFAULTS, retention_days='soon'),
    dict(DEFAULTS, sftp_private_key='x'),
    dict(DEFAULTS, sftp_public_key='x'),
    dict(DEFAULTS, unknown='x'),
])
def test_settings_route_refuses_bad_input_and_key_fields(app, client, auth, body):
    response = client.put(f'{API}/settings', headers=auth, json=body)
    assert response.status_code == 400
    with app.app_context():
        assert _ctx(app).settings.get('global', 0)['patterns'] == DEFAULTS['patterns']


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
        "FF_VERSION=1.0.0",
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
    assert data['version'] == '1.0.0'
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
    assert extravars['ff_version'] == '1.0.0'
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
    assert len(queue) == 1
    name, args, kwargs = queue[0]
    assert name == 'sync_task'
    assert args[0] == host_id
    assert kwargs['purge'] is purge
    assert kwargs['lock_token']


def test_apply_enqueues_the_apply_task(app, client, auth, queue):
    host_id = _host(app)
    _enable(app, host_id)
    assert client.post(f'{API}/hosts/{host_id}/apply', headers=auth).status_code == 202
    assert [(c[0], c[1][0]) for c in queue] == [('apply_task', host_id)]


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
