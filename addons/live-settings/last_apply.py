"""The last apply per instance, kept so the operator can come back later and
see what was sent, what the engine answered and how server.cfg changed.

One JSON file per instance under data/addons/live-settings/. `data/` is the
bind mount every qlsm container shares and that survives an image update
(the same reason the operator plugin pool lives there); the instance's own
configs/ directory is out of the question because it is synchronised to the
game host as a whole.
"""
import json
import os
import time

STORE_DIR = os.path.join('data', 'addons', 'live-settings')
KEEP_LAST = 20


def _path(instance_id):
    return os.path.join(STORE_DIR, f'instance-{int(instance_id)}.json')


def load(instance_id):
    """{"applies": [newest first]} or an empty history."""
    try:
        with open(_path(instance_id), 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {'applies': []}
    applies = data.get('applies') if isinstance(data, dict) else None
    return {'applies': applies if isinstance(applies, list) else []}


def record(instance_id, entry):
    """Prepend `entry` (stamped with `at`) and keep the last few."""
    entry = dict(entry)
    entry.setdefault('at', time.time())
    history = load(instance_id)
    history['applies'] = [entry] + history['applies'][:KEEP_LAST - 1]
    os.makedirs(STORE_DIR, exist_ok=True)
    tmp = _path(instance_id) + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(history, f, ensure_ascii=False, indent=1)
    os.replace(tmp, _path(instance_id))
    return entry
