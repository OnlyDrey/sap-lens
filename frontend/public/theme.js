// Keep the theme bootstrap external so the packaged app needs no inline scripts.
try {
  const saved = localStorage.getItem('sap-viz-theme');
  const dark = saved ? saved === 'dark' : true;
  document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light');
  document.documentElement.classList.toggle('dark', dark);
} catch { /* Storage may be disabled; use the default theme. */ }

// If the application module cannot start, keep a useful recovery screen visible.
window.addEventListener('DOMContentLoaded', () => {
  setTimeout(() => {
    const root = document.getElementById('root');
    if (!root || root.dataset.appMounted) return;
    const status = root.querySelector('[role="status"]');
    if (status) {
      status.setAttribute('role', 'alert');
      status.textContent = 'The interface could not load. Retry, or close and reopen SAP Lens.';
      const retry = document.createElement('button');
      retry.textContent = 'Retry interface';
      retry.addEventListener('click', () => window.location.reload());
      status.after(retry);
    }
  }, 15000);
});
