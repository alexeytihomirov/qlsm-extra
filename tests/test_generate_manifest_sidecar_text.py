"""generate_manifest.plugin_text: the sidecar wins for operator-facing text."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from generate_manifest import plugin_text  # noqa: E402

pytestmark = pytest.mark.standalone


def test_sidecar_wins_over_existing():
    sidecar = {"label": "New", "description": "new text"}
    existing = {"label": "Old", "description": "old text"}
    assert plugin_text(sidecar, existing) == ("New", "new text")


def test_missing_sidecar_key_keeps_existing():
    assert plugin_text({"label": "New"}, {"label": "Old", "description": "old text"}) == ("New", "old text")


def test_both_empty_gives_none():
    assert plugin_text({}, {}) == (None, None)
