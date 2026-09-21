"""Server-side demo listing and download, as an addon.

The built-in Demos modal and its core endpoints were deleted once this addon
was verified against real recordings on a real host - this is now the only
place the feature lives, including `ansible_instance_demos.py` itself (moved
in alongside this backend rather than staying in ui/task_logic/, so the
security-relevant filename validation lives next to its only caller instead
of split across core and addon).

By default this addon only recognises the raw per-POV .dm_91 file minqlxtended's
native demo capture writes -- it has no opinion on packed/derived formats.
Another addon extends what shows up here via the demo_management.file_kinds
hook (see ansible_instance_demos.py's _demo_filename_re()); qlmatch-packer is
the one bundled example, contributing .qlmatch/.replay.json.gz.
Its own external Bearer-token match API moved with it -- this addon no longer
knows anything about the .qlmatch format specifically.
"""
import io
import re
import zipfile

from flask import Blueprint, current_app, jsonify, request, send_file
from flask_jwt_extended import jwt_required

bp = Blueprint('demo_management_addon', __name__)


def _instance_or_error(instance_id):
    from ui.database import get_instance

    instance = get_instance(instance_id)
    if not instance:
        return None, (jsonify({"error": {"message": "Instance not found."}}), 404)
    if not instance.host:
        return None, (jsonify({"error": {"message": "Instance has no associated host."}}), 400)
    return instance, None


@bp.route('/instances/<int:instance_id>/demos', methods=['GET'], endpoint='list_demos')
@jwt_required()
def list_demos(instance_id):
    from ui.addons import dispatch

    from .ansible_instance_demos import list_instance_demos
    from .raw_match_groups import build_raw_match_groups

    instance, error = _instance_or_error(instance_id)
    if error:
        return error

    success, demos, error_msg = list_instance_demos(instance_id)
    if not success:
        current_app.logger.error(f'Addon demo-management: list failed for {instance_id}: {error_msg}')
        return jsonify({"error": {"message": error_msg}}), 500

    # Addon-owned extension point (demo_management.match_groups, see
    # ui/addons/hooks.py): another addon may know how to cluster some of
    # these files into a logical "match" and offer ACTIONS on it (e.g.
    # qlmatch-packer's Rebuild buttons), which is the part this addon stays
    # ignorant of, same as it already is for file_kinds.
    try:
        matches = dispatch('demo_management.match_groups', 0, instance_id, demos)
    except Exception as e:
        current_app.logger.warning(f'demo_management.match_groups hook skipped: {e}')
        matches = []

    # The clustering itself needs no addon: the engine's own filenames say
    # which match a file belongs to (see raw_match_groups). So every match the
    # hook did not claim still shows up as one row rather than one row per POV
    # -- which is what a duel's four POVs used to be, and what they still are
    # whenever the packer could not run.
    claimed = {name for group in matches for name in group.get('member_names') or []}
    matches = list(matches) + build_raw_match_groups(demos, claimed)

    return jsonify({"data": {"demos": demos, "matches": matches, "instance_name": instance.name}})


@bp.route('/instances/<int:instance_id>/demos/download', methods=['GET'], endpoint='download_demo')
@jwt_required()
def download_demo(instance_id):
    from .ansible_instance_demos import fetch_instance_demos

    instance, error = _instance_or_error(instance_id)
    if error:
        return error

    filename = request.args.get('filename', '')
    if not filename:
        return jsonify({"error": {"message": "filename is required."}}), 400

    success, files, missing, error_msg = fetch_instance_demos(instance_id, [filename])
    if not success:
        current_app.logger.error(f'Addon demo-management: download failed for {instance_id}: {error_msg}')
        return jsonify({"error": {"message": error_msg}}), 500
    if filename in missing or filename not in files:
        return jsonify({"error": {"message": "Demo file not found on the remote host."}}), 404

    return send_file(
        io.BytesIO(files[filename]),
        as_attachment=True,
        download_name=filename,
        mimetype='application/octet-stream',
    )


@bp.route('/instances/<int:instance_id>/demos/download-batch', methods=['POST'], endpoint='download_demos_batch')
@jwt_required()
def download_demos_batch(instance_id):
    """Zip up a checkbox selection.

    The table panel posts the selection under the key the manifest declares
    (`selection_key: "filenames"`), which is the name this endpoint and the
    built-in one already use.
    """
    from .ansible_instance_demos import fetch_instance_demos

    instance, error = _instance_or_error(instance_id)
    if error:
        return error

    data = request.get_json(silent=True) or {}
    filenames = data.get('filenames')
    if not isinstance(filenames, list) or not filenames:
        return jsonify({"error": {"message": "filenames must be a non-empty list."}}), 400

    success, files, missing, error_msg = fetch_instance_demos(instance_id, filenames)
    if not success:
        current_app.logger.error(f'Addon demo-management: batch failed for {instance_id}: {error_msg}')
        return jsonify({"error": {"message": error_msg}}), 500
    if not files:
        return jsonify({"error": {"message": "None of the selected files were found on the remote host."}}), 404

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    buf.seek(0)

    safe_name = re.sub(r'[^A-Za-z0-9._-]+', '-', instance.name or '').strip('.-') or 'instance'
    return send_file(
        buf,
        as_attachment=True,
        download_name=f'{safe_name}-demos.zip',
        mimetype='application/zip',
    )


def register(ctx):
    ctx.blueprint(bp)
