"""Contributes match-level grouping + rebuild actions to demo-management's
Demos listing via the demo_management.match_groups hook -- see
ui/addons/hooks.py for the contract this implements and why its shape
differs from the match_actions sketch in addons/README.md.
"""
import re
from urllib.parse import quote

from .instance_demo_transport import demo_dir_for_instance, open_sftp, resolve_instance_and_host

from .qlmatch_listing import _manifest_from_pack, cached_manifest, qlmatch_sidecar_name

ADDON_ID = 'qlmatch-packer'

# Mirrors pack.mjs's GAMETYPE_NAMES - only used to label an older pack that
# has no .meta.json (whose "gametype" is already the name).
_GAMETYPE_NAMES = {
    '0': 'ffa', '1': 'duel', '2': 'race', '3': 'tdm', '4': 'ca', '5': 'ctf',
    '6': '1f', '8': 'har', '9': 'ft', '10': 'dom', '11': 'ad', '12': 'rr',
}


# Quake colour codes ("^1") in a roster name.
_COLOR_CODE_RE = re.compile(r'\^.')


def _packer_log_name(match_id):
    return f'{match_id}.packer.log'


def _cache_key(instance_id, demo_row):
    return (instance_id, demo_row['name'], demo_row.get('size'), demo_row.get('mtime'))


def _info_from_manifest(manifest):
    """The match `info` an older pack's manifest.json can supply."""
    gametype = manifest.get('gametype') or ''
    names = [_COLOR_CODE_RE.sub('', n).strip() for n in manifest.get('pov_names') or []]
    return {
        'match_id': manifest['match_id'],
        'map': manifest['map'],
        'gametype': _GAMETYPE_NAMES.get(gametype, f'gt{gametype}' if gametype else None),
        'players': [{'name': n, 'team': ''} for n in names if n],
        'source': 'pack',
    }


def _resolve_legacy(instance_id, rows):
    """{pack name: manifest summary} for packs demo-management could not tie
    to a match (no "{match_id}.meta.json" - packed before the packer wrote
    one - and a templated name without the match id in front).

    Cache first (in-process, then Redis, keyed by name+size+mtime); an SFTP
    session is opened only if something is still missing, and then only
    once for all of them.
    """
    resolved = {}
    misses = []
    for row in rows:
        hit = cached_manifest(_cache_key(instance_id, row))
        if hit:
            resolved[row['name']] = hit
        else:
            misses.append(row)
    if not misses:
        return resolved

    instance, host, error = resolve_instance_and_host(instance_id)
    if error:
        return resolved
    demo_dir = demo_dir_for_instance(instance)
    client, sftp = open_sftp(host)
    try:
        for row in misses:
            manifest, _error = _manifest_from_pack(
                sftp, demo_dir, row['name'], cache_key=_cache_key(instance_id, row))
            if manifest:
                resolved[row['name']] = manifest
    finally:
        client.close()
    return resolved


def build_match_groups(instance_id, demos):
    """One group per .qlmatch pack found in `demos`, clustering it with every
    other file of its match (the raw per-POV .dm_91 it was built from - packing
    copies them into the zip, it never deletes the originals - plus its
    sidecar), and offering the two rebuild actions.

    Which match a pack belongs to comes, in order, from:
      1. the `match_id` demo-management already put on the row (from the
         match's .meta.json, which pack.mjs writes, or a match-id-prefixed
         name) - no remote access at all;
      2. the pack's own manifest.json, for packs older than the meta file -
         cached, so each such pack is read over SFTP once, ever.
    A pack neither resolves stays an ungrouped, plain row in the Demos
    listing rather than failing the whole call.
    """
    by_match_id = {}
    for demo in demos:
        if demo.get('match_id'):
            by_match_id.setdefault(demo['match_id'], []).append(demo)
    demo_names = {d['name'] for d in demos}

    packs = sorted((d for d in demos if d['name'].endswith('.qlmatch')), key=lambda d: d['name'])
    # Every pack whose match has no .meta.json gets its manifest read (once,
    # then cached): either to learn which match it belongs to, or - when its
    # name already says so - for the gametype and roster no filename carries.
    legacy = _resolve_legacy(instance_id, [d for d in packs if d.get('match_source') != 'meta'])

    groups = []
    for pack in packs:
        name = pack['name']
        info = None
        if pack.get('match_id'):
            match_id, map_name = pack['match_id'], pack.get('map') or ''
            member_names = [name] + [d['name'] for d in by_match_id[match_id] if d['name'] != name]
            if name in legacy:
                map_name = map_name or legacy[name]['map']
                info = _info_from_manifest(legacy[name])
        elif name in legacy:
            manifest = legacy[name]
            match_id, map_name = manifest['match_id'], manifest['map']
            member_names = [name]
            for raw_name in manifest.get('raw_demo_names') or []:
                if raw_name in demo_names and raw_name not in member_names:
                    member_names.append(raw_name)
            for other in by_match_id.get(match_id, []):
                if other['name'] not in member_names:
                    member_names.append(other['name'])
            sidecar_name = qlmatch_sidecar_name(match_id, map_name)
            if sidecar_name in demo_names and sidecar_name not in member_names:
                member_names.append(sidecar_name)
            info = _info_from_manifest(manifest)
        else:
            continue

        log_name = _packer_log_name(match_id)
        if log_name in demo_names and log_name not in member_names:
            member_names.append(log_name)

        encoded_name = quote(name, safe='')
        group = {
            'group_id': match_id,
            'label': f'{map_name} — {match_id}' if map_name else match_id,
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
        }
        if info:
            group['info'] = info
        groups.append(group)

    return groups
