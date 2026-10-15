"""What host-metrics puts under qlsm's notification bell (spec B6, ruling R8). Pure, stdlib only.

State-based reconciliation, once a minute: backend.notify_check() fetches each enabled host's
snapshot and asks the functions here for the DESIRED notifications (key -> severity, title,
body). Every desired key is notified (ctx.notify with a key updates the open row in place);
an open host-metrics notification whose key stayed out of the desired set for
ABSENT_CHECKS_TO_RESOLVE checks in a row is resolved (a condition that flaps for one check
neither resolves nor reopens), and one of a host that was switched off or deleted is
resolved at once. A missed close, a failed resolve and a long outage all heal on the next
check, and the first check notifies what is open now without replaying history.

Desired, per host:
- the snapshot's open events (`events_open`) of the notified kinds: frames_late and
  core_saturated only while players are on, steal_high / mem_low warning, disk_low critical;
- oom_kill (closed by the collector the moment it is recorded): critical while the
  snapshot's `events_24h` counts an OOM kill in the last 24 hours;
- `stale` critical when the collector is stale or the host unreachable for more than
  5 minutes (the start of the outage is kept in Redis by the backend).
A host whose snapshot is missing or has no `events_open` (unreachable, stale, a 1.0
collector) is "unknown": its event keys are left as they are until it answers again.

Keys: host-metrics:<host_id>:<kind>:<scope>, scope `host`, `core:<n>` or `port:<n>`.
"""
import re

SEVERITY_RANK = {'info': 0, 'warning': 1, 'critical': 2}
KIND_SEVERITY = {
    'frames_late': 'warning',
    'core_saturated': 'warning',
    'steal_high': 'warning',
    'mem_low': 'warning',
    'disk_low': 'critical',
}
OOM_KIND = 'oom_kill'
OOM_SEVERITY = 'critical'
# notified only while players are on (an idle server lagging hurts nobody)
BUSY_KINDS = ('frames_late', 'core_saturated')
DOWN_KIND = 'stale'
DOWN_AFTER_SECONDS = 300
ABSENT_CHECKS_TO_RESOLVE = 2
KEY_PREFIX = 'host-metrics:'
FRESH_STATES = ('ok', 'outdated')

_CORE_RE = re.compile(r'\bcore (\d+)\b')


def passes(severity, min_severity):
    return SEVERITY_RANK.get(severity, 0) >= SEVERITY_RANK.get(min_severity, 1)


def link(host_id):
    return '/addons/host-metrics?host=%d' % host_id


def key(host_id, kind, scope):
    return '%s%d:%s:%s' % (KEY_PREFIX, host_id, kind, scope)


def down_key(host_id):
    return key(host_id, DOWN_KIND, 'host')


def host_of_key(k):
    """Host id of one of our keys, None for anything else."""
    if not isinstance(k, str) or not k.startswith(KEY_PREFIX):
        return None
    part = k[len(KEY_PREFIX):].split(':', 1)[0]
    return int(part) if part.isascii() and part.isdigit() else None


def _int(value):
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def scope_of(event):
    """`port:<n>` for an instance event, `core:<n>` for a core event (the number is only in
    the collector's message), `host` otherwise."""
    scope = event.get('scope')
    port = _int(event.get('port'))
    if scope == 'instance' and port is not None:
        return 'port:%d' % port
    if scope == 'core':
        match = _CORE_RE.search(event.get('message') or '')
        return 'core:%s' % match.group(1) if match else 'core'
    return 'host'


def players_on(snapshot, port=None):
    """Some instance (or the one on `port`) has players in the snapshot's latest rows."""
    rows = (snapshot or {}).get('insts_last') or []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if port is not None and row.get('port') != port:
            continue
        players = _int(row.get('players'))
        if players is not None and players > 0:
            return True
    return False


def _detail(event):
    message = (event.get('message') or '').strip()
    return ' (%s)' % message if message else ''


def event_text(host_name, event):
    """(title, body) of an event notification: short title, one or two plain sentences."""
    kind = event.get('kind')
    scope = scope_of(event)
    detail = _detail(event)
    if kind == 'frames_late':
        where = 'port %s' % scope[5:] if scope.startswith('port:') else 'an instance'
        return ('%s: late frames on %s' % (host_name, where),
                'The game server on %s is running late frames while players are on%s. '
                'Players see hitches.' % (where, detail))
    if kind == 'core_saturated':
        core = 'CPU core %s' % scope[5:] if scope.startswith('core:') else 'CPU core'
        return ('%s: %s saturated' % (host_name, core),
                '%s stayed above the saturation limit while players are on%s. '
                'Matches on it may lag.' % (core, detail))
    if kind == 'steal_high':
        return ('%s: high CPU steal' % host_name,
                'The hypervisor is taking CPU time away from this host%s. '
                'Game servers may stutter.' % detail)
    if kind == 'mem_low':
        return ('%s: memory low' % host_name,
                'Available memory is below the limit%s. '
                'The kernel may start killing processes.' % detail)
    if kind == 'disk_low':
        return ('%s: disk almost full' % host_name,
                'The root disk is almost full%s. Free some space before logs or demos '
                'fail to write.' % detail)
    return '%s: %s' % (host_name, kind), 'Host metrics reported %s%s.' % (kind, detail)


def oom_text(host_name, count):
    kills = '1 out-of-memory kill' if count == 1 else '%d out-of-memory kills' % count
    return ('%s: out-of-memory kill' % host_name,
            'The kernel killed a process because the host ran out of memory '
            '(%s in the last 24 hours). A game server may have crashed.' % kills)


def host_events_desired(host_id, host_name, snapshot, min_severity):
    """{key: (severity, title, body)} from a fresh snapshot, or None when the host's open
    events are unknown (no snapshot, or a collector without `events_open`)."""
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get('events_open'), list):
        return None
    desired = {}
    for event in snapshot['events_open']:
        if not isinstance(event, dict):
            continue
        kind = event.get('kind')
        severity = KIND_SEVERITY.get(kind)
        if severity is None or not passes(severity, min_severity):
            continue
        if kind in BUSY_KINDS:
            port = _int(event.get('port')) if kind == 'frames_late' else None
            if not players_on(snapshot, port):
                continue
        title, body = event_text(host_name, event)
        desired[key(host_id, kind, scope_of(event))] = (severity, title, body)
    counts = snapshot.get('events_24h')
    ooms = _int(counts.get(OOM_KIND)) if isinstance(counts, dict) else None
    if ooms and ooms > 0 and passes(OOM_SEVERITY, min_severity):
        title, body = oom_text(host_name, ooms)
        desired[key(host_id, OOM_KIND, 'host')] = (OOM_SEVERITY, title, body)
    return desired


def down_update(host_id, host_name, state, data_age, down, wall_now, min_severity):
    """(new `down` dict, desired item or None) for one host's stale / unreachable state.

    `down` = {'since': wall clock start of the outage}; {} when the host answers. For a
    stale collector the start is its newest data (now - data_age), so the 5 minutes count
    from when it stopped, not from when qlsm noticed.
    """
    if state not in ('unreachable', 'stale'):
        return {}, None
    since = (down or {}).get('since')
    if not isinstance(since, (int, float)):
        since = wall_now
    if state == 'stale' and isinstance(data_age, (int, float)):
        since = min(since, wall_now - data_age)
    down = {'since': since}
    age = wall_now - since
    if age <= DOWN_AFTER_SECONDS or not passes('critical', min_severity):
        return down, None
    minutes = int(age // 60)
    if state == 'stale':
        title = '%s: metrics stopped' % host_name
        body = ('The host-metrics collector on this host has written no data for %d min. '
                'Check that the host-metrics service is running.' % minutes)
    else:
        title = '%s: unreachable' % host_name
        body = ('QLSM has not reached this host over SSH for %d min. '
                'Check that the host is up.' % minutes)
    return down, ('critical', title, body)


def reconcile(desired, active_hosts, unknown_hosts, open_keys, absent):
    """Which open keys to resolve now, and the new absent counts.

    desired: keys wanted this check; active_hosts: ids of enabled hosts checked this time;
    unknown_hosts: of those, the ones whose event keys are unknown (only their down key is
    judged); open_keys: keys of our open notifications (None when they cannot be read:
    nothing is resolved); absent: {key: consecutive checks absent}.
    """
    if open_keys is None:
        return [], dict(absent or {})
    resolve, counts = [], {}
    for k in sorted(open_keys):
        host_id = host_of_key(k)
        if host_id is None:
            continue
        if host_id not in active_hosts:
            resolve.append(k)           # switched off, deleted, or notifications off
            continue
        if k in desired:
            continue
        if host_id in unknown_hosts and k != down_key(host_id):
            if k in (absent or {}):
                counts[k] = absent[k]
            continue
        count = (absent or {}).get(k, 0) + 1
        if count >= ABSENT_CHECKS_TO_RESOLVE:
            resolve.append(k)
        counts[k] = count
    return resolve, counts
