"""Suggests a starting config for an instance's 'Ranks' tab from cvars its
server.cfg already carries, if ranked.py wrote them there for its own
purposes. Never writes anything -- server.cfg is the authority, not
something this addon takes over.

qlstats has no per-instance suggestion: it's an installation-wide switch now
(settings.global, see backend.py), so there is no per-instance field left to
suggest a value into. Only Thunderdome elo-service -- still genuinely
per-instance -- gets suggested here.
"""
import os

from .cvar_text import read_cvars_from_text

_ELO_SERVICE_CVARS = ('qlx_rankedServiceUrl', 'qlx_rankedApiKey', 'qlx_rankedPool')


def _config_path(instance):
    if not instance.host:
        return None
    return os.path.join('configs', instance.host.name, str(instance.id), 'server.cfg')


def suggest_from_server_cfg(instance):
    """Best-effort {elo_service_enabled, elo_service_base_url, ...} guess
    from qlx_rankedServiceUrl and friends, or {} if server.cfg is missing or
    doesn't carry it."""
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

    return {}
