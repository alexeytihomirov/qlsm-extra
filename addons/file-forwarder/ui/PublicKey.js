// The "File Forwarder SFTP key" settings section. A table cell cannot wrap a
// 100-character key line, so the section scrolled sideways; here the key is a
// wrapping block with a Copy button. Hand-written ESM, no build step, inline
// styles on qlsm's CSS variables (see HostPanel.js).

const styles = {
  text: { margin: '0 0 8px', fontSize: 13, color: 'var(--text-secondary)' },
  key: {
    margin: '0 0 8px', padding: '8px 10px', borderRadius: 6,
    border: '1px solid var(--surface-border)', background: 'var(--surface-base)',
    color: 'var(--text-primary)', fontSize: 12,
    fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
    whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', userSelect: 'all',
  },
  row: { display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 10 },
  note: { fontSize: 12, color: 'var(--text-muted)' },
};

export default function PublicKey({ ctx }) {
  const React = window.__qlsm.react;
  const { useEffect, useState } = React;
  const { Button } = ctx.ui;
  const h = React.createElement;

  const [state, setState] = useState({ loading: true });
  const [copied, setCopied] = useState(null);

  useEffect(() => {
    let alive = true;
    ctx.api('GET', 'public-key')
      .then((data) => { if (alive) setState({ key: data?.public_key || '' }); })
      .catch((err) => {
        if (alive) setState({ error: err?.response?.data?.error?.message || err?.message || 'Failed to load' });
      });
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(state.key);
      setCopied('Copied.');
    } catch (err) {
      setCopied('Could not copy; select the line and copy it by hand.');
    }
  };

  if (state.loading) return h('p', { style: styles.text }, 'Loading...');
  if (state.error) return h('p', { style: { ...styles.text, color: 'var(--accent-danger)' } }, state.error);

  return h('div', null,
    h('p', { style: styles.text },
      'The SFTP key of this QLSM install, generated on first use. Add this public line once to '
      + '/etc/ssh/authorized_keys.d/qldemos-in on the VPS. The private half never leaves QLSM except '
      + 'to the game hosts.'),
    h('div', { style: styles.key }, state.key),
    h('div', { style: styles.row },
      h(Button, { variant: 'secondary', onClick: copy }, 'Copy'),
      copied && h('span', { style: styles.note }, copied)));
}
