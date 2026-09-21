"""Clusters a listing's files into the matches they belong to, from the engine's
own filenames alone.

This is deliberately NOT the same thing as the demo_management.match_groups
hook (which another addon implements when it knows how to do something WITH a
match - see qlmatch-packer). This module knows only what the engine's naming
contract already states and this addon already documents: every file the
per-match capture ships is named "<match_id>_..." with match_id being a
"%Y%m%dT%H%M%SZ" UTC stamp minted once per match (demo_match.c's
demo_match_id_now / demo_build_pov_name), and a plain sv_demoRecord capture
that belongs to no match is named "%Y%m%d-%H%M%S_..." instead, which cannot
collide with it.

So "everything whose name starts with the same match_id token" IS the match,
and it needs no knowledge of file formats: the per-POV .dm_91 files group with
each other, and with whatever sidecars another addon contributed to the
listing, without this module having to know that .qlmatch or .packer.log
exist. Before this, four POVs of one duel were four unrelated rows.
"""
import re

ADDON_ID = 'demo-management'

# The match_id token as demo_match.c mints it, anchored at the start of the
# name: 8 digits, "T", 6 digits, "Z". The separator after it is required so
# "20260917T174655Z_bloodrun..." matches while a (hypothetical) longer stamp
# does not half-match.
_MATCH_ID_RE = re.compile(r'\A(\d{8}T\d{6}Z)[._]')

# A per-POV demo as demo_build_pov_name() writes it:
# "{match_id}_{map}_p{slot}_{name}_{seg_time}_{seg_id}.dm_91". Only used to
# recover the map name for the row label - membership is the match_id alone.
_POV_RE = re.compile(r'\A\d{8}T\d{6}Z_([A-Za-z0-9_-]+?)_p\d+_.*\.dm_91\Z')


def _match_id_of(name):
    found = _MATCH_ID_RE.match(name)
    return found.group(1) if found else None


def build_raw_match_groups(demos, claimed_names):
    """One group per match_id seen in `demos`, minus anything an addon already
    grouped.

    `claimed_names` is the set of filenames already covered by a
    demo_management.match_groups contributor. A match with even one claimed
    file is skipped entirely rather than half-grouped: that addon knows more
    about the match than this module does (it can offer actions on it), so two
    rows for one match would be worse than leaving its leftovers as plain rows.

    Returns groups in the same shape the hook produces, with no actions --
    this module has nothing to offer beyond the clustering itself.
    """
    by_match = {}
    for demo in demos:
        match_id = _match_id_of(demo['name'])
        if match_id:
            by_match.setdefault(match_id, []).append(demo)

    groups = []
    for match_id, members in by_match.items():
        # A single file is already one row; wrapping it in a collapsed group
        # would only add a click.
        if len(members) < 2:
            continue
        if any(m['name'] in claimed_names for m in members):
            continue

        map_name = ''
        for member in members:
            found = _POV_RE.match(member['name'])
            if found:
                map_name = found.group(1)
                break

        groups.append({
            'group_id': match_id,
            'label': f'{map_name} — {match_id}' if map_name else match_id,
            'addon_id': ADDON_ID,
            'member_names': [m['name'] for m in members],
            'actions': [],
        })
    return groups
