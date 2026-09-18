import React, { useState, useEffect, useCallback } from 'react';
import { CheckCircle2, XCircle, Loader2, RefreshCw } from 'lucide-react';
// This component now lives inside the addon that owns it, so it has no
// default data source: QLSM core no longer has telemetry endpoints to fall
// back to. `api` is supplied by the addon's mount wrapper and is required.
//
// Its modal chrome, buttons, panel surfaces and fields come from
// window.__qlsm.ui (see addons/UI-GUIDE.md) instead of hand-rolling a
// Headless UI dialog -- that duplication is what left this screen out of
// sync with the rest of QLSM (a one-off width fix, a plain-text token
// field) the last time it was touched.

function StatusBadge({ status, statusLoading }) {
    if (statusLoading) {
        return (
            <span className="inline-flex items-center gap-1.5 text-xs text-theme-muted">
                <Loader2 size={13} className="animate-spin" /> Checking...
            </span>
        );
    }
    if (!status || !status.enabled) {
        return <span className="text-xs text-theme-muted">Sidecar disabled</span>;
    }
    if (status.reachable) {
        return (
            <span className="inline-flex items-center gap-1.5 text-xs font-medium text-emerald-400">
                <CheckCircle2 size={13} /> Reachable
            </span>
        );
    }
    return (
        <span className="inline-flex items-center gap-1.5 text-xs font-medium" style={{ color: 'var(--accent-danger)' }}>
            <XCircle size={13} /> {status.error || 'Unreachable'}
        </span>
    );
}

function TelemetryRelayModal({ isOpen, onClose, onSubmit, host, api }) {
    const {
        Modal, Button, Panel: Card, AddonField, Icon, Stack, Row,
    } = window.__qlsm.ui;

    const [enabled, setEnabled] = useState(false);
    const [urlOverride, setUrlOverride] = useState('');
    const [tokenOverride, setTokenOverride] = useState('');
    const [effectiveUrl, setEffectiveUrl] = useState(null);
    const [status, setStatus] = useState(null);
    const [statusLoading, setStatusLoading] = useState(false);
    const [loaded, setLoaded] = useState(false);

    const refreshStatus = useCallback(async (hostId) => {
        setStatusLoading(true);
        try {
            const data = await api.getStatus(hostId);
            setStatus(data);
        } catch {
            setStatus(null);
        } finally {
            setStatusLoading(false);
        }
    }, [api]);

    useEffect(() => {
        if (!isOpen || !host) return;
        setLoaded(false);
        let cancelled = false;
        (async () => {
            try {
                const [relay, override] = await Promise.all([
                    api.getRelay(host.id),
                    api.getOverride(host.id),
                ]);
                if (cancelled) return;
                setEnabled(!!relay.enabled);
                setUrlOverride(override.url_override || '');
                setTokenOverride(override.ingest_token_override || '');
                setEffectiveUrl(override.effective_url || null);
            } finally {
                if (!cancelled) setLoaded(true);
            }
        })();
        refreshStatus(host.id);
        return () => { cancelled = true; };
    }, [isOpen, host, refreshStatus]);

    const handleSave = () => {
        onSubmit(host?.id, enabled, urlOverride.trim(), tokenOverride.trim());
        onClose();
    };

    const routedInstances = status?.routed_instances || [];

    return (
        <Modal
            isOpen={isOpen}
            onClose={onClose}
            title="Telemetry Relay"
            icon={<Icon name="radio" size={18} style={{ color: 'var(--accent-primary)' }} />}
            size="lg"
            footer={(
                <>
                    <Button variant="secondary" onClick={onClose}>Cancel</Button>
                    <Button variant="primary" onClick={handleSave} disabled={!loaded}>Save</Button>
                </>
            )}
        >
            <Stack gap={5}>
                <p className="text-sm text-theme-muted">
                    ql-telemetry-relay sidecar on <strong>{host?.name}</strong> forwards instance
                    telemetry to ql-stats-hub. Instances only talk to this local relay - the
                    stats-hub URL/ingest token live here, not on any instance.
                </p>

                <Card>
                    <Stack gap={1}>
                        <Row justify="between">
                            <span className="text-sm font-medium text-theme-primary">Sidecar Enabled</span>
                            <button
                                type="button"
                                onClick={() => setEnabled((v) => !v)}
                                className="neu-toggle"
                                aria-pressed={enabled}
                            >
                                <span className="sr-only">Toggle telemetry relay</span>
                                <span className={`neu-toggle__track ${enabled ? 'neu-toggle__track--on' : 'neu-toggle__track--off'}`}>
                                    <span className={`neu-toggle__knob ${enabled ? 'neu-toggle__knob--on' : 'neu-toggle__knob--off'}`} />
                                </span>
                            </button>
                        </Row>
                        <p className="text-xs text-theme-muted">
                            Installs and runs the ql-telemetry-relay sidecar process on this host.
                            Saving with this on (or off) installs (or removes) it and restarts the host's relay.
                        </p>
                    </Stack>
                </Card>

                <Card>
                    <Stack gap={2}>
                        <Row justify="between">
                            <span className="text-sm font-medium text-theme-primary">Status</span>
                            <Row gap={3}>
                                <StatusBadge status={status} statusLoading={statusLoading} />
                                <button
                                    type="button"
                                    onClick={() => host && refreshStatus(host.id)}
                                    disabled={statusLoading}
                                    className="text-theme-muted hover:text-theme-primary disabled:opacity-40"
                                    title="Refresh status"
                                >
                                    <RefreshCw size={13} className={statusLoading ? 'animate-spin' : ''} />
                                </button>
                            </Row>
                        </Row>
                        <div className="text-xs text-theme-muted">
                            {routedInstances.length === 0 && 'No instances routed through this relay yet.'}
                            {routedInstances.length > 0 && (
                                <ul className="space-y-0.5">
                                    {routedInstances.map((inst) => (
                                        <li key={inst.id} className="flex items-center justify-between">
                                            <span>{inst.name}</span>
                                            <span className="font-mono">#{inst.server_id}</span>
                                        </li>
                                    ))}
                                </ul>
                            )}
                        </div>
                    </Stack>
                </Card>

                <Stack gap={4} className="border-t border-theme pt-5">
                    <AddonField
                        field={{
                            key: 'url_override',
                            type: 'string',
                            label: 'Stats Hub URL Override',
                            placeholder: effectiveUrl ? `Inherits global: ${effectiveUrl}` : 'Not configured globally either',
                        }}
                        value={urlOverride}
                        disabled={!loaded}
                        onChange={(_key, value) => setUrlOverride(value)}
                    />
                    <AddonField
                        field={{
                            key: 'token_override',
                            type: 'secret',
                            label: 'Ingest Token Override',
                            placeholder: 'Blank = inherit the global ingest token',
                        }}
                        value={tokenOverride}
                        disabled={!loaded}
                        onChange={(_key, value) => setTokenOverride(value)}
                    />
                    <p className="text-xs text-theme-muted">
                        Leave both blank to use the cluster-wide stats-hub target from Settings.
                        Set either to point this host at a different stats-hub instance.
                    </p>
                </Stack>
            </Stack>
        </Modal>
    );
}

export default TelemetryRelayModal;
