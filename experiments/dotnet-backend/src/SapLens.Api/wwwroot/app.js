'use strict';
// Prototype UI for the /api/v1 contract. It holds no credential: the Desktop shell adds the access token to /api requests outside page script,
// and the Server uses an HttpOnly session cookie set by /auth/login. Data is rendered with textContent only.
(() => {
  const $ = (selector) => document.querySelector(selector);
  const state = { roles: { offset: 0 }, users: { offset: 0 }, sod: { offset: 0 } };
  const LIMIT = 50;

  async function api(path, options = {}) {
    const response = await fetch(path, { credentials: 'same-origin', cache: 'no-store', ...options });
    if (response.status === 401) { showSignIn(); throw new Error('Not signed in.'); }
    const body = response.headers.get('Content-Type')?.includes('json') ? await response.json() : null;
    if (!response.ok) throw new Error(body?.title || `Request failed (${response.status}).`);
    return body;
  }

  function showSignIn() {
    $('#app').hidden = true;
    setStatus('Not signed in. ', 'error');
    const link = document.createElement('a'); link.href = '/login.html'; link.textContent = 'Sign in';
    $('#status').append(link);
  }
  function setStatus(text, kind = '') { const s = $('#status'); s.textContent = text; s.className = kind; }

  function rows(target, items, cells) {
    const body = $(target); body.replaceChildren();
    for (const item of items) {
      const tr = document.createElement('tr');
      for (const value of cells(item)) {
        const td = document.createElement('td');
        if (value instanceof Node) td.append(value); else td.textContent = value ?? '';
        tr.append(td);
      }
      body.append(tr);
    }
  }

  function pager(name, page, reload) {
    const el = document.querySelector(`.pager[data-for="${name}"]`); el.replaceChildren();
    const info = document.createElement('span');
    const last = Math.min(page.offset + page.items.length, page.total);
    info.textContent = page.total ? `${page.offset + 1}–${last} of ${page.total}` : 'No results';
    const prev = document.createElement('button'); prev.type = 'button'; prev.textContent = 'Previous'; prev.disabled = page.offset === 0;
    const next = document.createElement('button'); next.type = 'button'; next.textContent = 'Next'; next.disabled = last >= page.total;
    prev.onclick = () => { state[name].offset = Math.max(0, page.offset - LIMIT); reload(); };
    next.onclick = () => { state[name].offset = page.offset + LIMIT; reload(); };
    el.append(prev, info, next);
  }

  function query(form, extra = {}) {
    const params = new URLSearchParams();
    for (const [key, raw] of new FormData(form)) {
      const value = String(raw).trim(); if (!value) continue;
      if (key === 'tcode') value.split(/[\s,;]+/).filter(Boolean).forEach((code) => params.append('tcode', code));
      else params.set(key, value);
    }
    for (const [key, value] of Object.entries(extra)) params.set(key, value);
    return params;
  }

  const fail = (target) => (error) => { const el = $(target); el.textContent = error.message; el.className = 'summary error'; };

  async function loadDatasets() {
    const datasets = await api('/api/v1/datasets');
    rows('#datasets', datasets, (d) => {
      let action = '';
      if (d.status === 'Held') {
        action = document.createElement('button'); action.type = 'button'; action.textContent = 'Confirm activation';
        action.onclick = async () => {
          if (!confirm(`Activate held ${d.source} revision ${d.revision}? Its change was flagged as unusually large.`)) return;
          try { await api(`/api/v1/datasets/${d.id}/confirm`, { method: 'POST' }); await refresh(); } catch (e) { fail('#import-result')(e); }
        };
      }
      return [d.id, d.source, d.revision, d.status, d.record_count, d.activated_utc ?? '', action];
    });
  }

  async function refresh() {
    const datasets = await api('/api/v1/datasets');
    const session = await api('/api/v1/session');
    const active = datasets.filter((d) => d.status === 'Active').map((d) => `${d.source} r${d.revision}`);
    setStatus(`${session.principal} · ${session.mode} · ${active.length ? 'Active: ' + active.join(', ') : 'No data imported yet'}`, 'ok');
    await loadDatasets();
  }

  async function waitForJob(id) {
    for (;;) {
      const job = await api(`/api/v1/jobs/${id}`);
      $('#import-result').textContent = `Job ${id}: ${job.status}${job.progress_text ? ' · ' + job.progress_text : ''}`;
      if (['Completed', 'Failed', 'Cancelled'].includes(job.status)) return job;
      await new Promise((resolve) => setTimeout(resolve, 500));
    }
  }

  $('#import-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const form = event.target; const file = form.file.files[0]; if (!file) return;
    const result = $('#import-result'); result.className = 'summary'; result.textContent = `Uploading ${file.name}…`;
    try {
      const job = await api(`/api/v1/imports/${form.source.value}`, { method: 'POST', body: file, headers: { 'Content-Type': 'text/csv', 'X-File-Name': file.name } });
      const done = await waitForJob(job.id);
      if (done.status === 'Failed') { result.textContent = `Import failed: ${done.error}`; result.className = 'summary error'; }
      else if (done.result?.status === 'Held') result.textContent = `Held for confirmation: ${done.result.anomalies.join(' ')}`;
      else result.textContent = `Imported ${done.result?.records ?? 0} records (${done.status}).`;
      await refresh();
    } catch (e) { fail('#import-result')(e); }
  });

  async function loadRoles() {
    const page = await api('/api/v1/roles?' + query($('#roles-form'), { offset: state.roles.offset, limit: LIMIT }));
    $('#roles-summary').textContent = `${page.total} roles`; $('#roles-summary').className = 'summary';
    rows('#roles', page.items, (r) => [r.agr_name, r.text, `${r.function_key} ${r.module_name}`, r.matching_tcodes.length ? r.matching_tcodes.join(', ') : r.tcode_count]);
    pager('roles', page, loadRoles);
  }
  async function loadUsers() {
    const page = await api('/api/v1/users?' + query($('#users-form'), { offset: state.users.offset, limit: LIMIT }));
    $('#users-summary').textContent = `${page.total} users`; $('#users-summary').className = 'summary';
    rows('#users', page.items, (u) => [u.username, `${u.first_name} ${u.last_name}`.trim(), u.groups.join(', '), `${u.account_status} / ${u.lock_status}`, u.relevant_roles]);
    pager('users', page, loadUsers);
  }
  async function loadCompare() {
    const result = await api('/api/v1/users/compare?' + query($('#compare-form'), { limit: 100 }));
    const [a, b] = result.users.map((u) => u.summary.username);
    $('#compare-summary').textContent = `${result.page.total} rows · a = ${a}, b = ${b}`; $('#compare-summary').className = 'summary';
    rows('#compare', result.page.items, (r) => [r.identifier, r.difference, (r.areas || []).join(', ')]);
  }
  async function loadSod() {
    const result = await api('/api/v1/sod/findings?' + query($('#sod-form'), { offset: state.sod.offset, limit: LIMIT }));
    $('#sod-summary').textContent = result.sod_available
      ? `${result.page.total} findings · policy ${result.evaluation_policy} · ${result.supported_risks} supported risks · as of ${result.as_of}`
      : 'No SoD matrix imported.';
    $('#sod-summary').className = 'summary';
    rows('#sod', result.page.items, (f) => [typeof f.subject === 'string' ? f.subject : JSON.stringify(f.subject), f.risk_id, f.criticality, f.finding_id.slice(0, 12)]);
    pager('sod', result.page, loadSod);
  }

  const forms = { 'roles-form': ['roles', loadRoles, '#roles-summary'], 'users-form': ['users', loadUsers, '#users-summary'], 'sod-form': ['sod', loadSod, '#sod-summary'] };
  for (const [id, [name, load, summary]] of Object.entries(forms))
    $('#' + id).addEventListener('submit', (event) => { event.preventDefault(); state[name].offset = 0; load().catch(fail(summary)); });
  $('#compare-form').addEventListener('submit', (event) => { event.preventDefault(); loadCompare().catch(fail('#compare-summary')); });

  for (const button of document.querySelectorAll('nav button')) {
    button.addEventListener('click', () => {
      for (const other of document.querySelectorAll('nav button')) {
        const selected = other === button; other.setAttribute('aria-pressed', String(selected));
        $('#tab-' + other.dataset.tab).hidden = !selected;
      }
    });
  }

  refresh().then(() => { $('#app').hidden = false; }).catch((error) => { if (error.message !== 'Not signed in.') setStatus(`Backend unavailable: ${error.message}`, 'error'); });
})();
