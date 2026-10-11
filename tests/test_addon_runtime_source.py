"""The runtime-source addon: a per-host minqlxtended repository, delivered to
setup_host.yml through the host.setup hook.

What matters here is what reaches the playbook. A source that does not
validate must contribute nothing at all, because whatever this addon returns
is handed to `git clone` on the host.
"""
import importlib.util
from pathlib import Path

import pytest

from ui import db
from ui.addons import dispatch, get_addon
from ui.models import Host, HostStatus
from conftest import auth_headers, make_user

ADDON = '/api/addons/runtime-source'
REPO = 'https://github.com/someone/minqlxtended.git'
SHA = 'd0719268d4aa4d9c0f2f05c9524f2a87fa733bc5'
BACKEND = Path(__file__).resolve().parent.parent / 'addons' / 'runtime-source' / 'backend.py'


@pytest.fixture
def addon_id():
    return 'runtime-source'


@pytest.fixture
def resolve_source():
    spec = importlib.util.spec_from_file_location('runtime_source_backend', BACKEND)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.resolve_source


@pytest.fixture
def auth(app):
    make_user(app, 'srcop', 'pw')
    return auth_headers(app, 'srcop')


def _host(app, name, runtime):
    with app.app_context():
        host = Host(name=name, ip_address='10.0.0.1', provider='standalone',
                    runtime=runtime, status=HostStatus.ACTIVE)
        db.session.add(host)
        db.session.commit()
        return host.id


def _configure(app, host_id, enabled=True, **values):
    with app.app_context():
        settings = get_addon('runtime-source', app).ctx.settings
        settings.set_enabled('global', 0, True)
        settings.set_enabled('host', host_id, enabled)
        if values:
            settings.set('host', host_id, values)


def _contributions(app, host_id):
    with app.app_context():
        return [r for r in (dispatch('host.setup', host_id, host_id) or []) if r]


# ---- validation ------------------------------------------------------------

def test_blank_means_the_pinned_build(resolve_source):
    assert resolve_source({}) == ({}, None)
    assert resolve_source({'git_repo': ' ', 'git_version': None}) == ({}, None)


@pytest.mark.parametrize('version', [SHA, 'v1.2.3', 'main', 'feature/demo-cut'])
def test_a_valid_pair_becomes_the_two_playbook_vars(resolve_source, version):
    assert resolve_source({'git_repo': f' {REPO} ', 'git_version': f' {version} '}) == (
        {'minqlxtended_git_repo': REPO, 'minqlxtended_git_version': version}, None)


@pytest.mark.parametrize('settings', [
    {'git_repo': REPO},
    {'git_version': SHA},
    {'git_repo': 'http://github.com/a/b.git', 'git_version': SHA},
    {'git_repo': 'git@github.com:a/b.git', 'git_version': SHA},
    {'git_repo': 'file:///etc/passwd', 'git_version': SHA},
    {'git_repo': 'https://user:token@github.com/a/b.git', 'git_version': SHA},
    {'git_repo': 'https://github.com/a/b.git?x=1', 'git_version': SHA},
    {'git_repo': '--upload-pack=touch /tmp/x', 'git_version': SHA},
    {'git_repo': 'https://github.com/' + 'a' * 250, 'git_version': SHA},
    {'git_repo': REPO, 'git_version': '--force'},
    {'git_repo': REPO, 'git_version': 'main..other'},
    {'git_repo': REPO, 'git_version': 'a b'},
    {'git_repo': REPO, 'git_version': '$(id)'},
    {'git_repo': REPO, 'git_version': 'a' * 101},
])
def test_an_unusable_source_contributes_nothing(resolve_source, settings):
    extra_vars, problem = resolve_source(settings)
    assert extra_vars == {}
    assert problem


# ---- the hook --------------------------------------------------------------

def test_an_enabled_minqlxtended_host_gets_its_source(app):
    host_id = _host(app, 'fork-host', 'minqlxtended')
    _configure(app, host_id, git_repo=REPO, git_version=SHA)
    assert _contributions(app, host_id) == [
        {'minqlxtended_git_repo': REPO, 'minqlxtended_git_version': SHA}]


def test_a_host_the_addon_is_off_for_gets_nothing(app):
    host_id = _host(app, 'off-host', 'minqlxtended')
    _configure(app, host_id, enabled=False, git_repo=REPO, git_version=SHA)
    assert _contributions(app, host_id) == []


def test_a_minqlx_host_gets_nothing(app):
    host_id = _host(app, 'minqlx-host', 'minqlx')
    _configure(app, host_id, git_repo=REPO, git_version=SHA)
    assert _contributions(app, host_id) == []


def test_a_malformed_source_gets_nothing(app):
    host_id = _host(app, 'bad-host', 'minqlxtended')
    _configure(app, host_id, git_repo='git@github.com:a/b.git', git_version=SHA)
    assert _contributions(app, host_id) == []


# ---- the status badge --------------------------------------------------------

def test_status_requires_auth(app, client):
    host_id = _host(app, 'auth-host', 'minqlxtended')
    assert client.get(f'{ADDON}/hosts/{host_id}/status').status_code == 401


def test_status_of_an_unknown_host_is_404(client, auth):
    assert client.get(f'{ADDON}/hosts/9999/status', headers=auth).status_code == 404


@pytest.mark.parametrize('runtime, enabled, values, ok, fragment', [
    ('minqlxtended', True, {'git_repo': REPO, 'git_version': SHA}, True, 'Custom source'),
    ('minqlxtended', True, {}, True, 'pinned'),
    ('minqlxtended', False, {'git_repo': REPO, 'git_version': SHA}, False, 'off for this host'),
    ('minqlxtended', True, {'git_repo': REPO}, False, 'needs both'),
    ('minqlx', True, {'git_repo': REPO, 'git_version': SHA}, False, 'minqlx'),
])
def test_status_says_what_the_next_setup_builds(app, client, auth, runtime, enabled,
                                                values, ok, fragment):
    host_id = _host(app, 'status-host', runtime)
    _configure(app, host_id, enabled=enabled, **values)
    data = client.get(f'{ADDON}/hosts/{host_id}/status', headers=auth).get_json()['data']
    assert data['ok'] is ok
    assert fragment in data['label']
