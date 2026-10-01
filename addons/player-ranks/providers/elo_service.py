"""x76 (elo-service) adapter.

Ported from qlsm's rank-provider work (ui/rank_providers/elo_service.py),
which was verified against the ranked.py plugin:

  - bulk:   GET /players?ids=a,b,c&mode=<mode>  -> {steam_id: entry | null}
  - rating: sort_score or mu

`sort_score or mu` is copied from ranked.py's own !rank/!elo/!top10 commands,
Python `or` and all: a 0 sort_score means "not computed yet", not "score is
zero", so the fallback to mu is not optional.

One request covers the whole roster. The previous per-player loop held a web
worker for (players x timeout) whenever the service was unreachable.
"""
import requests

from .base import PROVIDER_TIMEOUT_SEC, RankProvider

# extra['display']: which field the Live Status column shows.
DISPLAY_FIELDS = ('sort_score', 'rank_label')
DEFAULT_DISPLAY = 'sort_score'


class ThunderdomeEloProvider(RankProvider):
    def map_game_type(self, qlsm_gametype):
        # The service's "mode" is an operator-defined pool name (e.g.
        # ffa_auto, ranked_duel) with no fixed enum to validate against --
        # identity mapping; an unknown pool simply returns nobody.
        gt = (qlsm_gametype or '').strip()
        return gt or None

    def fetch_ratings(self, steam_ids, game_type):
        if not steam_ids or not game_type or not self.base_url or not self.api_key:
            return {}
        # No try/except: a failed call must escape so ranks_service logs it
        # and caches the empty answer for TTL_NEGATIVE, not TTL_SUCCESS.
        resp = requests.get(
            f'{self.base_url}/players',
            params={'ids': ','.join(str(s) for s in steam_ids), 'mode': game_type},
            headers={'X-API-Key': self.api_key},
            timeout=PROVIDER_TIMEOUT_SEC,
        )
        if resp.status_code == 404:
            return {}
        resp.raise_for_status()
        body = resp.json()
        if not isinstance(body, dict):
            return {}

        show_label = self.extra.get('display') == 'rank_label'
        wanted = {str(s) for s in steam_ids}
        out = {}
        for steam_id, entry in body.items():
            steam_id = str(steam_id)
            # A null entry means the service knows nothing about that player.
            if steam_id not in wanted or not isinstance(entry, dict):
                continue
            value = entry.get('sort_score') or entry.get('mu')
            if value is None:
                continue
            try:
                rating = float(value)
            except (TypeError, ValueError):
                continue  # one bad value skips this player, not the source
            # A player with no label yet still gets the number, not a dash.
            label = entry.get('rank_label') if show_label else None
            display = label.strip() if isinstance(label, str) and label.strip() else f'{rating:g}'
            wins, losses = entry.get('wins'), entry.get('losses')
            title = f'{wins}-{losses}' if wins is not None and losses is not None else None
            out[steam_id] = {
                'rating': rating,
                'display': display,
                'provisional': False,
                'title': title,
            }
        return out
