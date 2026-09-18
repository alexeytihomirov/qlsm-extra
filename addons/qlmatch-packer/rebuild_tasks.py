"""RQ task bodies for the rebuild endpoints in backend.py.

Separate from rebuild_ops.py (which stays pure request/response logic that
raises RebuildError) so that module does not also need to know about
ui.job_events -- this thin layer's only job is to translate a rebuild's
outcome into one job:completed toast per unit of work.
"""
import logging

from ui.job_events import publish_job_event

from .rebuild_ops import RebuildError, rebuild_full_logic, rebuild_sidecar_logic

log = logging.getLogger(__name__)

_SOURCE = 'qlmatch-packer.rebuild'


def rebuild_sidecar_task_logic(instance_id, filename):
    try:
        result = rebuild_sidecar_logic(instance_id, filename)
    except RebuildError as e:
        log.warning('Sidecar rebuild failed for instance %s, %s: %s', instance_id, filename, e)
        publish_job_event(_SOURCE, 'error', f'Sidecar rebuild failed for "{filename}": {e}',
                           instance_id=instance_id, filename=filename)
        return {'ok': False, 'error': str(e)}

    publish_job_event(_SOURCE, 'success', f'Rebuilt replay sidecar for "{filename}".',
                       instance_id=instance_id, filename=filename)
    return {'ok': True, **result}


def rebuild_full_task_logic(instance_id, filename):
    try:
        result = rebuild_full_logic(instance_id, filename)
    except RebuildError as e:
        log.warning('Full rebuild failed for instance %s, %s: %s', instance_id, filename, e)
        publish_job_event(_SOURCE, 'error', f'Full rebuild failed for "{filename}": {e}',
                           instance_id=instance_id, filename=filename)
        return {'ok': False, 'error': str(e)}

    publish_job_event(_SOURCE, 'success', f'Fully rebuilt "{filename}" from raw demos.',
                       instance_id=instance_id, filename=filename)
    return {'ok': True, **result}


_KIND_LOGIC = {
    'sidecar': rebuild_sidecar_logic,
    'full': rebuild_full_logic,
}


def rebuild_batch_task_logic(instance_id, kind, filenames):
    """Runs every filename sequentially under the one instance lock the
    caller already acquired -- a batch is a maintenance operation the
    operator explicitly asked for, not something that benefits from partial
    concurrency against the same host. Each item gets its own toast so
    progress is visible without waiting for the whole batch; a final summary
    event covers anyone who only cares about the overall result."""
    logic = _KIND_LOGIC[kind]
    results = {}
    failures = 0
    for filename in filenames:
        try:
            results[filename] = {'ok': True, **logic(instance_id, filename)}
            publish_job_event(_SOURCE, 'success', f'Rebuilt "{filename}" ({kind}).',
                               instance_id=instance_id, filename=filename)
        except RebuildError as e:
            failures += 1
            results[filename] = {'ok': False, 'error': str(e)}
            log.warning('Batch %s rebuild failed for instance %s, %s: %s', kind, instance_id, filename, e)
            publish_job_event(_SOURCE, 'error', f'Rebuild failed for "{filename}": {e}',
                               instance_id=instance_id, filename=filename)

    ok_count = len(filenames) - failures
    summary_status = 'error' if failures else 'success'
    publish_job_event(
        _SOURCE, summary_status,
        f'Batch {kind} rebuild finished: {ok_count}/{len(filenames)} succeeded.',
        instance_id=instance_id,
    )
    return {'ok': failures == 0, 'results': results}
