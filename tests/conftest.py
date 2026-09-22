"""Test harness for the addons in this repo.

These addons run *inside* qlsm: they import `ui.db`, `ui.models`,
`ui.addons.dispatch` and are mounted as Flask blueprints by qlsm's addon
registry. So their tests need a qlsm checkout, and there is no way around
that short of mocking the half of the code that actually matters.

Point `QLSM_REPO` at one, or keep qlsm checked out next to this repo (the
monorepo layout: `<root>/qlsm` beside `<root>/qlsm-extra`) and it is found
automatically. Without one, every test here skips with a message rather than
erroring -- a clone of this repo alone is still a valid thing to have.

    QLSM_REPO=/path/to/qlsm python -m pytest tests/ -q

The `app` fixture installs the addon under test the way an operator would:
copied into an ADDON_PACKAGES_DIR volume, loaded from there, not bundled.
That is also the only way it *can* be loaded now -- qlsm's image ships no
addon at all.
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
ADDONS_DIR = REPO_ROOT / 'addons'


def _find_qlsm():
    explicit = os.environ.get('QLSM_REPO')
    candidates = [Path(explicit)] if explicit else []
    candidates.append(REPO_ROOT.parent / 'qlsm')
    for path in candidates:
        if (path / 'ui' / '__init__.py').is_file():
            return path.resolve()
    return None


QLSM_REPO = _find_qlsm()

if QLSM_REPO is not None:
    # qlsm resolves a handful of config paths relative to the process's
    # working directory (presets, drafts, ql-assets), so the suite runs from
    # its checkout rather than this one.
    sys.path.insert(0, str(QLSM_REPO))
    os.chdir(QLSM_REPO)
    os.environ.setdefault('SECRET_KEY', 'test-secret-key')


def pytest_collection_modifyitems(config, items):
    if QLSM_REPO is not None:
        return
    skip = pytest.mark.skip(reason='no qlsm checkout found -- set QLSM_REPO')
    for item in items:
        item.add_marker(skip)


@pytest.fixture
def addon_id():
    """Overridden per test module; the addon to install into the volume."""
    raise NotImplementedError('a test module must override the addon_id fixture')


@pytest.fixture
def addon_ids(request):
    """Every addon to install for this test.

    Defaults to the single one the module names, so the common case stays
    `addon_id`. A test that needs two addons together -- one declaring an
    extension point and the other contributing to it -- overrides this
    instead.
    """
    return [request.getfixturevalue('addon_id')]


@pytest.fixture
def app(tmp_path, monkeypatch, addon_ids):
    """A qlsm app with the named addons installed, from the volume."""
    from ui import create_app, db
    from ui.addons import registry

    packages = tmp_path / 'addon-packages'
    packages.mkdir()
    for addon_id in addon_ids:
        source = ADDONS_DIR / addon_id
        assert source.is_dir(), f'no addon named {addon_id} in this repo'
        shutil.copytree(
            source, packages / addon_id,
            ignore=shutil.ignore_patterns('node_modules', 'ui-src', '__pycache__',
                                          'package.json', 'package-lock.json',
                                          'vite.config.js'),
        )

    # Installed-only: drop qlsm's bundled addons/ dir from the scan so a
    # stale copy there could never be what these tests exercise.
    monkeypatch.setattr(
        registry, '_candidate_dirs',
        lambda a: [(str(a.config['ADDON_PACKAGES_DIR']), 'installed')],
    )

    db_fd, db_path = tempfile.mkstemp()
    application = create_app({
        'TESTING': True,
        'SECRET_KEY': 'test-secret-key',
        'JWT_SECRET_KEY': 'test-jwt-secret-key',
        'JWT_COOKIE_CSRF_PROTECT': False,
        'JWT_TOKEN_LOCATION': ['headers', 'cookies'],
        'SQLALCHEMY_DATABASE_URI': f'sqlite:///{db_path}',
        'SQLALCHEMY_TRACK_MODIFICATIONS': False,
        'WTF_CSRF_ENABLED': False,
        'RCON_ENABLED': False,
        'ADDON_PACKAGES_DIR': str(packages),
        'DRAFTS_BASE': str(tmp_path / 'qlds-drafts'),
    })
    with application.app_context():
        db.create_all()

    yield application

    with application.app_context():
        db.session.remove()
        db.engine.dispose()
    os.close(db_fd)
    for path in (db_path, f'{db_path}-wal', f'{db_path}-shm'):
        if os.path.exists(path):
            os.unlink(path)


@pytest.fixture
def client(app):
    return app.test_client()


# Copied from qlsm's tests/helpers.py rather than imported: adding qlsm's
# repo root to sys.path makes *two* top-level `tests` packages visible, and
# which one `import tests.helpers` resolves to depends on collection order.
# Two five-line functions are cheaper than that ambiguity.
def make_user(app, username, password):
    from ui import db
    from ui.models import User
    with app.app_context():
        user = User(username=username)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        return user.id


def auth_headers(app, identity):
    from flask_jwt_extended import create_access_token
    with app.app_context():
        token = create_access_token(identity=identity)
    return {'Authorization': f'Bearer {token}'}
