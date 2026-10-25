import { defineConfig } from 'vite';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));

/**
 * Builds this addon's tier-2 component for QLSM (see qlsm's addons/README.md
 * and the demo-management addon, whose build this copies).
 *
 * React is NOT bundled and NOT a rollup "external" either: an external would
 * leave a bare `import ... from "react"` in the output, which the browser
 * cannot resolve (QLSM loads this file with a plain dynamic import()). So
 * `react` is aliased to ui-src/runtime.js, which reads QLSM's own React off
 * window.__qlsm.
 *
 * No Tailwind here: the panel's stylesheet is plain CSS written against
 * QLSM's CSS variables (ui-src/panel.css), emitted next to the script as
 * ui/Panel.css, which core loads by that naming convention.
 */
export default defineConfig({
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
