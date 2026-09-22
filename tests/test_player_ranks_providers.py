"""Unit tests for the rating-source adapters, importable standalone (no
Flask app, no qlsm checkout needed for these specific classes -- they only
touch `requests` and the abc-based RankProvider contract).
"""
import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

ADDON_DIR = Path(__file__).resolve().parent.parent / 'addons' / 'player-ranks'
if str(ADDON_DIR) not in sys.path:
    sys.path.insert(0, str(ADDON_DIR))

from providers.base import RateLimited  # noqa: E402
from providers.elo_service import ThunderdomeEloProvider  # noqa: E402
from providers.qlstats import QlstatsProvider  # noqa: E402
from providers.server_status import ServerStatusProvider  # noqa: E402
from providers.slipgate import SlipgateProvider  # noqa: E402


def _resp(status_code=200, json_data=None, headers=None):
    resp = Mock()
    resp.status_code = status_code
    resp.headers = headers or {}
    resp.json.return_value = json_data if json_data is not None else {}
    if status_code >= 400:
        import requests
        resp.raise_for_status.side_effect = requests.HTTPError(response=resp)
    else:
        resp.raise_for_status.side_effect = None
    return resp


# ---- qlstats -------------------------------------------------------------

class TestQlstats:
    def test_rated_gametypes_map_to_themselves(self):
        p = QlstatsProvider()
        for gt in ('duel', 'ffa', 'ca', 'tdm', 'ctf', 'ft', 'ad'):
            assert p.map_game_type(gt) == gt

    def test_unrated_gametype_is_none(self):
        p = QlstatsProvider()
        assert p.map_game_type('har') is None
        assert p.map_game_type('race') is None

    def test_games_zero_is_treated_as_no_data_not_elo_900(self):
        """The qlstats default-for-unknown-player shape, not a real rating."""
        p = QlstatsProvider(base_url='http://qlstats.example')
        payload = {'players': [
            {'steamid': '76561197993968023', 'duel': {'games': 13732, 'elo': 2181}},
            {'steamid': '76561197960287930', 'duel': {'games': 0, 'elo': 900}},
        ]}
        with patch('providers.qlstats.requests.get', return_value=_resp(json_data=payload)):
            result = p.fetch_ratings(['76561197993968023', '76561197960287930'], 'duel')

        assert result['76561197993968023']['display'] == '2181'
        assert '76561197960287930' not in result

    def test_empty_steam_ids_short_circuits(self):
        p = QlstatsProvider()
        assert p.fetch_ratings([], 'duel') == {}

    def test_no_game_type_short_circuits(self):
        p = QlstatsProvider()
        assert p.fetch_ratings(['76561197993968023'], None) == {}

    def test_network_failure_returns_empty(self):
        import requests
        p = QlstatsProvider()
        with patch('providers.qlstats.requests.get', side_effect=requests.ConnectionError()):
            assert p.fetch_ratings(['76561197993968023'], 'duel') == {}

    def test_rating_system_defaults_to_elo_and_is_used_in_url(self):
        p = QlstatsProvider(base_url='http://qlstats.example')
        with patch('providers.qlstats.requests.get', return_value=_resp(json_data={'players': []})) as mock_get:
            p.fetch_ratings(['76561197993968023'], 'duel')
        assert mock_get.call_args[0][0] == 'http://qlstats.example/elo/76561197993968023'

    def test_rating_system_override(self):
        p = QlstatsProvider(base_url='http://qlstats.example', extra={'rating_system': 'elo_b'})
        with patch('providers.qlstats.requests.get', return_value=_resp(json_data={'players': []})) as mock_get:
            p.fetch_ratings(['76561197993968023'], 'duel')
        assert '/elo_b/' in mock_get.call_args[0][0]


# ---- slipgate --------------------------------------------------------

class TestSlipgate:
    def test_gametype_aliases(self):
        p = SlipgateProvider()
        assert p.map_game_type('har') == 'harvester'
        assert p.map_game_type('dom') == 'domination'
        assert p.map_game_type('rr') == 'redrover'
        assert p.map_game_type('1f') == '1flag'
        assert p.map_game_type('duel') == 'duel'

    def test_unrated_gametype_is_none(self):
        p = SlipgateProvider()
        assert p.map_game_type('1fctf') is None
        assert p.map_game_type('ictf') is None

    def test_display_is_used_verbatim_and_tier_name_goes_to_title(self):
        p = SlipgateProvider(base_url='http://sg.example', api_key='sg_test')
        payload = [{'steam_id': '76561197993968023', 'found': True, 'display': 2561,
                    'tier_name': 'Elite', 'mu': 25.1, 'provisional': False}]
        with patch('providers.slipgate.requests.post', return_value=_resp(json_data=payload)):
            result = p.fetch_ratings(['76561197993968023'], 'duel')
        assert result['76561197993968023'] == {
            'rating': 25.1, 'display': '2561', 'provisional': False, 'title': 'Elite',
        }

    def test_unfound_player_is_skipped(self):
        p = SlipgateProvider(base_url='http://sg.example', api_key='sg_test')
        payload = [{'steam_id': '76561197993968023', 'found': False, 'display': None}]
        with patch('providers.slipgate.requests.post', return_value=_resp(json_data=payload)):
            result = p.fetch_ratings(['76561197993968023'], 'duel')
        assert result == {}

    def test_without_key_uses_public_per_player_endpoint(self):
        p = SlipgateProvider(base_url='http://sg.example')
        payload = {'display': 1650, 'tier_name': 'Gold', 'mu': 18.0, 'provisional': True}
        with patch('providers.slipgate.requests.get', return_value=_resp(json_data=payload)) as mock_get, \
             patch('providers.slipgate.requests.post') as mock_post:
            result = p.fetch_ratings(['76561197993968023'], 'duel')
        mock_post.assert_not_called()
        assert mock_get.call_args[0][0] == 'http://sg.example/api/v1/players/76561197993968023/ratings/duel'
        assert result['76561197993968023']['display'] == '1650'
        assert result['76561197993968023']['provisional'] is True

    def test_public_404_means_unranked(self):
        p = SlipgateProvider(base_url='http://sg.example')
        with patch('providers.slipgate.requests.get', return_value=_resp(status_code=404)):
            result = p.fetch_ratings(['76561197993968023'], 'duel')
        assert result == {}

    def test_429_raises_rate_limited_with_retry_after(self):
        p = SlipgateProvider(base_url='http://sg.example', api_key='sg_test')
        with patch('providers.slipgate.requests.post',
                   return_value=_resp(status_code=429, headers={'Retry-After': '42'})):
            with pytest.raises(RateLimited) as exc_info:
                p.fetch_ratings(['76561197993968023'], 'duel')
        assert exc_info.value.retry_after == 42

    def test_429_without_header_falls_back_to_default(self):
        p = SlipgateProvider(base_url='http://sg.example')
        with patch('providers.slipgate.requests.get', return_value=_resp(status_code=429)):
            with pytest.raises(RateLimited) as exc_info:
                p.fetch_ratings(['76561197993968023'], 'duel')
        assert exc_info.value.retry_after == 15


# ---- elo_service -------------------------------------------------------

class TestThunderdomeElo:
    def test_map_game_type_is_identity(self):
        p = ThunderdomeEloProvider()
        assert p.map_game_type('ffa_auto') == 'ffa_auto'
        assert p.map_game_type('') is None

    def test_no_key_or_base_url_short_circuits_without_a_request(self):
        p = ThunderdomeEloProvider(base_url='http://elo.example')  # no api_key
        with patch('providers.elo_service.requests.get') as mock_get:
            result = p.fetch_ratings(['76561197993968023'], 'ffa_auto')
        mock_get.assert_not_called()
        assert result == {}

    def test_sort_score_or_mu_uses_python_or_semantics(self):
        """sort_score=0 is falsy -- must fall back to mu, not report 0."""
        p = ThunderdomeEloProvider(base_url='http://elo.example', api_key='key123')
        payload = {'sort_score': 0, 'mu': 27.4, 'wins': 3, 'losses': 1}
        with patch('providers.elo_service.requests.get', return_value=_resp(json_data=payload)):
            result = p.fetch_ratings(['76561197993968023'], 'ffa_auto')
        assert result['76561197993968023']['display'] == '27'
        assert result['76561197993968023']['title'] == '3-1'

    def test_sort_score_nonzero_is_preferred_over_mu(self):
        p = ThunderdomeEloProvider(base_url='http://elo.example', api_key='key123')
        payload = {'sort_score': 1500, 'mu': 27.4}
        with patch('providers.elo_service.requests.get', return_value=_resp(json_data=payload)):
            result = p.fetch_ratings(['76561197993968023'], 'ffa_auto')
        assert result['76561197993968023']['display'] == '1500'

    def test_404_means_no_record(self):
        p = ThunderdomeEloProvider(base_url='http://elo.example', api_key='key123')
        with patch('providers.elo_service.requests.get', return_value=_resp(status_code=404)):
            result = p.fetch_ratings(['76561197993968023'], 'ffa_auto')
        assert result == {}

    def test_sends_api_key_header(self):
        p = ThunderdomeEloProvider(base_url='http://elo.example', api_key='key123')
        with patch('providers.elo_service.requests.get',
                   return_value=_resp(json_data={'sort_score': 10})) as mock_get:
            p.fetch_ratings(['76561197993968023'], 'ffa_auto')
        assert mock_get.call_args.kwargs['headers'] == {'X-API-Key': 'key123'}


# ---- server_status -------------------------------------------------------

class TestServerStatus:
    def test_reads_rating_from_players_blob(self):
        p = ServerStatusProvider(extra={'players': [
            {'steam': '76561197993968023', 'rating': 1234},
            {'steam': '76561197960287930'},  # no rating field
        ]})
        result = p.fetch_ratings(['76561197993968023', '76561197960287930'], 'duel')
        assert result == {'76561197993968023': {
            'rating': 1234.0, 'display': '1234', 'provisional': False, 'title': None,
        }}

    def test_no_players_blob_is_empty(self):
        p = ServerStatusProvider()
        assert p.fetch_ratings(['76561197993968023'], 'duel') == {}
