"""qlmatch-packer extends demo-management, and nothing else was testing that.

Each addon's own tests install it alone, so the one thing that only happens
when both are present -- qlmatch-packer's contribution reaching
demo-management's file listing -- was covered nowhere. That contribution is
also the whole reason the extension-point mechanism exists, and it changed
shape when hook ownership moved out of qlsm core and into the manifest of the
addon being extended: demo-management now declares `file_kinds` and
`match_groups` itself, and qlsm validates qlmatch-packer's subscription
against that declaration rather than against a hardcoded table.

So this pins the contract end to end: declared, subscribed, gated, dispatched.
"""
import pytest

from ui.addons import registry


@pytest.fixture
def addon_ids():
    return ['demo-management', 'qlmatch-packer']


def test_both_addons_load_clean(app):
    for addon_id in ('demo-management', 'qlmatch-packer'):
        addon = registry.get_addon(addon_id, app)
        assert addon is not None, f'{addon_id} was not discovered'
        assert addon.loaded is True, f'{addon_id} failed to load: {addon.errors}'
        assert addon.errors == []


def test_demo_management_declares_the_points_it_dispatches(app):
    """The names its own code calls dispatch() with must be the names its
    manifest declares -- a mismatch degrades silently to "no contributors"."""
    declared = registry.get_declared_hooks(app)

    assert set(declared) >= {'demo_management.file_kinds',
                             'demo_management.match_groups'}
    for name in ('demo_management.file_kinds', 'demo_management.match_groups'):
        assert declared[name]['owner'] == 'demo-management'
        assert declared[name]['list'] is True, (
            f'{name} collects contributions from several addons; declaring it '
            f'as a single value would nest each contributor\'s list'
        )


def test_qlmatch_packer_subscribes_to_them(app):
    packer = registry.get_addon('qlmatch-packer', app)

    assert 'demo_management.file_kinds' in packer.ctx.handlers
    assert 'demo_management.match_groups' in packer.ctx.handlers


def test_its_file_kinds_reach_the_listing_once_enabled(app):
    """The contribution itself, flattened rather than nested, and gated on
    qlmatch-packer's own global switch: turning the addon off has to stop its
    files showing up in Demos, not just hide its settings."""
    with app.app_context():
        assert registry.dispatch('demo_management.file_kinds', 0) == []

        registry.get_addon('qlmatch-packer').ctx.settings.set_enabled('global', 0, True)
        kinds = registry.dispatch('demo_management.file_kinds', 0)

    assert 'qlmatch' in kinds
    assert all(isinstance(k, str) for k in kinds), (
        'a nested list here means the point was declared without "list": true'
    )

    # The other half of "optional": demo-management does not need the addon
    # that extends it. Its own test module installs it alone and its listing
    # works there, which is that case covered.
