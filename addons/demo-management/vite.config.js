import { defineConfig } from 'vite';
import tailwindcss from '@tailwindcss/vite';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));

/**
 * Builds this addon's tier-2 component for QLSM (see qlsm's addons/README.md).
 *
 * Two things make it unusual for a Vite library build:
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
export default defineConfig({
  plugins: [tailwindcss()],
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
      entry: path.resolve(here, 'ui-src/Panel.jsx'),
      formats: ['es'],
      fileName: () => 'Panel.js',
    },
    rollupOptions: {
      output: { assetFileNames: 'Panel.css' },
    },
  },
});
