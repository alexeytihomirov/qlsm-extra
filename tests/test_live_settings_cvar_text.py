"""live-settings: reading and rewriting `set <cvar> "<value>"` lines in a
server.cfg text. Python port of qlsm's frontend serverCfgCvars.js, so the
addon writes a file the Plugins tab's own cvar form reads back the same way.
"""
import importlib
import importlib.machinery
import importlib.util
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.standalone

ADDON_DIR = Path(__file__).resolve().parent.parent / 'addons' / 'live-settings'
_PKG = 'live_settings_addon_under_test'
if _PKG not in sys.modules:
    _spec = importlib.machinery.ModuleSpec(_PKG, loader=None, is_package=True)
    _spec.submodule_search_locations = [str(ADDON_DIR)]
    sys.modules[_PKG] = importlib.util.module_from_spec(_spec)

cvar_text = importlib.import_module(f'{_PKG}.cvar_text')


CFG = (
    'set sv_hostname "duel"\n'
    'seta g_password frontier // join password\n'
    'set qlx_itemRouletteTakeChance "50"\n'
    '  set qlx_itemRouletteTakeChance "25"\n'
    'set timelimit 15\n'
)


def test_read_takes_the_last_occurrence():
    assert cvar_text.read_cvar(CFG, 'qlx_itemRouletteTakeChance') == '25'


def test_read_handles_unquoted_values_and_seta():
    assert cvar_text.read_cvar(CFG, 'g_password') == 'frontier'
    assert cvar_text.read_cvar(CFG, 'timelimit') == '15'


def test_read_is_case_insensitive_and_none_when_absent():
    assert cvar_text.read_cvar(CFG, 'SV_HOSTNAME') == 'duel'
    assert cvar_text.read_cvar(CFG, 'fraglimit') is None


def test_upsert_rewrites_the_last_occurrence_keeping_keyword_and_indent():
    out = cvar_text.upsert_cvar(CFG, 'qlx_itemRouletteTakeChance', '30')
    assert 'set qlx_itemRouletteTakeChance "50"\n' in out
    assert '  set qlx_itemRouletteTakeChance "30"\n' in out
    assert out.count('qlx_itemRouletteTakeChance') == 2


def test_upsert_quotes_an_unquoted_line_and_keeps_its_comment():
    out = cvar_text.upsert_cvar(CFG, 'g_password', 'secret')
    assert 'seta g_password "secret" // join password\n' in out


def test_upsert_appends_when_absent():
    out = cvar_text.upsert_cvar('set a "1"', 'fraglimit', '20')
    assert out == 'set a "1"\nset fraglimit "20"\n'
    assert cvar_text.upsert_cvar('', 'fraglimit', '20') == 'set fraglimit "20"\n'


def test_upsert_appends_after_a_trailing_newline_without_a_blank_line():
    out = cvar_text.upsert_cvar('set a "1"\n', 'b', '2')
    assert out == 'set a "1"\nset b "2"\n'


def test_sanitize_drops_quotes_and_newlines():
    assert cvar_text.sanitize_value('a"b\r\nc') == 'abc'
    assert cvar_text.sanitize_value(None) == ''
    assert cvar_text.sanitize_value(25) == '25'


def test_unified_diff_names_the_file_and_shows_the_change():
    before = 'set a "1"\nset b "2"\n'
    after = 'set a "1"\nset b "3"\n'
    diff = cvar_text.unified_diff(before, after, 'server.cfg')
    assert diff.startswith('--- server.cfg')
    assert '-set b "2"' in diff and '+set b "3"' in diff
    assert cvar_text.unified_diff(before, before, 'server.cfg') == ''
