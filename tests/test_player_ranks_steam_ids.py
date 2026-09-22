import sys
from pathlib import Path

ADDON_DIR = Path(__file__).resolve().parent.parent / 'addons' / 'player-ranks'
if str(ADDON_DIR) not in sys.path:
    sys.path.insert(0, str(ADDON_DIR))

from steam_ids import MAX_STEAM_IDS, parse_steam_ids  # noqa: E402

VALID = '76561197993968023'
VALID_2 = '76561197960287930'


def test_empty_input():
    assert parse_steam_ids('') == []
    assert parse_steam_ids(None) == []


def test_parses_comma_separated_ids():
    assert parse_steam_ids(f'{VALID},{VALID_2}') == [VALID, VALID_2]


def test_dedupes_preserving_first_occurrence_order():
    assert parse_steam_ids(f'{VALID_2},{VALID},{VALID_2}') == [VALID_2, VALID]


def test_drops_malformed_ids():
    assert parse_steam_ids(f'{VALID},not-a-steamid,123') == [VALID]


def test_strips_whitespace():
    assert parse_steam_ids(f' {VALID} , {VALID_2} ') == [VALID, VALID_2]


def test_caps_at_max_steam_ids():
    ids = [f'7656119{str(i).zfill(10)}' for i in range(MAX_STEAM_IDS + 20)]
    result = parse_steam_ids(','.join(ids))
    assert len(result) == MAX_STEAM_IDS
