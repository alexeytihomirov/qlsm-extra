"""Slipgate (slipgate.gg) adapter.

Verified against the live openapi.json + live requests 2026-09-22 (design
doc section 9.7). Three corrections to the original integration plan:

- `display` is an integer ("Player-facing rating number"), never a
  formatted string like "1650 (Gold)" -- the tier label is the separate
  `tier_name` field, which we put in `title` instead.
- An API key is optional, not required: `GET /players/{id}/ratings/{gt}` is
  public (no `security` in the spec, confirmed with a live request), so a
  key-less setup falls back to one request per player instead of the bulk
  endpoint.
- Slipgate rate-limits (429 + Retry-After) and that is not documented in the
  original plan; RateLimited carries the header value up to ranks_service
  rather than this adapter guessing a backoff.

Re-checked against the live openapi.json 2026-09-30: `POST /ratings/bulk`
now replies `{"ok", "game_type", "rating_set", "players": [...]}` rather than
the bare list this file originally assumed, which silently dropped every
bulk (keyed) response -- see BulkRatingsOut in the spec. `_fetch_bulk` below
accepts either shape.
"""
import requests

from .base import PROVIDER_TIMEOUT_SEC, RankProvider, RateLimited

DEFAULT_BASE_URL = 'https://slipgate.gg'
DEFAULT_NEGATIVE_TTL = 15

# Static fallback for GET /api/v1/gametypes ("rated": true entries) -- see
# design doc 9.7. A live daily refresh is a nice-to-have this pass skips;
# this table matches the response captured 2026-09-22.
GAMETYPE_ALIASES = {'har': 'harvester', 'dom': 'domination', 'rr': 'redrover', '1f': '1flag'}
RATED_GAMETYPES = {
    'ca', 'duel', 'ctf', 'ft', 'tdm', 'ffa', 'ad', 'domination', 'harvester', '1flag', 'redrover',
}


def _retry_after_seconds(response):
    try:
        return max(1, int(response.headers.get('Retry-After', DEFAULT_NEGATIVE_TTL)))
    except (TypeError, ValueError):
        return DEFAULT_NEGATIVE_TTL


class SlipgateProvider(RankProvider):
    def __init__(self, base_url=None, api_key=None, extra=None):
        super().__init__(base_url, api_key, extra)
        if not self.base_url:
            self.base_url = DEFAULT_BASE_URL

    def map_game_type(self, qlsm_gametype):
        gt = (qlsm_gametype or '').strip().lower()
        mapped = GAMETYPE_ALIASES.get(gt, gt)
        return mapped if mapped in RATED_GAMETYPES else None

    def fetch_ratings(self, steam_ids, game_type):
        if not steam_ids or not game_type:
            return {}
        if self.api_key:
            return self._fetch_bulk(steam_ids, game_type)
        return self._fetch_public(steam_ids, game_type)

    def _fetch_bulk(self, steam_ids, game_type):
        # No try/except around the call: see qlstats.py -- a failure must
        # escape to ranks_service to be logged and negatively cached.
        resp = requests.post(
            f'{self.base_url}/api/v1/ratings/bulk',
            json={'steam_ids': steam_ids, 'game_type': game_type},
            headers={'Authorization': f'Bearer {self.api_key}'},
            timeout=PROVIDER_TIMEOUT_SEC,
        )
        if resp.status_code == 429:
            raise RateLimited(_retry_after_seconds(resp))
        resp.raise_for_status()
        body = resp.json()
        # Live response is {"ok", "game_type", "rating_set", "players": [...]},
        # not a bare list -- confirmed against the current openapi.json
        # (BulkRatingsOut). A bare list is still accepted.
        items = body.get('players') if isinstance(body, dict) else body
        if not isinstance(items, list):
            return {}

        wanted = set(steam_ids)
        out = {}
        for item in items:
            if not isinstance(item, dict) or not item.get('found'):
                continue
            steam_id = str(item.get('steam_id') or '')
            display = item.get('display')
            if steam_id not in wanted or display is None:
                continue
            out[steam_id] = _result(item)
        return out

    def _fetch_public(self, steam_ids, game_type):
        out = {}
        last_error = None
        for steam_id in steam_ids:
            try:
                resp = requests.get(
                    f'{self.base_url}/api/v1/players/{steam_id}/ratings/{game_type}',
                    timeout=PROVIDER_TIMEOUT_SEC,
                )
            except requests.RequestException as e:
                # Unreachable or timed out: stop here, because every player
                # left would wait out the same timeout while a web worker is
                # held. What was already fetched is still returned below.
                last_error = e
                break
            if resp.status_code == 429:
                raise RateLimited(_retry_after_seconds(resp))
            if resp.status_code == 404:
                continue
            try:
                resp.raise_for_status()
                data = resp.json()
            except (requests.RequestException, ValueError) as e:
                # One player's lookup failing says nothing about the next
                # one, and an answered request costs no timeout: skip it.
                last_error = e
                continue
            if not isinstance(data, dict) or data.get('display') is None:
                continue
            out[str(steam_id)] = _result(data)
        if not out and last_error is not None:
            # Nothing fetched and something failed is a failing source, not
            # an empty roster: let ranks_service log it and cache it briefly.
            raise last_error
        return out

def _result(data):
    mu = data.get('mu')
    return {
        'rating': float(mu) if mu is not None else None,
        'display': str(data['display']),
        'provisional': bool(data.get('provisional')),
        'title': data.get('tier_name') or None,
    }
