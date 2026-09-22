"""Reads whatever rating a plugin on the instance already wrote into the
server-status poller's blob (server:status:<host_id>:<instance_id> in
management Redis) -- no HTTP call, no credentials, nothing to configure.

Speculative (design doc "variant E"): nothing in this repo writes a
`rating` field per player into that blob today. Cheap to support anyway --
an instance with a plugin that does this needs no server_cfg wiring here,
just picking this source.
"""
from .base import RankProvider


class ServerStatusProvider(RankProvider):
    def map_game_type(self, qlsm_gametype):
        return qlsm_gametype  # no per-gametype distinction; whatever the blob carries is used as-is

    def fetch_ratings(self, steam_ids, game_type):
        players = self.extra.get('players') or []
        wanted = set(steam_ids)
        out = {}
        for player in players:
            if not isinstance(player, dict):
                continue
            steam_id = str(player.get('steam') or player.get('steamid') or player.get('steam_id') or '')
            if steam_id not in wanted:
                continue
            rating = player.get('rating')
            if rating is None:
                continue
            out[steam_id] = {
                'rating': float(rating) if isinstance(rating, (int, float)) else None,
                'display': str(rating),
                'provisional': False,
                'title': None,
            }
        return out
