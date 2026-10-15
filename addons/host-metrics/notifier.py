"""What host-metrics puts under qlsm's notification bell (spec B6). Pure and stdlib only.

backend.notify_check() fetches each host's snapshot and its events changed since the last
check, then calls the two functions here:

- handle_events(): an event opening -> ctx.notify(key), closing -> ctx.resolve(key).
  `seen` remembers which event ids were handled, so the one minute of overlap of every
  `events --since` query (ruling R4) and a long-open event closing days later never
  notify twice.
- handle_down(): collector stale or host unreachable for more than 5 minutes -> one
  critical notification, resolved once data is back. `down` carries the start of the
  outage between checks (kept in Redis, so a poller restart does not reset the clock).

Keys: host-metrics:<host_id>:<kind>:<scope>, scope `host`, `core:<n>` or `port:<n>`.
"""
import re

SEVERITY_RANK = {'info': 0, 'warning': 1, 'critical': 2}
KIND_SEVERITY = {
    'frames_late': 'warning',
    'core_saturated': 'warning',
    'steal_high': 'warning',
    'mem_low': 'warning',
    'oom_kill': 'critical',
    'disk_low': 'critical',
}
# notified only while players are on (an idle server lagging hurts nobody)
BUSY_KINDS = ('frames_late', 'core_saturated')
# opened and closed in the same collector tick: every new one is its own notification
POINT_KINDS = ('oom_kill',)
DOWN_KIND = 'stale'
DOWN_AFTER_SECONDS = 300
SEEN_MAX = 500

_CORE_RE = re.compile(r'\bcore (\d+)\b')


def passes(severity, min_severity):
    return SEVERITY_RANK.get(severity, 0) >= SEVERITY_RANK.get(min_severity, 1)


def link(host_id):
    return '/addons/host-metrics?host=%d' % host_id


def key(host_id, kind, scope):
    return 'host-metrics:%d:%s:%s' % (host_id, kind, scope)


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
    if kind == 'oom_kill':
        return ('%s: out-of-memory kill' % host_name,
                'The kernel killed a process because the host ran out of memory%s. '
                'A game server may have crashed.' % detail)
    if kind == 'disk_low':
        return ('%s: disk almost full' % host_name,
                'The root disk is almost full%s. Free some space before logs or demos '
                'fail to write.' % detail)
    return '%s: %s' % (host_name, kind), 'Host metrics reported %s%s.' % (kind, detail)


def handle_events(host_id, host_name, events, seen, snapshot, min_severity, notify, resolve,
                  now, overlap, on_error=None):
    """Notify / resolve for the events of one `events --since` answer (oldest change first).

    `seen` maps str(event id) -> closed_ts (None while open) of every event already
    handled; returned pruned. notify(severity, title, body, link, key) / resolve(key) may
    raise: on_error(event, exc) is called, the event keeps its previous state in `seen` and
    is retried while it is still in the window; the other events go on.
    """
    seen = dict(seen or {})
    for event in events or []:
        if not isinstance(event, dict):
            continue
        kind = event.get('kind')
        severity = KIND_SEVERITY.get(kind)
        event_id = _int(event.get('id'))
        if severity is None or event_id is None:
            continue
        try:
            _handle_one(host_id, host_name, event, kind, severity, str(event_id), seen,
                        snapshot, min_severity, notify, resolve)
        except Exception as exc:
            if on_error is not None:
                on_error(event, exc)
    return prune_seen(seen, now, overlap)


def _handle_one(host_id, host_name, event, kind, severity, sid, seen, snapshot, min_severity,
                notify, resolve):
    closed = event.get('state') == 'closed'
    closed_ts = event.get('closed_ts') if closed else None
    k = key(host_id, kind, scope_of(event))
    if sid in seen:
        if closed and seen[sid] is None:
            if kind not in POINT_KINDS:
                resolve(k)
            seen[sid] = closed_ts
        return
    wanted = passes(severity, min_severity)
    if wanted and kind in BUSY_KINDS:
        port = _int(event.get('port')) if kind == 'frames_late' else None
        wanted = players_on(snapshot, port)
    if wanted:
        title, body = event_text(host_name, event)
        if kind in POINT_KINDS:
            resolve(k)      # the previous one greys out; this one is new and unread
            notify(severity, title, body, link(host_id), k)
        else:
            notify(severity, title, body, link(host_id), k)
            if closed:
                resolve(k)
    seen[sid] = closed_ts


def prune_seen(seen, now, overlap):
    """Drop closed events that can no longer come back (closed before the next since);
    keep open ones (their close is still to come) and at most SEEN_MAX ids."""
    cutoff = (now - 2 * overlap) if isinstance(now, (int, float)) else None
    kept = {sid: closed for sid, closed in seen.items()
            if closed is None or cutoff is None
            or not isinstance(closed, (int, float)) or closed > cutoff}
    if len(kept) > SEEN_MAX:
        newest = sorted(kept, key=int)[-SEEN_MAX:]
        kept = {sid: kept[sid] for sid in newest}
    return kept


def handle_down(host_id, host_name, state, data_age, down, wall_now, min_severity, notify,
                resolve):
    """One host's stale / unreachable state -> the new `down` dict ({} when fine).

    `down` = {'since': wall clock start, 'reason': state, 'notified': bool}. For a stale
    collector the start is its newest data (now - data_age), so the 5 minutes count from
    when it stopped, not from when qlsm noticed.
    """
    k = key(host_id, DOWN_KIND, 'host')
    down = dict(down or {})
    if state not in ('unreachable', 'stale'):
        if down.get('notified'):
            resolve(k)
        return {}
    since = down.get('since')
    if not isinstance(since, (int, float)):
        since = wall_now
    if state == 'stale' and isinstance(data_age, (int, float)):
        since = min(since, wall_now - data_age)
    down.update(since=since, reason=state)
    age = wall_now - since
    if not down.get('notified') and age > DOWN_AFTER_SECONDS and passes('critical', min_severity):
        minutes = int(age // 60)
        if state == 'stale':
            title = '%s: metrics stopped' % host_name
            body = ('The host-metrics collector on this host has written no data for %d min. '
                    'Check that the host-metrics service is running.' % minutes)
        else:
            title = '%s: unreachable' % host_name
            body = ('QLSM has not reached this host over SSH for %d min. '
                    'Check that the host is up.' % minutes)
        notify('critical', title, body, link(host_id), k)
        down['notified'] = True
    return down
