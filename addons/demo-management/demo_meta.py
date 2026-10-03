"""Per-match metadata for the Demos listing: what each listed file IS (which
match, which map, whose POV), on top of the bare name/size/mtime the
directory listing gives.

Two sources, in order of trust:

1. A "{match_id}.meta.json" file next to the demos. Written by whichever
   producer knows the match best (qlmatch-packer's pack.mjs writes one per
   pack, atomically, and rewrites it on a full rebuild). This is the only
   reliable source once a filename is operator-configurable: a .qlmatch named
   by qlx_qlmatchNameTemplate may carry no match id or map at all, and the
   meta's "pack"/"povs" fields are what tie it back to its match.

2. The engine's own filename contract, as a fallback for matches nothing has
   written a meta for (packer not installed, packing failed, older packs):
   per-match files start with "{match_id}_" (demo_match.c's
   demo_match_id_now), and a per-POV demo is
   "{match_id}_{map}_p{slot}_{name}_{seg_time}_{seg_id}.dm_91". Those names
   are fixed by the engine, not by any cvar, so parsing them is safe.

The directory listing stays the only source of truth for what EXISTS. A meta
never adds a file to the listing - it only labels files the listing already
has - so a deleted demo cannot come back through a stale meta, and a meta
whose files are all gone is simply never looked at (no index to compact, no
cleanup step to forget). That is also why there is one small file per match
rather than one shared index: a rebuild rewrites exactly its own file
(write + rename, atomic), concurrent packers cannot race on a shared file,
and deleting a match by its "{match_id}*" prefix takes its meta with it.

Format (version 1), every field but match_id optional:

    {"format": "qlsm-demo-meta", "version": 1,
     "match_id": "20260917T174655Z", "map": "bloodrun", "gametype": "duel",
     "duration_ms": 612000,
     "players": [{"name": "alex", "team": "0"}, ...],
     "povs": [{"file": "<basename>.dm_91", "client_num": 3, "name": "alex"}],
     "pack": "<basename>.qlmatch"}
"""
import json
import logging
import re
from datetime import datetime, timezone

log = logging.getLogger(__name__)

META_FORMAT = 'qlsm-demo-meta'
META_VERSION = 1
# A meta is a few hundred bytes; anything this large is not one.
META_MAX_BYTES = 256 * 1024

# Named after the match id alone (never a template), so the name itself says
# which match it describes before it is even read.
META_FILENAME_RE = re.compile(r'\A(\d{8}T\d{6}Z)\.meta\.json\Z')

# The match_id token as demo_match.c mints it, anchored at the start of the
# name and followed by a separator, so a longer stamp never half-matches.
MATCH_ID_PREFIX_RE = re.compile(r'\A(\d{8}T\d{6}Z)[._]')
MATCH_ID_RE = re.compile(r'\A(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z\Z')

# demo_build_pov_name() + the "_{seg_time}_{seg_id}" suffix demo_match.c
# appends. The map is non-greedy so "_p<digits>_" ends it.
_POV_RE = re.compile(r'\A\d{8}T\d{6}Z_([A-Za-z0-9_-]+?)_p(\d+)_(.*)\.dm_91\Z')

# Suffix -> kind, longest first. Anything else falls back to its extension.
_KINDS = (
    ('.replay.json.gz', 'replay'),
    ('.qlmatch', 'pack'),
    ('.dm_91', 'pov'),
)

# Redis key prefix for parsed metas. A cached entry is keyed by the file's
# (name, size, mtime), so a rewritten meta is a different key and a stale
# value can never be read back for new content.
_CACHE_PREFIX = 'qlsm:demo-management:meta:v1'
_CACHE_TTL_SECONDS = 30 * 24 * 3600


def started_at_from_match_id(match_id):
    """'20260917T174655Z' -> '2026-09-17T17:46:55Z', or None."""
    found = MATCH_ID_RE.match(match_id or '')
    if not found:
        return None
    y, mo, d, h, mi, s = (int(v) for v in found.groups())
    try:
        stamp = datetime(y, mo, d, h, mi, s, tzinfo=timezone.utc)
    except ValueError:
        return None
    return stamp.strftime('%Y-%m-%dT%H:%M:%SZ')


def kind_of(name):
    lower = name.lower()
    for suffix, kind in _KINDS:
        if lower.endswith(suffix):
            return kind
    return lower.rsplit('.', 1)[-1] if '.' in lower else 'file'


def _pov_from_filename(name):
    """(map, slot, player) out of an engine-named POV, or None."""
    found = _POV_RE.match(name)
    if not found:
        return None
    map_name, slot, rest = found.group(1), int(found.group(2)), found.group(3)
    # Drop the trailing "_{seg_time}_{seg_id}" numeric tokens (at most two,
    # older captures carried one); demo_sanitise() turned spaces into '_'.
    parts = rest.split('_')
    dropped = 0
    while len(parts) > 1 and dropped < 2 and parts[-1].isdigit():
        parts.pop()
        dropped += 1
    return map_name, slot, ' '.join(parts).strip()


def _str(value, limit=200):
    return str(value)[:limit] if isinstance(value, (str, int, float)) and value != '' else None


def parse_meta(raw, expected_match_id):
    """Validate and normalise one meta file's bytes. None if it is not a
    usable meta for `expected_match_id` (wrong format, wrong match, broken
    JSON) - a bad meta degrades to the filename fallback, never an error."""
    try:
        data = json.loads(raw.decode('utf-8') if isinstance(raw, bytes) else raw)
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict) or data.get('format') != META_FORMAT:
        return None
    if not isinstance(data.get('version'), int) or data['version'] > META_VERSION:
        return None
    if data.get('match_id') != expected_match_id:
        return None

    players = []
    for row in data.get('players') or []:
        if isinstance(row, dict) and _str(row.get('name')):
            players.append({'name': _str(row['name'], 64), 'team': _str(row.get('team'), 8) or ''})

    povs = []
    for row in data.get('povs') or []:
        if isinstance(row, dict) and isinstance(row.get('file'), str) and row['file']:
            povs.append({
                'file': row['file'].rsplit('/', 1)[-1],
                'client_num': row['client_num'] if isinstance(row.get('client_num'), int) else None,
                'name': _str(row.get('name'), 64) or '',
            })

    duration = data.get('duration_ms')
    pack = data.get('pack')
    return {
        'match_id': expected_match_id,
        'map': _str(data.get('map'), 64),
        'gametype': _str(data.get('gametype'), 32),
        'duration_ms': int(duration) if isinstance(duration, (int, float)) and duration > 0 else None,
        'players': players,
        'povs': povs,
        'pack': pack.rsplit('/', 1)[-1] if isinstance(pack, str) and pack else None,
    }


# ---- Redis cache -----------------------------------------------------------

def _redis():
    try:
        from flask import current_app
        return current_app.extensions.get('redis')
    except Exception:
        return None


def _cache_key(instance_id, entry):
    return f"{_CACHE_PREFIX}:{instance_id}:{entry['name']}:{entry['size']}:{entry['mtime']}"


def cache_get_many(instance_id, entries):
    """{name: parsed meta (or None for "known unusable")} for every entry the
    cache has. Fails open: no Redis, or Redis down, is just a full miss."""
    client = _redis()
    if client is None or not entries:
        return {}
    try:
        values = client.mget([_cache_key(instance_id, e) for e in entries])
    except Exception as exc:
        log.warning('demo meta cache read skipped: %s', exc)
        return {}
    hits = {}
    for entry, value in zip(entries, values):
        if value is None:
            continue
        try:
            hits[entry['name']] = json.loads(value)
        except ValueError:
            continue
    return hits


def cache_put_many(instance_id, parsed_by_entry):
    """Store parsed metas. An unusable meta is cached as JSON null so a bad
    file is not re-read on every listing - its key changes as soon as the
    file is rewritten."""
    client = _redis()
    if client is None or not parsed_by_entry:
        return
    try:
        pipe = client.pipeline(transaction=False)
        for entry, parsed in parsed_by_entry:
            pipe.set(_cache_key(instance_id, entry), json.dumps(parsed), ex=_CACHE_TTL_SECONDS)
        pipe.execute()
    except Exception as exc:
        log.warning('demo meta cache write skipped: %s', exc)


# ---- annotation ------------------------------------------------------------

def annotate(demos, metas):
    """Label every listed file in place and return {match_id: info}.

    `metas` is {match_id: parsed meta}. Adds to each demo dict:
      kind        "pov" | "pack" | "replay" | <extension>
      match_id    when the name starts with one, or a meta claims the file
      started_at  ISO UTC, from the match id
      map         from the meta, else from an engine-named POV
      pov         {"slot", "player"} for a per-POV demo, when known
      match_source  "meta" or "filename" - where its match's info came from

    info per match: match_id, started_at, map, gametype, duration_ms,
    players, source ("meta" or "filename"). Without a meta the players are
    the names on the match's POV files and the gametype is unknown here. Only matches that still have at
    least one listed file get one.
    """
    claimed = {}
    pov_by_file = {}
    for match_id, meta in metas.items():
        if meta.get('pack'):
            claimed[meta['pack']] = match_id
        for pov in meta.get('povs') or []:
            claimed[pov['file']] = match_id
            pov_by_file[pov['file']] = pov

    infos = {}
    for demo in demos:
        name = demo['name']
        demo['kind'] = kind_of(name)

        prefix = MATCH_ID_PREFIX_RE.match(name)
        match_id = prefix.group(1) if prefix else claimed.get(name)
        parsed_pov = _pov_from_filename(name) if demo['kind'] == 'pov' else None

        if parsed_pov or name in pov_by_file:
            meta_pov = pov_by_file.get(name)
            demo['pov'] = {
                'slot': parsed_pov[1] if parsed_pov else None,
                'player': (meta_pov or {}).get('name') or (parsed_pov[2] if parsed_pov else ''),
            }

        if not match_id:
            continue
        demo['match_id'] = match_id
        started_at = started_at_from_match_id(match_id)
        if started_at:
            demo['started_at'] = started_at

        info = infos.get(match_id)
        if info is None:
            meta = metas.get(match_id)
            info = {
                'match_id': match_id,
                'started_at': started_at,
                'map': meta.get('map') if meta else None,
                'gametype': meta.get('gametype') if meta else None,
                'duration_ms': meta.get('duration_ms') if meta else None,
                'players': list(meta.get('players') or []) if meta else [],
                'source': 'meta' if meta else 'filename',
            }
            infos[match_id] = info
        if not info['map'] and parsed_pov:
            info['map'] = parsed_pov[0]
        # No meta: the POVs' own filenames still say who played.
        if info['source'] == 'filename' and parsed_pov and parsed_pov[2]:
            if all(p['name'] != parsed_pov[2] for p in info['players']):
                info['players'].append({'name': parsed_pov[2], 'team': ''})
        demo['match_source'] = info['source']
        if info['map']:
            demo['map'] = info['map']

    # A map learned from a later POV still labels the earlier files.
    for demo in demos:
        info = infos.get(demo.get('match_id'))
        if info and info['map']:
            demo['map'] = info['map']
    return infos


def merge_info(primary, fallback):
    """Fill the gaps in `primary` from `fallback` (either may be None)."""
    if not primary:
        return dict(fallback) if fallback else None
    merged = dict(primary)
    for key, value in (fallback or {}).items():
        if merged.get(key) in (None, '', []):
            merged[key] = value
    return merged
