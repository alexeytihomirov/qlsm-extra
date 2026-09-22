"""RankProvider contract every source (built-in or contributed through the
player_ranks.providers hook) implements.

A provider never raises for "this player has no rating" -- that is simply
absence from the returned dict. It may raise RateLimited when a source's own
throttling kicked in, so the caller can honor Retry-After instead of guessing
a backoff; anything else escaping fetch_ratings() is treated by ranks_service
as a transient failure (logged, empty result, short negative cache).
"""
from abc import ABC, abstractmethod

# Every outbound call a provider makes uses this. 3s matches balance.py/
# ranked.py's own timeouts to their respective services.
PROVIDER_TIMEOUT_SEC = 3


class RankProvider(ABC):
    def __init__(self, base_url=None, api_key=None, extra=None):
        self.base_url = (base_url or '').rstrip('/')
        self.api_key = (api_key or '').strip() or None
        self.extra = extra or {}

    @abstractmethod
    def map_game_type(self, qlsm_gametype):
        """This source's code for `qlsm_gametype`, or None if the source
        does not rate that game type at all (not an error -- just skip)."""

    @abstractmethod
    def fetch_ratings(self, steam_ids, game_type):
        """{steam_id(str): {'rating': float|None, 'display': str,
        'provisional': bool, 'title': str|None}} for whichever of
        `steam_ids` the source knows about. Missing players are simply
        absent from the dict, not an error."""


class RateLimited(Exception):
    """A source's own rate limit kicked in. `retry_after` is in seconds."""

    def __init__(self, retry_after=15):
        self.retry_after = max(1, int(retry_after))
        super().__init__(f'rate limited, retry after {self.retry_after}s')
