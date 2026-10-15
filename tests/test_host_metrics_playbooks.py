"""Static checks for the host-metrics playbooks, systemd unit and settings.

Nothing here runs Ansible against a host. The syntax-check test runs only when
`ansible-playbook` is on PATH.
"""
import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.standalone

ADDON = Path(__file__).resolve().parent.parent / 'addons' / 'host-metrics'
PLAYBOOKS = ADDON / 'playbooks'
ASSETS = ADDON / 'assets'
NAMES = ('sync_host_metrics.yml', 'status_host_metrics.yml')

GLOBAL_DEFAULTS = {
    'core_saturated_pct': '95', 'steal_event_pct': '10', 'mem_low_pct': '10', 'disk_low_pct': '90',
    'frames_late_pct': '1', 'frame_gap_ms': '100', 'event_window_s': '60',
    'verdict_target_pct': '70', 'mem_reserve_pct': '20', 'steal_tight_pct': '5',
    'steal_overload_pct': '15',
}


def _load(name):
    return yaml.safe_load((PLAYBOOKS / name).read_text(encoding='utf-8'))


def _tasks(name):
    return [task for play in _load(name) for task in play.get('tasks', [])]


def _settings():
    spec = importlib.util.spec_from_file_location('hm_settings_under_test', ADDON / 'settings.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('name', NAMES)
def test_playbook_parses_and_targets_all_hosts(name):
    plays = _load(name)
    assert isinstance(plays, list) and plays
    for play in plays:
        assert play['hosts'] == 'all'
        assert play['become'] is True or play['become'] == 'yes'
        assert play['gather_facts'] is False
        assert play['tasks']


def test_every_copied_asset_exists():
    sync = _load('sync_host_metrics.yml')[0]
    modules = sync['vars']['hm_modules']
    assert set(modules) == {'hm_readers.py', 'hm_store.py', 'hm_events.py', 'hm_collect.py', 'hm_query.py'}
    for module in modules:
        assert (ASSETS / module).is_file(), module
    assert (ASSETS / 'host-metrics.service').is_file()
    text = (PLAYBOOKS / 'sync_host_metrics.yml').read_text(encoding='utf-8')
    assert '{{ playbook_dir }}/../assets/host-metrics.service' in text
    assert '{{ playbook_dir }}/../assets/{{ item }}' in text


def test_sync_paths_owners_and_smoke_check():
    text = (PLAYBOOKS / 'sync_host_metrics.yml').read_text(encoding='utf-8')
    for fragment in ('hm_dir: /home/ql/host-metrics', 'hm_data_dir: /var/lib/host-metrics',
                     'hm_conf_dir: /etc/host-metrics', '{{ hm_version }}', '{{ hm_config_json }}',
                     'sudo -u ql python3 /home/ql/host-metrics/hm_collect.py '
                     '--config /etc/host-metrics/config.json --once --dry-run'):
        assert fragment in text, fragment
    data_dir = next(t for t in _tasks('sync_host_metrics.yml') if t['name'] == 'Create the data directory')
    assert data_dir['file']['owner'] == 'ql' and data_dir['file']['mode'] == '0750'
    enable = next(t for t in _tasks('sync_host_metrics.yml') if t['name'].startswith('Enable'))
    assert enable['systemd']['enabled'] in (True, 'yes') and enable['systemd']['state'] == 'restarted'
    disable = next(t for t in _tasks('sync_host_metrics.yml') if t['name'].startswith('Stop and disable'))
    assert disable['systemd']['state'] == 'stopped' and disable['systemd']['enabled'] in (False, 'no')
    assert not any('absent' in json.dumps(t) for t in _tasks('sync_host_metrics.yml'))  # data is kept


def test_unit_asset():
    service = (ASSETS / 'host-metrics.service').read_text(encoding='utf-8')
    for line in ('User=ql', 'Nice=19', 'CPUWeight=1', 'Restart=always', 'RestartSec=10',
                 'StateDirectory=host-metrics',
                 'ExecStart=/usr/bin/python3 /home/ql/host-metrics/hm_collect.py '
                 '--config /etc/host-metrics/config.json'):
        assert line in service.splitlines(), line


def test_status_prints_three_lines():
    text = (PLAYBOOKS / 'status_host_metrics.yml').read_text(encoding='utf-8')
    for marker in ('HM_VERSION=', 'HM_SERVICE=', 'HM_DB_BYTES='):
        assert marker in text
    assert 'systemctl is-active host-metrics.service' in text
    assert '/home/ql/host-metrics/VERSION' in text
    assert '/var/lib/host-metrics/metrics.db' in text


@pytest.mark.skipif(shutil.which('ansible-playbook') is None, reason='ansible-playbook not installed')
@pytest.mark.parametrize('name', NAMES)
def test_ansible_syntax_check(name):
    result = subprocess.run(['ansible-playbook', '--syntax-check', '-i', 'localhost,', str(PLAYBOOKS / name)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


# ---- settings -----------------------------------------------------------------

def test_manifest_defaults_match_the_constraints():
    manifest = json.loads((ADDON / 'qlsm-addon.json').read_text(encoding='utf-8'))
    fields = {f['key']: f['default'] for f in manifest['settings']['global']}
    assert fields == GLOBAL_DEFAULTS
    assert _settings().DEFAULTS == GLOBAL_DEFAULTS
    panel_fields = {f['key']: f['default'] for f in manifest['ui']['panels']['global_settings']['fields']}
    assert panel_fields == GLOBAL_DEFAULTS


def test_collector_config_defaults():
    config = _settings().collector_config({})
    assert config == {
        'db_path': '/var/lib/host-metrics/metrics.db',
        'redis_socket': '/var/run/redis/redis.sock',
        'redis_db': 1,
        'thresholds': {'core_saturated_pct': 95, 'steal_event_pct': 10, 'mem_low_pct': 10,
                       'disk_low_pct': 90, 'frames_late_pct': 1, 'frame_gap_ms': 100,
                       'event_window_s': 60},
        'version': '1.0.0',
    }
    assert _settings().collector_config(GLOBAL_DEFAULTS) == config


def test_collector_config_keys_are_the_ones_the_collector_reads():
    import sys
    sys.path.insert(0, str(ASSETS))
    try:
        import hm_events
    finally:
        sys.path.remove(str(ASSETS))
    assert set(_settings().collector_config({})['thresholds']) == set(hm_events.DEFAULTS)


def test_verdict_settings_are_numbers_and_not_in_the_config():
    module = _settings()
    assert module.verdict_settings({}) == {'verdict_target_pct': 70.0, 'mem_reserve_pct': 20.0,
                                           'steal_tight_pct': 5.0, 'steal_overload_pct': 15.0}
    assert module.verdict_settings({'verdict_target_pct': '80'})['verdict_target_pct'] == 80.0
    assert not any(k.startswith(('verdict', 'mem_reserve', 'steal_tight', 'steal_overload'))
                   for k in module.collector_config({})['thresholds'])


@pytest.mark.parametrize('key, value', [
    ('core_saturated_pct', 'abc'),
    ('core_saturated_pct', '101'),
    ('core_saturated_pct', '-1'),
    ('core_saturated_pct', '9.5'),
    ('core_saturated_pct', True),
    ('core_saturated_pct', 9.5),
    ('core_saturated_pct', '95; rm -rf /'),
    ('frame_gap_ms', '0'),
    ('frame_gap_ms', '3601'),
    ('event_window_s', '0'),
    ('verdict_target_pct', '150'),
    ('steal_overload_pct', 'x'),
])
def test_a_bad_value_raises_naming_the_field(key, value):
    module = _settings()
    with pytest.raises(ValueError, match=key):
        if key.startswith(('verdict', 'steal_overload')):
            module.verdict_settings({key: value})
        else:
            module.collector_config({key: value})
    with pytest.raises(ValueError, match=key):
        module.validate_settings({key: value})
