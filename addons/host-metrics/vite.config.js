import { defineConfig } from 'vite';
import tailwindcss from '@tailwindcss/vite';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));

/**
 * Builds this addon's two tier-2 components (Page, HostPanel) for QLSM (see qlsm's addons/README.md).
 *
 * Two things make it unusual for a Vite library build:
 *
 * 0. Both entries import one panel.css; the build writes it as Page.css and HostPanel.css.
 *    A shared chunk (uPlot, charts, format) is split out by Rollup; QLSM loads
 *    each component with a plain import(), which follows the relative chunk import.
 *
 * 1. React is NOT bundled and NOT a rollup "external" either. An external
 *    would leave a bare `import ... from "react"` in the output, which the
 *    browser cannot resolve -- QLSM loads this file with a plain dynamic
 *    import(), not through a bundler or an import map. So `react` is aliased
 *    to src/runtime.js, which reads QLSM's own React off window.__qlsm. Two
 *    React copies on one page break hooks; this is how that is avoided while
 *    still shipping a single self-contained file.
 *
 * 2. Tailwind runs over this addon's sources only (see src/panel.css). QLSM's
 *    compiled CSS cannot cover them: its own Tailwind build scans
 *    frontend-react/src, and this addon is not in that tree.
 *
 * No @vitejs/plugin-react: without React Fast Refresh or the automatic JSX
 * runtime (which would import 'react/jsx-runtime', a second bare specifier to
 * shim), esbuild's plain JSX transform is all this needs.
 */
/**
 * QLSM links `<component>.css` next to each component by convention (Page.js -> Page.css,
 * HostPanel.js -> HostPanel.css; see qlsm's addonCss.js). Both entries share one stylesheet,
 * so the single CSS asset Vite emits is written out once per entry name and the original removed.
 */
const cssPerEntry = {
  name: 'hm-css-per-entry',
  // writeBundle, not generateBundle: Vite adds its CSS asset to the bundle after the
  // generateBundle hooks of ordinary plugins have run.
  writeBundle(options, bundle) {
    for (const [file, asset] of Object.entries(bundle)) {
      if (asset.type !== 'asset' || !file.endsWith('.css')) continue;
      for (const name of ['Page', 'HostPanel']) {
        fs.writeFileSync(path.join(options.dir, `${name}.css`), asset.source);
      }
      fs.rmSync(path.join(options.dir, file));
    }
  },
};

export default defineConfig({
  plugins: [tailwindcss(), cssPerEntry],
  resolve: {
    alias: { react: path.resolve(here, 'ui-src/runtime.js') },
  },
  esbuild: {
    jsx: 'transform',
    jsxFactory: 'React.createElement',
    jsxFragment: 'React.Fragment',
  },
  build: {
    outDir: 'ui',
    emptyOutDir: false,
    cssCodeSplit: false,
    // Readable output: this file is committed, and a reviewer comparing it
    // against ui-src/ should be able to follow it.
    minify: false,
    lib: {
      entry: {
        Page: path.resolve(here, 'ui-src/Page.jsx'),
        HostPanel: path.resolve(here, 'ui-src/HostPanel.jsx'),
      },
      formats: ['es'],
      fileName: (_format, name) => `${name}.js`,
    },
    rollupOptions: {
      output: { chunkFileNames: 'hm-shared.js' },
    },
  },
});
