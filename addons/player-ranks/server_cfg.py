"""Suggests a starting config for an instance's 'Ranks' tab from cvars its
server.cfg already carries, if a plugin like balance.py or ranked.py wrote
them there for its own purposes. Never writes anything -- server.cfg is the
authority, not something this addon takes over.
"""
import os

from .cvar_text import read_cvars_from_text

_QLSTATS_CVARS = ('qlx_balanceUrl', 'qlx_balanceApi')
_ELO_SERVICE_CVARS = ('qlx_rankedServiceUrl', 'qlx_rankedApiKey', 'qlx_rankedPool')


def _config_path(instance):
    if not instance.host:
        return None
    return os.path.join('configs', instance.host.name, str(instance.id), 'server.cfg')


def suggest_from_server_cfg(instance):
    """Best-effort {<provider>_enabled, <provider>_base_url, ...} guess for
    whichever single source server.cfg's cvars point at, or {} if server.cfg
    is missing or carries none of the cvars this addon knows about.
    `qlstats_rating_system` is left for the operator to confirm --
    qlx_balanceApi's own values ('elo'/'elo_b') line up, but nothing here
    validates that."""
    path = _config_path(instance)
    if not path:
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            text = f.read()
    except OSError:
        return {}

    elo_cvars = read_cvars_from_text(text, _ELO_SERVICE_CVARS)
    if elo_cvars.get('qlx_rankedServiceUrl'):
        return {
            'elo_service_enabled': True,
            'elo_service_base_url': elo_cvars['qlx_rankedServiceUrl'],
            'elo_service_api_key': elo_cvars.get('qlx_rankedApiKey') or '',
            'elo_service_game_type': elo_cvars.get('qlx_rankedPool') or '',
        }

    qlstats_cvars = read_cvars_from_text(text, _QLSTATS_CVARS)
    if qlstats_cvars.get('qlx_balanceUrl'):
        url = qlstats_cvars['qlx_balanceUrl']
        if not url.startswith('http://') and not url.startswith('https://'):
            url = f'http://{url}'
        return {
            'qlstats_enabled': True,
            'qlstats_base_url': url,
            'qlstats_rating_system': qlstats_cvars.get('qlx_balanceApi') or 'elo',
        }

    return {}
