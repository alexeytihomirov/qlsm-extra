import importlib
import importlib.machinery
import importlib.util
import sys
from pathlib import Path
from unittest.mock import Mock

ADDON_DIR = Path(__file__).resolve().parent.parent / 'addons' / 'player-ranks'

# server_cfg.py does `from .cvar_text import ...` -- a relative import that
# needs a real package context to resolve, unlike the leaf modules (cache,
# steam_ids) imported elsewhere in this suite via a bare sys.path insert.
# This mirrors how qlsm's own registry.py loads an addon (a namespace
# package rooted at the addon's directory), without touching backend.py
# (which needs Flask/ui and is exercised by the full-app tests instead).
_PKG_NAME = 'player_ranks_addon_under_test'
if _PKG_NAME not in sys.modules:
    _spec = importlib.machinery.ModuleSpec(_PKG_NAME, loader=None, is_package=True)
    _spec.submodule_search_locations = [str(ADDON_DIR)]
    sys.modules[_PKG_NAME] = importlib.util.module_from_spec(_spec)

suggest_from_server_cfg = importlib.import_module(f'{_PKG_NAME}.server_cfg').suggest_from_server_cfg


def _instance(host_name, instance_id):
    instance = Mock()
    instance.host = Mock()
    instance.host.name = host_name
    instance.id = instance_id
    return instance


def test_no_host_means_no_suggestion():
    instance = Mock()
    instance.host = None
    assert suggest_from_server_cfg(instance) == {}


def test_missing_server_cfg_means_no_suggestion(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    instance = _instance('germany', 42)
    assert suggest_from_server_cfg(instance) == {}


def test_elo_service_cvars_are_suggested(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg_dir = tmp_path / 'configs' / 'germany' / '42'
    cfg_dir.mkdir(parents=True)
    (cfg_dir / 'server.cfg').write_text(
        'set qlx_rankedServiceUrl "http://localhost:5002"\n'
        'set qlx_rankedApiKey "secret-key"\n'
        'set qlx_rankedPool "ffa_auto"\n',
        encoding='utf-8',
    )
    instance = _instance('germany', 42)

    result = suggest_from_server_cfg(instance)

    assert result == {
        'elo_service_enabled': True,
        'elo_service_base_url': 'http://localhost:5002',
        'elo_service_api_key': 'secret-key',
        'elo_service_game_type': 'ffa_auto',
    }


def test_qlstats_cvars_are_suggested_when_no_elo_service(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg_dir = tmp_path / 'configs' / 'germany' / '42'
    cfg_dir.mkdir(parents=True)
    (cfg_dir / 'server.cfg').write_text(
        'set qlx_balanceUrl "qlstats.net"\n'
        'set qlx_balanceApi "elo_b"\n',
        encoding='utf-8',
    )
    instance = _instance('germany', 42)

    result = suggest_from_server_cfg(instance)

    assert result == {
        'qlstats_enabled': True,
        'qlstats_base_url': 'http://qlstats.net',
        'qlstats_rating_system': 'elo_b',
    }


def test_qlstats_url_already_has_scheme_is_left_alone(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg_dir = tmp_path / 'configs' / 'germany' / '42'
    cfg_dir.mkdir(parents=True)
    (cfg_dir / 'server.cfg').write_text(
        'set qlx_balanceUrl "https://qlstats.net"\n',
        encoding='utf-8',
    )
    instance = _instance('germany', 42)

    result = suggest_from_server_cfg(instance)

    assert result['qlstats_base_url'] == 'https://qlstats.net'


def test_no_recognised_cvars_means_no_suggestion(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg_dir = tmp_path / 'configs' / 'germany' / '42'
    cfg_dir.mkdir(parents=True)
    (cfg_dir / 'server.cfg').write_text('set sv_hostname "test"\n', encoding='utf-8')
    instance = _instance('germany', 42)

    assert suggest_from_server_cfg(instance) == {}
