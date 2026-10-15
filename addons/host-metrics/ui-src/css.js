// QLSM links `<component>.css` (Page.css, HostPanel.css) by convention, but this addon
// builds one shared Panel.css for both entries, so each entry links it itself, next to
// the module it was loaded from. Idempotent; a missing file is dropped quietly.
export function ensurePanelCss() {
  if (typeof document === 'undefined') return;
  const here = import.meta.url;
  const href = `${here.slice(0, here.lastIndexOf('/') + 1)}Panel.css`;
  const id = 'hm-panel-css';
  if (document.getElementById(id)) return;
  const link = document.createElement('link');
  link.id = id;
  link.rel = 'stylesheet';
  link.href = href;
  link.onerror = () => link.remove();
  document.head.appendChild(link);
}
