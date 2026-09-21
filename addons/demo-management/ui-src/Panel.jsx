import React from './runtime';
import ViewDemosModal from './ViewDemosModal';
import './panel.css';

/**
 * Tier-2 entry point: the addon's own component, mounted by QLSM with a
 * single `ctx` prop (see qlsm's addons/README.md).
 *
 * The manifest declares `"renders": "modal"` for this mount point, so core
 * skips its generic dialog shell and this component renders the whole
 * dialog -- that is what keeps the Demos screen exactly as wide, as tall and
 * as equipped (filter, date range, "N of M", Refresh) as it was when it was
 * part of QLSM itself. `ctx.modal` carries the open/close state and the
 * instance the menu entry was opened from.
 *
 * All this wrapper does is adapt `ctx` to the data source ViewDemosModal
 * expects -- the component itself has no idea it is inside an addon.
 */
function Panel({ ctx }) {
    const modal = ctx?.modal || {};

    const api = React.useMemo(() => ({
        list: (instanceId) => ctx.api('GET', `instances/${instanceId}/demos`),

        downloadOne: async (instanceId, name) => {
            const { blob } = await ctx.download(
                'GET',
                `instances/${instanceId}/demos/download?filename=${encodeURIComponent(name)}`,
                { fallbackName: name },
            );
            return blob;
        },

        downloadBatch: async (instanceId, names) => {
            const { blob } = await ctx.download(
                'POST', `instances/${instanceId}/demos/download-batch`,
                { data: { filenames: names }, fallbackName: 'demos.zip' },
            );
            return blob;
        },

        // Match-group actions (e.g. qlmatch-packer's Rebuild buttons) are
        // contributed by another addon via the demo_management.match_groups
        // hook and carry their own `addon_id` + relative route -- this addon
        // has no idea what the action does, only how to call it.
        runAction: (addonId, method, path, data) => (
            ctx.apiFor(addonId)(method, path, { data })
        ),
    }), [ctx]);

    return (
        <ViewDemosModal
            isOpen={Boolean(modal.isOpen)}
            onClose={modal.onClose}
            instance={modal.entity}
            api={api}
        />
    );
}

export default Panel;
