// Keep the theme bootstrap external so the packaged app needs no inline scripts.
try {
  const saved = localStorage.getItem('sap-viz-theme');
  const dark = saved ? saved === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches;
  document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light');
  document.documentElement.classList.toggle('dark', dark);
} catch { /* Storage may be disabled; use the default theme. */ }
