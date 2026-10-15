// Server Ping page. Hand-written ESM on window.__qlsm (no build step, no bundled
// React): the shared DTLS certificate (fingerprint + one-time Generate) and one
// row per host with its switch, a status check and Apply.
export default function Page({ ctx }) {
  const React = window.__qlsm.react;
  const { useCallback, useEffect, useState } = React;
  const { Button, Panel: Card, Stack, Row } = ctx.ui;
  const h = React.createElement;

  const [fp, setFp] = useState(null);
  const [hosts, setHosts] = useState([]);
  const [rows, setRows] = useState({});
  const [message, setMessage] = useState(null);
  const [busy, setBusy] = useState(false);

  const errorText = (err, fallback) => err?.response?.data?.error?.message || fallback;
  const setRow = (id, patch) => setRows(prev => ({ ...prev, [id]: { ...(prev[id] || {}), ...patch } }));

  const load = useCallback(async () => {
    try {
      setFp(await ctx.api('GET', 'fingerprint'));
      const data = await ctx.api('GET', 'hosts');
      setHosts(data?.hosts || []);
    } catch (err) {
      setMessage(errorText(err, 'Failed to load.'));
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const generate = async () => {
    setBusy(true);
    try {
      setFp(await ctx.api('POST', 'generate-cert'));
      setMessage('Certificate generated. Put the fingerprint into the ql-tournament env (PING_DTLS_FINGERPRINT) and Apply to every host.');
    } catch (err) {
      setMessage(errorText(err, 'Failed to generate the certificate.'));
    } finally {
      setBusy(false);
    }
  };

  const toggle = async (host) => {
    try {
      const data = await ctx.api('PUT', `hosts/${host.id}`, { data: { enabled: !host.enabled } });
      setHosts(prev => prev.map(x => (x.id === host.id ? { ...x, enabled: data.enabled } : x)));
      setRow(host.id, { note: 'Saved; Apply to take effect on the host.' });
    } catch (err) {
      setRow(host.id, { note: errorText(err, 'Failed to save.') });
    }
  };

  const check = async (host) => {
    setRow(host.id, { note: 'Checking...' });
    try {
      const s = await ctx.api('GET', `hosts/${host.id}/status`);
      const parts = [
        s.service || 'unknown',
        s.firewall === true ? 'port open' : s.firewall === false ? 'port closed' : 'port unknown',
        s.version ? `v${s.version}${s.version === s.expected_version ? '' : ` (addon ${s.expected_version})`}` : 'not installed',
      ];
      if (s.fingerprint) parts.push(s.fingerprint === s.expected_fingerprint ? 'cert ok' : 'cert differs');
      setRow(host.id, { note: s.error || parts.join(', ') });
    } catch (err) {
      setRow(host.id, { note: errorText(err, 'Status failed.') });
    }
  };

  const apply = async (host) => {
    try {
      const data = await ctx.api('POST', `hosts/${host.id}/apply`);
      setRow(host.id, { note: data?.message || 'Apply queued.' });
    } catch (err) {
      setRow(host.id, { note: errorText(err, 'Apply failed.') });
    }
  };

  const mono = { fontFamily: 'ui-monospace, monospace', wordBreak: 'break-all', userSelect: 'all' };

  return h(Stack, { gap: 4 },
    h(Card, null,
      h('h3', { className: 'font-display text-lg text-theme-primary mb-2' }, 'DTLS certificate'),
      fp?.fingerprint
        ? h(Stack, { gap: 1 },
          h('p', { className: 'text-sm text-theme-secondary' }, 'Shared by every host. ql-tournament env PING_DTLS_FINGERPRINT:'),
          h('code', { className: 'text-sm text-theme-primary', style: mono }, fp.fingerprint))
        : h(Row, { gap: 3 },
          h('p', { className: 'text-sm text-theme-secondary' }, fp?.error || 'No certificate yet.'),
          h(Button, { variant: 'primary', disabled: busy, onClick: generate }, 'Generate certificate')),
      message && h('p', { className: 'mt-2 text-sm text-theme-secondary' }, message)),
    h(Card, null,
      h('h3', { className: 'font-display text-lg text-theme-primary mb-2' }, 'Hosts'),
      hosts.length === 0 && h('p', { className: 'text-sm text-theme-muted' }, 'No hosts.'),
      ...hosts.map(host => h(Row, { key: host.id, gap: 3, className: 'py-1', wrap: true },
        h('label', { className: 'flex items-center gap-2 text-sm text-theme-primary', style: { minWidth: '12rem' } },
          h('input', { type: 'checkbox', checked: Boolean(host.enabled), onChange: () => toggle(host) }),
          host.name),
        h(Button, { variant: 'secondary', onClick: () => check(host) }, 'Status'),
        h(Button, { variant: 'primary', onClick: () => apply(host) }, 'Apply'),
        h('span', { className: 'text-xs text-theme-muted' }, rows[host.id]?.note || '')))),
  );
}
