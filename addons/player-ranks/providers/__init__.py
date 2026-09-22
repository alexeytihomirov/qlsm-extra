"""Provider registry: the 4 built-in sources plus whatever a separately
distributed addon contributes through the player_ranks.providers hook
(addons/README.md, "Cross-addon UI contribution").

A contributed provider is fully usable end to end: `settings.instance.provider`
is declared `type: string` in the manifest (not `select`) specifically so
ctx.settings.set() does not statically constrain it, and
update_instance_config() validates the write against build_registry() below
-- the live merged registry, not a fixed list. The Ranks tab's own dropdown
still only *offers* the 4 built-ins (a declarative select needs a fixed
option list to render), so picking a contributed provider today means
setting it through the API rather than that dropdown -- but nothing stops
storing or fetch_ranks() from using it once set.
"""
from .base import RankProvider, RateLimited
from .elo_service import ThunderdomeEloProvider
from .qlstats import QlstatsProvider
from .server_status import ServerStatusProvider
from .slipgate import SlipgateProvider

BUILTIN_PROVIDERS = {
    'qlstats': {
        'label': 'qlstats',
        'factory': QlstatsProvider,
        'requires_api_key': False,
    },
    'slipgate': {
        'label': 'Slipgate',
        'factory': SlipgateProvider,
        'requires_api_key': False,
    },
    'elo_service': {
        'label': 'Thunderdome elo-service',
        'factory': ThunderdomeEloProvider,
        'requires_api_key': True,
    },
    'server_status': {
        'label': "From the game server's own status data",
        'factory': ServerStatusProvider,
        'requires_api_key': False,
    },
}


def build_registry():
    """Built-ins merged with player_ranks.providers contributions, own
    entries winning on a duplicate id -- same merge-order-and-conflicts rule
    as demo_management's hooks (addons/README.md)."""
    from flask import current_app
    from ui.addons import dispatch

    registry = dict(BUILTIN_PROVIDERS)
    for contribution in dispatch('player_ranks.providers', 0):
        try:
            provider_id = contribution['id']
            factory = contribution['factory']
        except (KeyError, TypeError):
            current_app.logger.warning(
                'player-ranks: malformed player_ranks.providers contribution: %r', contribution)
            continue
        if provider_id in registry:
            current_app.logger.warning(
                'player-ranks: player_ranks.providers contributed duplicate id "%s", ignored', provider_id)
            continue
        registry[provider_id] = {
            'label': contribution.get('label') or provider_id,
            'factory': factory,
            'requires_api_key': bool(contribution.get('requires_api_key')),
        }
    return registry


__all__ = ['RankProvider', 'RateLimited', 'BUILTIN_PROVIDERS', 'build_registry']
