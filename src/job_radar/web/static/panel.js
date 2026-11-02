'use strict';

// Chrome side panel: shows the job whose tab is active. The extension page that frames this
// one (web/extension/sidepanel.js) posts the active tab's URL; everything else goes through
// the same token-protected API as the main page.

const panel = {
  url: '', jobId: null, detail: null, busy: false, drafts: false,
  apps: [], parentOrigin: null, pendingUrl: null,
};

window.addEventListener('message', (event) => {
  if (event.source !== window.parent || !event.origin.startsWith('chrome-extension://')) return;
  if (!event.data || event.data.type !== 'jr-tab') return;
  panel.parentOrigin = event.origin;
  onTab(String(event.data.url || ''));
});

function tellParent(type) {
  if (panel.parentOrigin) window.parent.postMessage({ type }, panel.parentOrigin);
}

async function call(fn) {
  try {
    return await fn();
  } catch (err) {
    // Server restarted (new token) or stopped: let the extension reconnect.
    if (err instanceof TypeError || /token/.test(err.message)) tellParent('jr-offline');
    throw err;
  }
}

async function onTab(url) {
  if (panel.busy) { panel.pendingUrl = url; return; }
  panel.url = url;
  try {
    const { job_id: jobId } = await call(() => api(`/api/tab?url=${encodeURIComponent(url)}`));
    panel.jobId = jobId;
    if (jobId) await loadJob();
    else panel.apps = await call(() => api('/api/applications'));
  } catch (err) {
    toast(err.message, true);
  }
  render();
}

async function loadJob() {
  panel.detail = await call(() => api(jobPath(panel.jobId)));
}

async function run(label, fn) {
  if (panel.busy) return;
  panel.busy = label;
  render();
  try {
    await fn();
  } catch (err) {
    toast(err.message, true);
  } finally {
    panel.busy = false;
    const next = panel.pendingUrl;
    panel.pendingUrl = null;
    if (next !== null && next !== panel.url) onTab(next);
    else render();
  }
}

// ---------- views ----------

function render() {
  const root = document.getElementById('panel');
  if (panel.jobId && panel.detail) root.replaceChildren(...jobView());
  else root.replaceChildren(...otherView());
}

function jobView() {
  const d = panel.detail;
  const app = d.application;
  const job = app.job;
  const form = d.form;
  const busy = Boolean(panel.busy);
  const company = job.company || SOURCE[job.source] || '';
  const [title, desc] = nextStep(d, panel.drafts);
  const parts = [
    h('header', { class: 'side-head' },
      monogram(company, 'lg'),
      h('div', { class: 'side-head-text' },
        h('div', { class: 'job-head-company' }, company, statusPill(app.status)),
        h('div', { class: 'side-title', text: job.title || '（尚未取得職稱）' }))),
    app.status !== 'skipped' ? stepper(stageOf(d)) : null,
    h('section', { class: `side-step${busy ? ' busy' : ''}` },
      h('h2', { text: title }),
      busy ? h('p', { class: 'step-busy' }, spinner(), `${panel.busy}…`) : h('p', { class: 'step-desc', text: desc })),
  ];
  if (form && form.answers.length) parts.push(formStats(form));
  if (form) parts.push(...banners(form), ...renderAnswers(form, job.title));
  parts.push(actionBar(d, busy));
  return parts.filter(Boolean);
}

// The panel is one narrow column, so the step's buttons stay pinned at the bottom.
function actionBar(d, busy) {
  const app = d.application;
  const form = d.form;
  const stage = stageOf(d);
  const prefill = (primary) => h('button', { class: `btn${primary ? ' primary wide' : ' small'}`, disabled: busy, onclick: onPrefill, text: form ? '② 重新掃描' : '② 自動填寫' });
  const skip = h('button', { class: 'btn ghost small', disabled: busy, onclick: () => onStatus('skipped'), text: '略過' });
  let main;
  let extra = [];
  if (app.status === 'skipped') {
    main = h('button', { class: 'btn primary wide', disabled: busy, onclick: () => onStatus('queued'), text: '移回進行中' });
  } else if (stage <= 1) {
    main = prefill(true); extra = [skip];
  } else if (stage === 2) {
    main = h('button', { class: 'btn success wide', disabled: busy, onclick: onApplied, text: '我已送出' });
    extra = [prefill(false), skip];
  } else {
    main = h('select', { class: 'status-select wide', disabled: busy, onchange: (e) => onStatus(e.target.value) },
      ...DONE.map((s) => h('option', { value: s, text: `進度：${STATUS[s]}`, selected: s === app.status })));
  }
  return h('footer', { class: 'action-bar' }, main, extra.some(Boolean) ? h('div', { class: 'action-extra' }, ...extra) : null);
}

function otherView() {
  const isHome = panel.url.startsWith(location.origin);
  const isWeb = /^https?:\/\//.test(panel.url) && !isHome;
  const active = panel.apps.filter((a) => ACTIVE.includes(a.status));
  const parts = [];
  if (isHome) {
    parts.push(h('section', { class: 'side-step' },
      h('h2', { text: '這是主頁' }),
      h('p', { class: 'step-desc', text: '在主頁選職缺並按「① 開啟申請頁」，切到申請頁時這裡會列出要你自己填的題目。' })));
  } else {
    parts.push(h('section', { class: 'side-step' },
      h('h2', { text: '這個分頁不在清單裡' }),
      h('p', { class: 'step-desc', text: isWeb ? '在 LinkedIn 或公司網站逛到的職缺，可以直接加入、在這頁申請。' : '切到職缺的申請頁，這裡就會顯示它的題目。' }),
      isWeb ? h('button', { class: 'btn primary wide', disabled: Boolean(panel.busy), onclick: onAdopt, text: '加入清單並在這頁申請' }) : null,
      panel.busy ? h('p', { class: 'step-busy' }, spinner(), `${panel.busy}…`) : null));
  }
  if (active.length) {
    parts.push(h('section', { class: 'side-list' },
      h('div', { class: 'list-group-head' }, '進行中的職缺', h('span', { class: 'count', text: String(active.length) })),
      ...active.map((a) => jobRow(a, {
        side: tabClosed(a, a.page_open) ? h('span', { class: 'job-row-time closed', text: '分頁已關' }) : statusPill(a.status),
        onclick: () => (tabClosed(a, a.page_open) ? onRecover(a.job.job_id) : onOpen(a.job.job_id)),
      }))));
  }
  return parts;
}

// ---------- actions ----------

function onPrefill() {
  run(prefillLabel(panel.drafts), async () => {
    const [message, isError] = await call(() => prefillJob(panel.jobId));
    await loadJob();
    toast(message, isError);
  });
}

function onApplied(event) {
  confirmTwice(event, () => onStatus('applied'), '確定已送出？再按一次');
}

function onStatus(status) {
  run('正在更新狀態', async () => {
    await call(() => setJobStatus(panel.jobId, status));
    await loadJob();
  });
}

function onOpen(jobId) {
  // Opening switches tabs; the extension then reports the new tab and this panel follows.
  run('正在開啟申請頁', () => call(() => api(jobPath(jobId, '/open'), { method: 'POST' })));
}

function onRecover(jobId) {
  // ② re-opens the closed tab and fills it again; the extension then reports the new tab.
  run('正在恢復申請頁', async () => {
    const [message, isError] = await call(() => prefillJob(jobId));
    toast(message, isError);
  });
}

function onAdopt() {
  const url = panel.url;
  run('正在加入職缺', async () => {
    const { job_id: jobId } = await call(() => api('/api/tab/adopt', { method: 'POST', body: JSON.stringify({ url }) }));
    panel.jobId = jobId;
    await loadJob();
    toast('已加入。看到申請表後按②。');
  });
}

document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible' && panel.url && !panel.busy) onTab(panel.url);
});

// ---------- boot ----------

call(() => api('/api/status'))
  .then((s) => { panel.drafts = s.drafts; })
  .catch(() => {})
  .finally(() => window.parent.postMessage({ type: 'jr-ready' }, '*'));
