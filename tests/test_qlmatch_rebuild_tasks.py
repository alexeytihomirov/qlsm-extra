"""qlmatch-packer rebuild tasks must report unexpected failures (SSH loss)
the same way they report a RebuildError, and a batch must carry on."""
import importlib

import pytest


@pytest.fixture
def addon_id():
    return 'qlmatch-packer'


@pytest.fixture
def tasks_mod(app, monkeypatch):
    mod = importlib.import_module('qlsm_addon_qlmatch_packer.rebuild_tasks')
    events = []
    monkeypatch.setattr(mod, 'publish_job_event', lambda source, status, message, **extra: events.append((status, message)))
    mod.events = events
    return mod


def _ssh_lost(instance_id, filename):
    raise OSError('ssh lost')


def test_sidecar_rebuild_reports_an_ssh_failure(tasks_mod, monkeypatch):
    monkeypatch.setattr(tasks_mod, 'rebuild_sidecar_logic', _ssh_lost)
    assert tasks_mod.rebuild_sidecar_task_logic(1, 'a.qlmatch') == {'ok': False, 'error': 'OSError: ssh lost'}
    assert tasks_mod.events == [('error', 'Sidecar rebuild failed for "a.qlmatch": OSError: ssh lost')]


def test_full_rebuild_reports_an_ssh_failure(tasks_mod, monkeypatch):
    monkeypatch.setattr(tasks_mod, 'rebuild_full_logic', _ssh_lost)
    assert tasks_mod.rebuild_full_task_logic(1, 'a.qlmatch') == {'ok': False, 'error': 'OSError: ssh lost'}
    assert tasks_mod.events == [('error', 'Full rebuild failed for "a.qlmatch": OSError: ssh lost')]


def test_rebuild_error_text_is_unchanged(tasks_mod, monkeypatch):
    def refuse(instance_id, filename):
        raise tasks_mod.RebuildError('no raw demos')
    monkeypatch.setattr(tasks_mod, 'rebuild_full_logic', refuse)
    assert tasks_mod.rebuild_full_task_logic(1, 'a.qlmatch') == {'ok': False, 'error': 'no raw demos'}


def test_batch_continues_after_an_ssh_failure(tasks_mod, monkeypatch):
    def logic(instance_id, filename):
        if filename == 'a.qlmatch':
            raise OSError('ssh lost')
        return {'filename': filename}
    monkeypatch.setitem(tasks_mod._KIND_LOGIC, 'full', logic)
    result = tasks_mod.rebuild_batch_task_logic(1, 'full', ['a.qlmatch', 'b.qlmatch'])
    assert result['ok'] is False
    assert result['results']['a.qlmatch'] == {'ok': False, 'error': 'OSError: ssh lost'}
    assert result['results']['b.qlmatch'] == {'ok': True, 'filename': 'b.qlmatch'}
    assert tasks_mod.events[-1] == ('error', 'Batch full rebuild finished: 1/2 succeeded.')


def test_batch_where_every_file_fails_still_sends_the_summary(tasks_mod, monkeypatch):
    monkeypatch.setitem(tasks_mod._KIND_LOGIC, 'sidecar', _ssh_lost)
    result = tasks_mod.rebuild_batch_task_logic(1, 'sidecar', ['a.qlmatch', 'b.qlmatch'])
    assert result['ok'] is False
    assert tasks_mod.events[-1] == ('error', 'Batch sidecar rebuild finished: 0/2 succeeded.')


def _records(caplog, tasks_mod):
    return [r for r in caplog.records if r.name == tasks_mod.log.name]


def test_batch_ssh_failure_is_logged_with_traceback(tasks_mod, monkeypatch, caplog):
    monkeypatch.setitem(tasks_mod._KIND_LOGIC, 'full', _ssh_lost)
    with caplog.at_level('DEBUG'):
        tasks_mod.rebuild_batch_task_logic(7, 'full', ['a.qlmatch'])
    (rec,) = _records(caplog, tasks_mod)
    assert rec.levelname == 'ERROR'
    assert rec.exc_info
    msg = rec.getMessage()
    assert 'full' in msg and '7' in msg and 'a.qlmatch' in msg and 'ssh lost' in msg


def test_batch_rebuild_error_is_logged_as_warning_without_traceback(tasks_mod, monkeypatch, caplog):
    def refuse(instance_id, filename):
        raise tasks_mod.RebuildError('no raw demos')
    monkeypatch.setitem(tasks_mod._KIND_LOGIC, 'full', refuse)
    with caplog.at_level('DEBUG'):
        tasks_mod.rebuild_batch_task_logic(7, 'full', ['a.qlmatch'])
    (rec,) = _records(caplog, tasks_mod)
    assert rec.levelname == 'WARNING'
    assert not rec.exc_info
    msg = rec.getMessage()
    assert 'full' in msg and '7' in msg and 'a.qlmatch' in msg and 'no raw demos' in msg


@pytest.mark.parametrize('fn,name', [('rebuild_sidecar_task_logic', 'rebuild_sidecar_logic'),
                                     ('rebuild_full_task_logic', 'rebuild_full_logic')])
def test_single_ssh_failure_is_logged_with_traceback(tasks_mod, monkeypatch, caplog, fn, name):
    monkeypatch.setattr(tasks_mod, name, _ssh_lost)
    with caplog.at_level('DEBUG'):
        getattr(tasks_mod, fn)(7, 'a.qlmatch')
    (rec,) = _records(caplog, tasks_mod)
    assert rec.levelname == 'ERROR' and rec.exc_info
    msg = rec.getMessage()
    assert '7' in msg and 'a.qlmatch' in msg and 'ssh lost' in msg
