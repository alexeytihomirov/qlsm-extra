"""Contributes match-level grouping + rebuild actions to demo-management's
Demos listing via the demo_management.match_groups hook -- see
ui/addons/hooks.py for the contract this implements and why its shape
differs from the match_actions sketch in addons/README.md.
"""
from urllib.parse import quote

from .instance_demo_transport import demo_dir_for_instance, open_sftp, resolve_instance_and_host

from .qlmatch_listing import _manifest_from_pack, qlmatch_sidecar_name

ADDON_ID = 'qlmatch-packer'


def _packer_log_name(match_id):
    return f'{match_id}.packer.log'


def build_match_groups(instance_id, demos):
    """One group per .qlmatch pack found in `demos`, clustering it with the
    raw per-POV .dm_91 files it was built from (still on disk -- packing
    copies them into the zip, it never deletes the originals) plus its
    sidecar/log siblings (if also present), and offering the two rebuild
    actions.

    Opens at most one SFTP session (only if there is at least one .qlmatch
    row to resolve, and only for packs not already in _manifest_from_pack's
    cache), reading each pack's manifest.json the same way
    qlmatch_listing.list_instance_qlmatches does and for the same reason:
    one SSH handshake for the whole listing, not one per pack. A pack whose
    manifest.json cannot be read is skipped -- it stays an ungrouped, plain
    row in the Demos listing rather than failing the whole call.
    """
    demo_names = {d['name'] for d in demos}
    demo_by_name = {d['name']: d for d in demos}
    qlmatch_names = sorted(n for n in demo_names if n.endswith('.qlmatch'))
    if not qlmatch_names:
        return []

    instance, host, error = resolve_instance_and_host(instance_id)
    if error:
        return []
    demo_dir = demo_dir_for_instance(instance)

    groups = []
    client, sftp = open_sftp(host)
    try:
        for name in qlmatch_names:
            demo_row = demo_by_name[name]
            cache_key = (instance_id, name, demo_row.get('size'), demo_row.get('mtime'))
            manifest, _error = _manifest_from_pack(sftp, demo_dir, name, cache_key=cache_key)
            if not manifest:
                continue
            match_id, map_name = manifest['match_id'], manifest['map']

            member_names = [name]
            for raw_name in manifest.get('raw_demo_names') or []:
                if raw_name in demo_names and raw_name not in member_names:
                    member_names.append(raw_name)
            sidecar_name = qlmatch_sidecar_name(match_id, map_name)
            if sidecar_name in demo_names:
                member_names.append(sidecar_name)
            log_name = _packer_log_name(match_id)
            if log_name in demo_names:
                member_names.append(log_name)

            encoded_name = quote(name, safe='')
            groups.append({
                'group_id': match_id,
                'label': f'{map_name} — {match_id}',
                'addon_id': ADDON_ID,
                'member_names': member_names,
                'qlmatch_name': name,
                'actions': [
                    {
                        'id': 'qlmatch-packer.rebuild-sidecar',
                        'label': 'Rebuild sidecar',
                        'icon': 'refresh-cw',
                        'action': {
                            'route': f'instances/{{instance_id}}/matches/{encoded_name}/rebuild-sidecar',
                            'method': 'POST',
                            'confirm': 'Regenerate the replay sidecar from the existing pack?',
                        },
                        # Shown as a toolbar button once 2+ groups sharing
                        # this action id are selected -- selection_key
                        # mirrors the tier-1 bulk_actions convention
                        # (AddonTablePanel.jsx), just posting .qlmatch
                        # filenames instead of demo-management's own
                        # filenames since qlmatch-packer is the one
                        # resolving them to a match_id/map on the backend.
                        'bulk': {
                            'route': 'instances/{instance_id}/matches/rebuild-sidecar-batch',
                            'method': 'POST',
                            'selection_key': 'filenames',
                        },
                    },
                    {
                        'id': 'qlmatch-packer.rebuild-full',
                        'label': 'Full rebuild',
                        'icon': 'refresh-cw',
                        'danger': True,
                        'action': {
                            'route': f'instances/{{instance_id}}/matches/{encoded_name}/rebuild-full',
                            'method': 'POST',
                            'confirm': 'Re-run the packer from the raw demos? The raw .dm_91 '
                                       'files must still be on disk.',
                        },
                        'bulk': {
                            'route': 'instances/{instance_id}/matches/rebuild-full-batch',
                            'method': 'POST',
                            'selection_key': 'filenames',
                        },
                    },
                ],
            })
    finally:
        client.close()

    return groups
