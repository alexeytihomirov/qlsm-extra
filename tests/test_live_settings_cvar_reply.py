"""live-settings: parsing what the engine prints for a bare cvar name over
rcon (`"name" is:"value^7" default:"d^7"`, plus `latched:"x"` when the new
value waits for the next map).
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

cvar_reply = importlib.import_module(f'{_PKG}.cvar_reply')


def test_value_and_default_are_split_and_the_trailing_white_code_dropped():
    lines = ['"qlx_itemRouletteTakeChance" is:"25^7" default:"50^7"']
    found = cvar_reply.parse_cvar_lines(lines)
    entry = found['qlx_itemroulettetakechance']
    assert entry['name'] == 'qlx_itemRouletteTakeChance'
    assert entry['value'] == '25'
    assert entry['default'] == '50'
    assert entry['latched'] is None
    assert entry['raw'] == lines[0]


def test_colour_codes_inside_a_value_survive():
    found = cvar_reply.parse_cvar_lines(['"sv_hostname" is:"^1sD ^7test^7" default:"noname^7"'])
    assert found['sv_hostname']['value'] == '^1sD ^7test'


def test_latched_value_is_reported():
    found = cvar_reply.parse_cvar_lines(['"sv_maxclients" is:"16^7" default:"24^7" latched:"24"'])
    assert found['sv_maxclients']['value'] == '16'
    assert found['sv_maxclients']['latched'] == '24'


def test_the_default_marker_means_default_equals_value():
    found = cvar_reply.parse_cvar_lines(['"g_gravity" is:"800^7", the default'])
    assert found['g_gravity']['value'] == '800'
    assert found['g_gravity']['default'] == '800'


def test_empty_value_and_no_default():
    found = cvar_reply.parse_cvar_lines(['"g_password" is:"^7"'])
    assert found['g_password']['value'] == ''
    assert found['g_password']['default'] is None


def test_other_lines_are_ignored_and_last_report_wins():
    lines = [
        'zmq RCON command from 10.0.0.1: timelimit',
        '"timelimit" is:"15^7" default:"0^7"',
        'broadcast: print "hello"',
        '"timelimit" is:"20^7" default:"0^7"',
    ]
    found = cvar_reply.parse_cvar_lines(lines)
    assert list(found) == ['timelimit']
    assert found['timelimit']['value'] == '20'


def test_frames_are_turned_into_lines():
    frames = [b'print "\\"timelimit\\" is:\\"15^7\\" default:\\"0^7\\"\n"'.replace(b'\\"', b'"'),
              b'zmq RCON command from x\n', b'part one ', b'part two\n']
    assert cvar_reply.frames_to_lines(frames) == [
        '"timelimit" is:"15^7" default:"0^7"', 'part one part two',
    ]
