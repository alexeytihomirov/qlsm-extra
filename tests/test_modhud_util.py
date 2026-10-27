"""modhud_util: tokens, field building and the cs sender of the shared HUD panel."""
import pytest

from tests._minqlx_stub import import_plugin

pytestmark = pytest.mark.standalone

mu = import_plugin("modhud_util")


@pytest.fixture(autouse=True)
def clean_clients():
    for state in (mu.CLIENT, mu.PENDING, mu.HAS_PANEL, mu.CENTRE, mu.INGAME):
        state.clear()
    yield
    for state in (mu.CLIENT, mu.PENDING, mu.HAS_PANEL, mu.CENTRE, mu.INGAME):
        state.clear()


def cps(engine):
    return [cmd for _, cmd in engine.commands if cmd.startswith("cp ")]


def test_small_digits_and_back():
    assert mu.small("1/2 x") == " x"
    assert mu.small("09") == ""
    assert mu.plain(mu.small("10/2")) == "10/2"


def test_plain_turns_glyphs_into_labels():
    assert mu.plain(mu.expand("^3{mh}^7 0:35 {ra} {on}{off} ━╭")) == "^3MH^7 0:35 RA █░ ─┌"
    assert mu.plain(mu.expand("{rl} 1/2")) == "RL 1/2"


def test_client_command_marks_the_panel():
    assert mu.client_command(3, "modhud 1") is True
    assert mu.has_panel(3)
    assert mu.client_command(3, "say hi") is False
    mu.forget(3)
    assert not mu.has_panel(3)


def test_centre_copy_for_a_joined_client_without_the_panel():
    engine, sent = Engine(), {}
    mu.loaded(3)
    mu.send(engine, sent, 3, mu.fields(["{rl} 1/2"]), "")
    assert cps(engine) == []  # not in the game yet: Join Match is open, the hello may still come
    mu.joined(3)
    mu.send(engine, sent, 3, mu.fields(["{rl} 1/2", "x"]), "")
    assert cps(engine) == ['cp "RL 1/2\nx"']
    mu.send(engine, sent, 3, mu.fields(["{rl} 1/2", "x"]), "")
    assert len(cps(engine)) == 1  # unchanged text: no new centre print
    mu.send(engine, sent, 3, mu.blank(), "")
    assert len(cps(engine)) == 1  # a blank prints nothing


def test_no_centre_copy_with_the_panel():
    engine, sent = Engine(), {}
    mu.loaded(3)
    mu.client_command(3, "modhud 1")
    mu.joined(3)
    mu.send(engine, sent, 3, mu.fields(["{rl} 1/2"]), "")
    assert cps(engine) == [] and engine.commands


class Engine:
    CS_SYSTEMINFO = 1

    def __init__(self, refuse=False, raise_=False):
        self.commands = []
        self.refuse = refuse
        self.raise_ = raise_

    def send_server_command(self, cid, cmd):
        if self.raise_:
            raise ValueError("gone")
        if self.refuse:
            return False
        self.commands.append((cid, cmd))
        return True


def test_expand_tokens():
    assert mu.expand("{rl} 1/2") == " 1/2"
    assert mu.expand("{mh}{ra}") == ""
    assert mu.expand("{on}{off}") == "▰▱"
    assert mu.expand("{{rl}") == "{rl}"
    assert mu.expand("{nope} x") == "{nope} x"


def test_token_table_matches_spec():
    weapons = ["g", "mg", "sg", "gl", "rl", "lg", "rg", "pg", "bfg", "gh", "ng", "pl", "cg", "hmg"]
    items = ["mh", "ra", "ya", "ga", "shard", "quad", "bs", "regen", "haste", "invis", "flight", "flag"]
    for i, name in enumerate(weapons):
        assert mu.TOKENS[name] == chr(0xE000 + i)
    for i, name in enumerate(items):
        assert mu.TOKENS[name] == chr(0xE010 + i)
    assert len(mu.TOKENS) == len(weapons) + len(items) + 2


def test_fit_cuts_on_char_boundary():
    assert len(mu.fit("Ж" * 100).encode("utf-8")) == 120
    cut = mu.fit("a" + "" * 50)
    assert len(cut.encode("utf-8")) == 118
    assert cut == "a" + "" * 39
    assert mu.fit("short") == "short"


def test_fields_expand_clean_fit_and_pad():
    assert mu.fields(["a"]) == {"mod_hud_on": "1", "mod_hud_l1": "a", "mod_hud_l2": "", "mod_hud_l3": ""}
    out = mu.fields(['{rl} a"b;c\\d', "2", "3", "4"])
    assert out["mod_hud_l1"] == " abcd"
    assert out["mod_hud_l3"] == "3" and len(out) == 4
    assert len(mu.fields(["x" * 200])["mod_hud_l1"]) == 120


def test_blank_and_diff():
    assert mu.blank() == {"mod_hud_on": "0", "mod_hud_l1": "", "mod_hud_l2": "", "mod_hud_l3": ""}
    assert mu.diff({}, mu.blank()) == {}
    assert mu.diff(dict.fromkeys(mu.FIELDS), mu.blank()) == mu.blank()
    shown = mu.fields(["a"])
    assert mu.diff(shown, mu.fields(["b"])) == {"mod_hud_l1": "b"}


def test_command_keeps_field_order_and_cleans():
    cmd = mu.command(1, "\\sv_pure\\1", {"mod_hud_l1": 'a"b', "mod_hud_on": "1"})
    assert cmd == 'cs 1 "\\sv_pure\\1\\mod_hud_on\\1\\mod_hud_l1\\ab"'


FULL_A = 'cs 1 "\\mod_hud_on\\1\\mod_hud_l1\\a\\mod_hud_l2\\\\mod_hud_l3\\"'


def test_send_records_show_and_drops_on_blank():
    engine, sent = Engine(), {}
    mu.send(engine, sent, 3, mu.fields(["a"]), "")
    assert sent[3] == mu.fields(["a"]) and mu.CLIENT[3] == mu.fields(["a"])
    mu.send(engine, sent, 3, mu.fields(["a"]), "")
    assert len(engine.commands) == 1  # nothing changed
    mu.send(engine, sent, 3, mu.fields(["b"]), "")
    assert engine.commands[-1][1] == 'cs 1 "\\mod_hud_l1\\b"'
    mu.send(engine, sent, 3, mu.blank(), "")
    assert 3 not in sent
    assert engine.commands[-1][1] == 'cs 1 "\\mod_hud_on\\0\\mod_hud_l1\\"'


def test_first_show_sends_every_field():
    # Lines left by another server or plugin must not show next to ours.
    engine = Engine()
    mu.send(engine, {}, 3, mu.fields(["a"]), "")
    assert engine.commands == [(3, FULL_A)]


def test_reset_clients_resends_in_full():
    # Join Match hides the panel on every map load: what the client shows is unknown again.
    engine, sent = Engine(), {}
    mu.send(engine, sent, 3, mu.fields(["a"]), "")
    mu.reset_clients()
    mu.send(engine, sent, 3, mu.fields(["a"]), "")
    assert engine.commands == [(3, FULL_A), (3, FULL_A)]
    assert mu.needs_send(sent, 3, mu.fields(["a"])) is False


def test_two_plugins_share_the_client_state():
    engine, game, admin = Engine(), {}, {}
    mu.send(engine, game, 3, mu.fields(["x"]), "")
    mu.send(engine, admin, 3, mu.fields(["", "hello"]), "")
    assert engine.commands[-1][1] == 'cs 1 "\\mod_hud_l1\\\\mod_hud_l2\\hello"'
    mu.send(engine, game, 3, mu.fields(["x"]), "")
    assert engine.commands[-1][1] == 'cs 1 "\\mod_hud_l1\\x\\mod_hud_l2\\"'


def test_blank_from_a_plugin_that_never_showed_sends_nothing():
    engine = Engine()
    mu.send(engine, {}, 3, mu.fields(["x"]), "")
    mu.send(engine, {}, 3, mu.blank(), "")
    assert len(engine.commands) == 1


def test_long_command_is_cut_under_the_engine_limit():
    info = "\\k\\" + "v" * 700
    engine = Engine()
    mu.send(engine, {}, 3, mu.fields(["Ж" * 60] * 3), info)
    cmd = engine.commands[0][1]
    assert len(cmd.encode("utf-8")) + 1 <= mu.MAX_COMMAND_BYTES
    assert cmd.startswith('cs 1 "' + info + "\\mod_hud_on\\1\\mod_hud_l1\\")
    assert mu.CLIENT[3]["mod_hud_l1"] in cmd


def test_send_blank_to_never_shown_sends_nothing():
    engine, sent = Engine(), {}
    mu.send(engine, sent, 3, mu.blank(), "")
    assert engine.commands == [] and sent == {}


@pytest.mark.parametrize("engine", [Engine(refuse=True), Engine(raise_=True)])
def test_send_refused_marks_full_resend(engine):
    sent = {}
    mu.send(Engine(), sent, 3, mu.fields(["a"]), "")
    mu.send(engine, sent, 3, mu.fields(["b"]), "")
    assert mu.CLIENT[3] == dict.fromkeys(mu.FIELDS)
    assert mu.needs_send(sent, 3, mu.fields(["b"])) is True
    ok = Engine()
    mu.send(ok, sent, 3, mu.fields(["a"]), "")
    assert ok.commands[0][1] == FULL_A


def test_refused_blank_is_retried():
    sent = {}
    mu.send(Engine(), sent, 3, mu.fields(["a"]), "")
    mu.send(Engine(refuse=True), sent, 3, mu.blank(), "")
    ok = Engine()
    mu.send(ok, sent, 3, mu.blank(), "")
    assert ok.commands[0][1] == 'cs 1 "\\mod_hud_on\\0\\mod_hud_l1\\\\mod_hud_l2\\\\mod_hud_l3\\"'
    assert 3 not in sent


def test_loaded_then_joined_resends_in_full_once():
    # Live (#26, 2026-10-27): Join Match opens after player_loaded and its onOpen hides the
    # panel sent on load, so the first spawn / team join after a load sends it all again.
    engine, sent = Engine(), {}
    mu.loaded(3)
    mu.client_command(3, "modhud 1")  # has the panel: no centre copy in this test
    mu.send(engine, sent, 3, mu.fields(["a"]), "")
    assert mu.joined(3) is True
    mu.send(engine, sent, 3, mu.fields(["a"]), "")
    assert engine.commands == [(3, FULL_A), (3, FULL_A)]
    assert mu.joined(3) is False
    mu.send(engine, sent, 3, mu.fields(["a"]), "")
    assert len(engine.commands) == 2


def test_forget_drops_the_client():
    mu.send(Engine(), {}, 3, mu.fields(["a"]), "")
    mu.loaded(3)
    mu.forget(3)
    assert 3 not in mu.CLIENT and 3 not in mu.PENDING
