// The host menu dialog: the host switch, the forwarder's status and its
// actions in one place. Hand-written ESM with no build step: React and the UI
// kit come from window.__qlsm, styling is inline with qlsm's CSS variables
// (addons/UI-GUIDE.md in qlsm), so there is no Panel.css and no Tailwind.
//
// The status table has a fixed layout with wrapping cells (the last-run line
// is long), and the actions are buttons in a wrapping row below it, so the
// dialog never scrolls sideways.

const PURGE_CONFIRM = 'Sync now, then delete delivered demo files from this host, whatever their age: '
  + '.qlmatch and .replay.json.gz only when the VPS lists them, .dm_91 when the VPS lists them or '
  + 'they were delivered more than 24 hours ago (the NAS has pulled them). Everything else stays '
  + 'on the host. Continue?';

const ACTIONS = [
  { id: 'apply', label: 'Apply to host', variant: 'primary' },
  { id: 'sync', label: 'Sync now', variant: 'secondary' },
  { id: 'purge', label: 'Sync now and delete delivered', variant: 'danger', confirm: PURGE_CONFIRM },
];

const SWITCH_FIELD = {
  key: 'enabled',
  type: 'bool',
  label: "Forward this host's demos",
  description: 'Whether host setup installs and updates the forwarder on this host. Turning it off '
    + 'stops future installs; it does not remove a forwarder already on the host.',
};

const COLUMNS = [
  { label: 'Installed version', width: '17%' },
  { label: 'State', width: '21%' },
  { label: 'Timer', width: '14%' },
  { label: 'Last run', width: '48%' },
];

const MONO ='ui-monospace, SFMono-Regular, Menlo, Consolas, monospace';

const styles = {
  section: { marginTop: 16, paddingTop: 16, borderTop: '1px solid var(--surface-border)' },
  heading: { margin: '0 0 8px', fontSize: 13, fontWeight: 600, color: 'var(--text-secondary)' },
  tableWrap: { border: '1px solid var(--surface-border)', borderRadius: 6, overflow: 'hidden' },
  // Fixed layout + wrapping cells: the table always fits the dialog's width.
  table: { width: '100%', tableLayout: 'fixed', borderCollapse: 'collapse', fontSize: 14 },
  th: {
    padding: '8px 12px', textAlign: 'left', fontWeight: 500,
    color: 'var(--text-secondary)', overflowWrap: 'anywhere',
  },
  td: {
    padding: '8px 12px', verticalAlign: 'top', color: 'var(--text-primary)', overflowWrap: 'anywhere',
  },
  buttons: { display: 'flex', flexWrap: 'wrap', gap: 8 },
  muted: { margin: 0, fontSize: 13, color: 'var(--text-muted)' },
  hint: { margin: '10px 0 0', fontSize: 12, color: 'var(--text-muted)' },
};

function errorMessage(err, fallback) {
  return err?.response?.data?.error?.message || err?.message || fallback;
}

export default function HostPanel({ ctx }) {
  const React = window.__qlsm.react;
  const { useCallback, useEffect, useRef, useState } = React;
  const { Modal, Button, AddonField } = ctx.ui;
  const h = React.createElement;

  const hostId = ctx.scope.id;
  const hostName = ctx.modal?.entity?.name;

  const [enabled, setEnabled] = useState(null);
  const [status, setStatus] = useState({ loading: true });
  const [busy, setBusy] = useState(null);
  const [notice, setNotice] = useState(null);
  const alive = useRef(true);

  useEffect(() => {
    alive.current = true;
    return () => { alive.current = false; };
  }, []);

  const loadStatus = useCallback(async () => {
    setStatus({ loading: true });
    try {
      const data = await ctx.api('GET', `hosts/${hostId}/status`);
      if (alive.current) setStatus({ row: (data?.rows || [])[0] || null });
    } catch (err) {
      if (alive.current) setStatus({ error: errorMessage(err, 'Failed to read the status.') });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hostId]);

  useEffect(() => {
    ctx.api('GET', `hosts/${hostId}`)
      .then((data) => { if (alive.current) setEnabled(Boolean(data?.enabled)); })
      .catch((err) => {
        if (alive.current) setNotice({ error: true, text: errorMessage(err, 'Failed to load the host switch.') });
      });
    loadStatus();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hostId, loadStatus]);

  const saveSwitch = async (_key, value) => {
    const previous = enabled;
    setEnabled(value);
    setBusy('switch');
    setNotice(null);
    try {
      await ctx.api('PUT', `hosts/${hostId}`, { data: { enabled: value } });
      if (alive.current) setNotice({ text: value ? 'Forwarding is on for this host.' : 'Forwarding is off for this host.' });
    } catch (err) {
      if (alive.current) {
        setEnabled(previous);
        setNotice({ error: true, text: errorMessage(err, 'Failed to save.') });
      }
    } finally {
      if (alive.current) setBusy(null);
    }
  };

  const runAction = async (action) => {
    if (action.confirm && !window.confirm(action.confirm)) return;
    setBusy(action.id);
    setNotice(null);
    try {
      const data = await ctx.api('POST', `hosts/${hostId}/${action.id}`);
      if (alive.current) {
        setNotice({ text: `${data?.message || 'Queued.'} Press Refresh when it has finished.` });
      }
    } catch (err) {
      if (alive.current) setNotice({ error: true, text: errorMessage(err, 'Action failed.') });
    } finally {
      if (alive.current) setBusy(null);
    }
  };

  const row = status.row;
  const warn = { color: 'var(--accent-warning)' };
  let statusBody;
  if (status.loading) {
    statusBody = h('p', { style: styles.muted }, 'Reading the status from the host...');
  } else if (status.error) {
    statusBody = h('p', { style: { ...styles.muted, color: 'var(--accent-danger)' } }, status.error);
  } else if (!row) {
    statusBody = h('p', { style: styles.muted }, 'No status.');
  } else {
    const cells = [
      row.version,
      [row.state, row.state === 'up to date' ? null : warn],
      [row.timer, row.timer === 'active' ? null : warn],
      [row.last_run, { fontFamily: MONO, fontSize: 12 }],
    ].map((cell) => (Array.isArray(cell) ? cell : [cell, null]));
    statusBody = h('div', { style: styles.tableWrap },
      h('table', { style: styles.table },
        h('colgroup', null, ...COLUMNS.map((col) => h('col', { key: col.label, style: { width: col.width } }))),
        h('thead', null,
          h('tr', { style: { background: 'var(--surface-elevated)' } },
            ...COLUMNS.map((col) => h('th', { key: col.label, style: styles.th }, col.label)))),
        h('tbody', null,
          h('tr', { style: { borderTop: '1px solid var(--surface-border)' } },
            ...cells.map(([value, valueStyle], i) => h('td', {
              key: COLUMNS[i].label, style: { ...styles.td, ...valueStyle },
            }, value || '-'))))));
  }

  return h(Modal, {
    isOpen: Boolean(ctx.modal?.isOpen),
    onClose: ctx.modal?.onClose,
    title: hostName ? `File Forwarder - ${hostName}` : 'File Forwarder',
    size: 'xl',
    footer: h(Button, { variant: 'secondary', onClick: ctx.modal?.onClose }, 'Close'),
  },
  h('div', null,
    enabled === null
      ? h('p', { style: styles.muted }, 'Loading...')
      : h(AddonField, {
        field: SWITCH_FIELD, value: enabled, disabled: busy !== null, onChange: saveSwitch,
      }),

    h('div', { style: styles.section },
      h('h4', { style: styles.heading }, 'Forwarder on this host'),
      statusBody),

    h('div', { style: styles.section },
      h('div', { style: styles.buttons },
        ...ACTIONS.map((action) => h(Button, {
          key: action.id,
          variant: action.variant,
          disabled: busy !== null,
          onClick: () => runAction(action),
        }, busy === action.id ? 'Queuing...' : action.label)),
        h(Button, {
          key: 'refresh', variant: 'secondary', disabled: Boolean(status.loading), onClick: loadStatus,
        }, 'Refresh')),
      notice && h('p', {
        style: { ...styles.hint, fontSize: 13, color: notice.error ? 'var(--accent-danger)' : 'var(--text-primary)' },
      }, notice.text),
      h('p', { style: styles.hint },
        'Apply to host installs or updates the forwarder (after an addon update or a settings change). '
        + 'Sync now and delete delivered removes .qlmatch and .replay.json.gz only when the VPS lists them, '
        + '.dm_91 when the VPS lists them or they were delivered more than 24 hours ago; the rest stays '
        + 'and is counted as kept_unconfirmed.'))));
}
