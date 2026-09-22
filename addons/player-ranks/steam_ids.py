"""Parses and validates the `steam_ids` query param the live_status_columns
route receives from core (a comma-joined, already-deduplicated-by-the-
frontend string, but never trust the client)."""
from ui.admin_permissions import STEAMID64_RE

MAX_STEAM_IDS = 64


def parse_steam_ids(raw):
    """Deduplicated, order-preserving, capped at MAX_STEAM_IDS. Anything not
    matching STEAMID64_RE is silently dropped -- a malformed id is not this
    endpoint's problem to report, just to ignore."""
    if not raw:
        return []
    seen = set()
    out = []
    for part in raw.split(','):
        steam_id = part.strip()
        if not steam_id or steam_id in seen or not STEAMID64_RE.match(steam_id):
            continue
        seen.add(steam_id)
        out.append(steam_id)
        if len(out) >= MAX_STEAM_IDS:
            break
    return out
