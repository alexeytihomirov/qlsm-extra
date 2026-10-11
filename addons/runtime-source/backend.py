"""Build a host's minqlxtended from an operator-chosen repository.

qlsm's setup_host.yml clones minqlxtended from two playbook vars,
`minqlxtended_git_repo` and `minqlxtended_git_version`. This addon stores a
repository and a version per host and returns them from the `host.setup` hook,
which qlsm passes to the playbook as extra-vars -- so the choice applies on the
next host setup run, and on every one after it.

Nothing else about the host changes: it is still a minqlxtended host, with the
minqlxtended plugin pool, paths and presets.
"""
import re

from flask import Blueprint, jsonify
from flask_jwt_extended import jwt_required

bp = Blueprint('runtime_source', __name__)

RUNTIME = 'minqlxtended'

# https only, no credentials, no query string: the URL is stored in the
# database, shown in the UI and handed to `git clone` on the host.
_REPO = re.compile(r'^https://[A-Za-z0-9.-]+(:\d+)?(/[A-Za-z0-9._~-]+)+/?$')
# A commit hash, tag or branch. The first character may not be '-', so the
# value can never be read as an option by git.
_VERSION = re.compile(r'^[A-Za-z0-9_][A-Za-z0-9._/-]*$')


def resolve_source(settings):
    """(extra_vars, problem) for one host's stored settings.

    Both fields blank is not a problem: it means "build what qlsm pins" and
    yields no extra-vars. Anything else that does not validate yields no
    extra-vars either, plus the reason -- a half-filled or malformed source
    must never reach git on the host.
    """
    repo = str(settings.get('git_repo') or '').strip()
    version = str(settings.get('git_version') or '').strip()
    if not repo and not version:
        return {}, None
    if not repo or not version:
        return {}, 'needs both a repository URL and a commit, tag or branch'
    if len(repo) > 255 or not _REPO.match(repo):
        return {}, 'the repository must be an https:// git URL without credentials'
    if len(version) > 100 or '..' in version or not _VERSION.match(version):
        return {}, 'the version must be a commit hash, tag or branch name'
    return {
        f'{RUNTIME}_git_repo': repo,
        f'{RUNTIME}_git_version': version,
    }, None


def _host_runtime(host_id):
    from ui import db
    from ui.models import Host
    from ui.runtime import host_runtime

    host = db.session.get(Host, host_id)
    return host_runtime(host) if host is not None else None


def register(ctx):
    ctx.blueprint(bp)

    @bp.route('/hosts/<int:host_id>/status', methods=['GET'])
    @jwt_required()
    def status(host_id):
        """The badge on the host panel: what the next setup run will build."""
        runtime = _host_runtime(host_id)
        if runtime is None:
            return jsonify({'error': {'message': 'Host not found'}}), 404
        if runtime != RUNTIME:
            return jsonify({'data': {'ok': False, 'label': f'Ignored: this host runs {runtime}'}})
        extra_vars, problem = resolve_source(ctx.settings.get('host', host_id))
        if problem:
            return jsonify({'data': {'ok': False, 'label': f'Not applied: {problem}'}})
        if not extra_vars:
            return jsonify({'data': {'ok': True, 'label': 'QLSM pinned build'}})
        if not ctx.settings.is_enabled('host', host_id):
            return jsonify({'data': {'ok': False, 'label': 'Not applied: addon is off for this host'}})
        return jsonify({'data': {'ok': True, 'label': 'Custom source on next host setup'}})

    @ctx.on('host.setup')
    def host_setup(host_id):
        """Only called when the addon is enabled for this host."""
        runtime = _host_runtime(host_id)
        if runtime != RUNTIME:
            return {}
        extra_vars, problem = resolve_source(ctx.settings.get('host', host_id))
        if problem:
            ctx.logger.warning(
                'runtime-source: host %s builds the pinned %s, its custom source is not usable: %s',
                host_id, RUNTIME, problem)
        elif extra_vars:
            ctx.logger.info('runtime-source: host %s builds %s from %s @ %s', host_id, RUNTIME,
                            extra_vars[f'{RUNTIME}_git_repo'], extra_vars[f'{RUNTIME}_git_version'])
        return extra_vars
