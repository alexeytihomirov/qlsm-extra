"""Thunderdome elo-service adapter, matching the ranked.py plugin
(configs/presets/_builtin/default-minqlxtended/scripts/ranked.py in the
qlsm monorepo) since no live instance of the service itself was available to
verify against directly (design doc section 13).

`sort_score or mu` is copied from ranked.py's own !rank/!elo/!top10 commands
verbatim, Python `or` and all: a 0 sort_score means "not computed yet", not
"score is zero", so the fallback to mu is not optional. There is no `rating`
key anywhere in this service's responses.
"""
import requests

from .base import PROVIDER_TIMEOUT_SEC, RankProvider


class ThunderdomeEloProvider(RankProvider):
    def map_game_type(self, qlsm_gametype):
        # The service's "mode" is an operator-defined pool name (e.g.
        # ffa_auto, ranked_duel) with no fixed enum to validate against --
        # identity mapping; an unknown pool 404s per player instead.
        gt = (qlsm_gametype or '').strip()
        return gt or None

    def fetch_ratings(self, steam_ids, game_type):
        if not steam_ids or not game_type or not self.base_url or not self.api_key:
            return {}
        headers = {'X-API-Key': self.api_key}
        out = {}
        for steam_id in steam_ids:
            try:
                resp = requests.get(
                    f'{self.base_url}/player/{steam_id}',
                    params={'mode': game_type},
                    headers=headers,
                    timeout=PROVIDER_TIMEOUT_SEC,
                )
            except requests.RequestException:
                continue
            if resp.status_code == 404:
                continue
            try:
                resp.raise_for_status()
                data = resp.json()
            except (requests.RequestException, ValueError):
                continue
            if not isinstance(data, dict):
                continue
            score = data.get('sort_score') or data.get('mu')
            if score is None:
                continue
            wins, losses = data.get('wins'), data.get('losses')
            title = f'{wins}-{losses}' if wins is not None and losses is not None else None
            out[str(steam_id)] = {
                'rating': float(score),
                'display': str(int(score)),
                'provisional': False,
                'title': title,
            }
        return out
