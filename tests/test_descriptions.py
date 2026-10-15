"""Every addon and plugin description is short: what it does and what it needs.

At most two sentences and 300 characters, hyphens only. Panel descriptions
follow the same rule; operational detail belongs in field descriptions or
README.md.
"""
import json
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.standalone

ROOT = Path(__file__).resolve().parent.parent
ADDON_MANIFESTS = sorted(ROOT.glob('addons/*/qlsm-addon.json'))
PLUGIN_SIDECARS = sorted(ROOT.glob('*.ql-plugin.json'))
HELPERS = {
    'match_restore_util': 'match_restore',
    'qlmatch_packer_cmd': 'qlmatch_packer',
    'telemetry_unified_sched': 'stream_telemetry_unified',
    'stats_hub_pause': 'stream_telemetry_unified',
}

_SENTENCE_END = re.compile(r'\. (?=[A-Z])')


def _load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def _texts():
    for path in ADDON_MANIFESTS:
        manifest = _load(path)
        yield f'{path.parent.name}', manifest['description']
        for name, panel in (manifest.get('ui', {}).get('panels') or {}).items():
            if panel.get('description'):
                yield f'{path.parent.name} panel {name}', panel['description']
    for path in PLUGIN_SIDECARS:
        yield path.name, _load(path)['description']


TEXTS = list(_texts())


def test_found_the_files():
    assert len(ADDON_MANIFESTS) >= 8
    assert len(PLUGIN_SIDECARS) >= 13


@pytest.mark.parametrize('where,text', TEXTS, ids=[w for w, _ in TEXTS])
def test_description_is_short(where, text):
    sentences = [s for s in _SENTENCE_END.split(text.strip()) if s]
    assert len(sentences) <= 2, f'{where}: {len(sentences)} sentences'
    assert len(text) <= 300, f'{where}: {len(text)} characters'
    assert '—' not in text and '–' not in text, where


@pytest.mark.parametrize('helper,plugin', sorted(HELPERS.items()))
def test_helper_sidecar_text(helper, plugin):
    sidecar = _load(ROOT / f'{helper}.ql-plugin.json')
    assert sidecar == {
        'label': f'{plugin} helper',
        'description': f'Helper of {plugin}.py, downloaded with it. Not a plugin.',
    }
