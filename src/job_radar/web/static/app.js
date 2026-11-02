'use strict';

// Main page: "推薦職缺" (the radar) and "我的申請" (job list + the selected job). Shared helpers
// and answer rendering live in common.js; the Chrome side panel (panel.js) shows the same answers.

const FILTERS = { active: ACTIVE, done: DONE, all: null };
// List groups, in the order the work comes up.
// 'prefilled' (from before ③ was dropped) is the same step as 'ready': check and send.
const GROUP_ORDER = ['ready', 'queued', 'applied', 'interviewing', 'offer', 'rejected', 'withdrawn', 'skipped'];

const ui = {
  nav: 'apps', apps: [], filter: 'active', selected: null, detail: null, busy: false,
  drafts: false,
  radar: null, picked: new Set(), autoPrefill: true, role: 'all', onlyNew: false,
  recoverOpen: false, recoverSkip: new Set(),
};

function render() {
  if (ui.nav === 'radar') renderRadar(); else renderDetail();
}

async function run(label, fn) {
  if (ui.busy) return;
  ui.busy = label;
  render();
  try {
    await fn();
  } catch (err) {
    toast(err.message, true);
  } finally {
    ui.busy = false;
    render();
    if (ui.nav === 'apps') renderList();
  }
}

// ---------- navigation ----------

function setNav(nav) {
  ui.nav = nav;
  try { localStorage.setItem('jr-nav', nav); } catch { /* storage off: not remembered */ }
  document.getElementById('view-radar').hidden = nav !== 'radar';
  document.getElementById('view-apps').hidden = nav !== 'apps';
  for (const item of document.querySelectorAll('.nav-item')) item.classList.toggle('active', item.dataset.nav === nav);
  if (nav === 'radar') {
    renderRadar();
    loadRadar().catch((e) => toast(e.message, true));
  } else {
    renderList();
    renderDetail();
  }
}

function storedNav() {
  try { return localStorage.getItem('jr-nav'); } catch { return null; }
}

// ---------- data ----------

async function loadStatus() {
  const s = await api('/api/status');
  ui.drafts = s.drafts;
  const items = [
    ['基本資料', s.ok ? (s.error || 'applicant.yaml') : s.error, s.ok && !s.error],
    ['履歷', s.resumes.length ? s.resumes.join('、') : '沒有履歷 PDF（profile/resumes/）', s.resumes.length > 0],
    ['經歷素材', s.highlights ? `${s.highlights} 項` : 'highlights.yaml 是空的', s.highlights > 0],
    ['草稿模型', s.drafts ? `${s.model} · ${s.credential}` : '未接模型，只填答案庫', s.drafts ? true : null],
  ];
  const warnings = items.filter(([, , ok]) => ok === false).length;
  document.getElementById('health-btn').className = `health${warnings ? ' warn' : ''}`;
  document.getElementById('health-text').textContent = warnings ? `${warnings} 項待補` : '資料齊全';
  document.getElementById('health-list').replaceChildren(...items.map(([name, value, ok]) => h('li', { class: ok === false ? 'warn' : ok ? 'ok' : 'off' },
    h('span', { class: 'health-icon', text: ok === false ? '!' : ok ? '✓' : '–' }),
    h('span', { class: 'health-name', text: name }),
    h('span', { class: 'health-value', text: value }))));
  if (ui.detail) renderDetail();
}

async function loadApps() {
  ui.apps = await api('/api/applications');
  const active = ui.apps.filter((a) => ACTIVE.includes(a.status)).length;
  document.getElementById('nav-apps-count').textContent = active ? String(active) : '';
  renderList();
}

async function select(jobId) {
  ui.selected = jobId;
  renderList();
  ui.detail = await api(jobPath(jobId));
  renderDetail();
  window.scrollTo({ top: 0 });
}

async function refreshSelected() {
  await loadApps();
  if (ui.selected) {
    ui.detail = await api(jobPath(ui.selected));
  }
}

// ---------- list ----------

function renderList() {
  const allowed = FILTERS[ui.filter];
  const apps = ui.apps.filter((a) => !allowed || allowed.includes(a.status));
  const list = document.getElementById('job-list');
  if (!apps.length) {
    list.replaceChildren(h('p', { class: 'list-empty', text: ui.filter === 'active' ? '沒有進行中的職缺。到「推薦職缺」挑幾個，或在上面貼網址。' : '這裡還沒有職缺。' }));
    return;
  }
  const groupOf = (a) => (a.status === 'prefilled' ? 'ready' : a.status);
  const groups = GROUP_ORDER.map((status) => [status, apps.filter((a) => groupOf(a) === status)]).filter(([, g]) => g.length);
  list.replaceChildren(
    ui.filter === 'done' ? null : recoverCard(),
    ...groups.map(([status, group]) => h('div', { class: 'list-group' },
      h('div', { class: 'list-group-head' }, h('span', { class: `dot ${status}` }), STATUS[status] || status, h('span', { class: 'count', text: String(group.length) })),
      ...group.map((a) => jobRow(a, {
        selected: a.job.job_id === ui.selected,
        side: tabClosed(a, a.page_open)
          ? h('span', { class: 'job-row-time closed', title: '申請頁已關閉', text: '分頁已關' })
          : h('span', { class: 'job-row-time', text: timeAgo(a.updated_at) }),
        onclick: () => select(a.job.job_id).catch((e) => toast(e.message, true)),
      })))));
}

// Jobs filled in a tab that is now closed: re-open them all (or the ticked ones) in one go.
function recoverCard() {
  const closed = ui.apps.filter((a) => tabClosed(a, a.page_open));
  if (!closed.length) return null;
  const picked = closed.filter((a) => !ui.recoverSkip.has(a.job.job_id));
  const busy = Boolean(ui.busy);
  const ids = (ui.recoverOpen ? picked : closed).map((a) => a.job.job_id);
  return h('section', { class: 'recover' },
    h('div', { class: 'recover-head' },
      h('span', { class: 'recover-icon', 'aria-hidden': 'true', text: '!' }),
      h('strong', { text: `${closed.length} 個申請頁已關閉` }),
      h('button', { class: 'btn ghost small', onclick: () => { ui.recoverOpen = !ui.recoverOpen; renderList(); }, text: ui.recoverOpen ? '收起' : '選擇…' })),
    h('p', { class: 'recover-desc', text: '恢復會重新開啟申請頁並自動填寫一次。' }),
    ui.recoverOpen ? h('div', { class: 'recover-list' }, ...closed.map((a) => h('label', { class: 'recover-item' },
      h('input', { type: 'checkbox', checked: !ui.recoverSkip.has(a.job.job_id), onchange: (e) => {
        if (e.target.checked) ui.recoverSkip.delete(a.job.job_id); else ui.recoverSkip.add(a.job.job_id);
        renderList();
      } }),
      h('span', { class: 'recover-company', text: a.job.company || SOURCE[a.job.source] }),
      h('span', { class: 'recover-title', text: a.job.title })))) : null,
    h('button', { class: 'btn primary small wide', disabled: busy || !ids.length, onclick: () => onRecover(ids),
      text: ui.recoverOpen ? `恢復勾選的（${ids.length}）` : `全部恢復（${ids.length}）` }));
}

// ---------- detail ----------

function renderDetail() {
  const root = document.getElementById('detail');
  const d = ui.detail;
  if (!d) { root.replaceChildren(emptyDetail()); return; }
  const app = d.application;
  const job = app.job;
  const form = d.form;
  const busy = Boolean(ui.busy);
  const company = job.company || SOURCE[job.source] || '';

  const head = h('header', { class: 'job-head' },
    monogram(company, 'xl'),
    h('div', { class: 'job-head-text' },
      h('div', { class: 'job-head-company' }, company, statusPill(app.status)),
      h('h1', { class: 'job-head-title', text: job.title || '（尚未取得職稱）' }),
      h('div', { class: 'job-head-meta' },
        ...[locationText(job.location), SOURCE[job.source]].filter(Boolean).map((t) => h('span', { text: t })),
        h('a', { href: job.url, target: '_blank', rel: 'noopener noreferrer', text: '原始網址 ↗' }))),
    ACTIVE.includes(app.status) ? h('button', { class: 'btn ghost small', disabled: busy, onclick: () => onStatus('skipped'), text: '略過' }) : null);

  const parts = [head];
  if (app.status !== 'skipped') parts.push(stepper(stageOf(d)));
  parts.push(stepCard(d, busy));

  if (form && form.answers.length) {
    parts.push(formStats(form));
  }
  if (form) {
    parts.push(...banners(form));
    parts.push(...renderAnswers(form, job.title));
    parts.push(h('p', { class: 'detail-foot', text: `資料夾：${d.folder}${app.llm_cost_usd ? ` · 這個職缺的 LLM 花費約 $${app.llm_cost_usd.toFixed(3)}` : ''}` }));
  } else {
    parts.push(h('p', { class: 'side-tip' }, '申請頁開啟後，也可以按 Chrome 右上角的 Job Radar 圖示（或 ⌘⇧Y），在申請頁旁的側邊欄看要自己填的題目。'));
  }
  root.replaceChildren(...parts);
}

function emptyDetail() {
  const art = document.getElementById('radar-art');
  return h('div', { class: 'empty-state' },
    art ? art.content.cloneNode(true) : null,
    h('h2', { text: ui.apps.length ? '選一個職缺開始' : '還沒有職缺' }),
    h('p', { class: 'muted', text: ui.apps.length ? '每個職缺都照這三步走，送出永遠由你自己按。' : '到「推薦職缺」挑幾個，或在左上貼上職缺網址。' }),
    h('ol', { class: 'how' }, ...STEPS.map((label, i) => h('li', {},
      h('span', { class: 'bullet', text: String(i + 1) }),
      h('span', { text: label }),
      h('span', { class: 'muted', text: ['在受控的 Chrome 打開', '基本資料、經歷、答案庫', '補上沒填到的題目，自己按送出'][i] })))));
}

function resumeControl(d, busy) {
  const form = d.form;
  if (d.job_resume_override) return h('span', { class: 'resume-note', text: '履歷：職缺資料夾裡的 resume.pdf' });
  if (!d.resumes.length) return h('span', { class: 'resume-note warn', text: '沒有履歷 PDF' });
  const current = (form && form.resume_variant) || d.application.resume_variant || d.suggested_resume || d.resumes[0];
  if (d.resumes.length === 1) return h('span', { class: 'resume-note', text: `履歷：${current}` });
  return h('label', { class: 'resume-pick' }, '履歷',
    h('select', { id: 'resume-select', disabled: busy },
      ...d.resumes.map((name) => h('option', { value: name, text: name === d.suggested_resume ? `${name}（建議）` : name, selected: name === current }))));
}

function stepCard(d, busy) {
  const app = d.application;
  if (d.form && tabClosed(app, d.page_open)) return closedCard(d, busy);
  const stage = stageOf(d);
  const [title, desc] = nextStep(d, ui.drafts);
  const form = d.form;
  const open = (primary) => h('button', { class: `btn${primary ? ' primary' : ''}`, disabled: busy, onclick: onOpen, text: '① 開啟申請頁' });
  const prefill = (primary) => h('button', { class: `btn${primary ? ' primary' : ''}`, disabled: busy, onclick: onPrefill, text: form ? '② 重新掃描' : '② 自動填寫' });
  let actions;
  if (app.status === 'skipped') {
    actions = [h('button', { class: 'btn primary', disabled: busy, onclick: () => onStatus('queued'), text: '移回進行中' })];
  } else if (stage === 0) {
    actions = [open(true), prefill(false)];
  } else if (stage === 1) {
    actions = [prefill(true), open(false)];
  } else if (stage === 2) {
    actions = [
      h('button', { class: 'btn success', disabled: busy, onclick: onApplied, text: '我已送出' }),
      prefill(false), open(false)];
  } else {
    const sel = h('select', { class: 'status-select', disabled: busy, onchange: (e) => onStatus(e.target.value) },
      ...DONE.map((s) => h('option', { value: s, text: STATUS[s], selected: s === app.status })));
    actions = [h('label', { class: 'resume-pick' }, '進度', sel), open(false)];
  }
  const showResume = stage <= 2 && app.status !== 'skipped';
  return h('section', { class: `step-card stage-${stage}${busy ? ' busy' : ''}` },
    h('div', { class: 'step-card-text' },
      h('p', { class: 'step-eyebrow', text: stage < 3 && app.status !== 'skipped' ? `下一步 · ${stage + 1}/3` : '狀態' }),
      h('h2', { text: title }),
      busy ? h('p', { class: 'step-busy' }, spinner(), `${ui.busy}…`) : h('p', { class: 'step-desc', text: desc })),
    h('div', { class: 'step-actions' }, ...actions, showResume ? resumeControl(d, busy) : null));
}

function closedCard(d, busy) {
  const [title, desc] = nextStep(d, ui.drafts);
  return h('section', { class: `step-card closed${busy ? ' busy' : ''}` },
    h('div', { class: 'step-card-text' },
      h('p', { class: 'step-eyebrow', text: '分頁已關閉' }),
      h('h2', { text: title }),
      busy ? h('p', { class: 'step-busy' }, spinner(), `${ui.busy}…`) : h('p', { class: 'step-desc', text: desc })),
    h('div', { class: 'step-actions' },
      h('button', { class: 'btn primary', disabled: busy, onclick: () => onRecover([d.application.job.job_id]), text: '恢復申請頁' }),
      resumeControl(d, busy)));
}

// ---------- actions ----------

function onOpen() {
  run('正在開啟申請頁', async () => {
    await api(jobPath(ui.selected, '/open'), { method: 'POST' });
    await refreshSelected();
    toast('已在瀏覽器開啟。需要登入或點 Apply 的話，請先在瀏覽器處理。');
  });
}

function onPrefill() {
  const sel = document.getElementById('resume-select');
  const variant = sel && sel.value ? sel.value : null;
  run(prefillLabel(ui.drafts), async () => {
    const [message, isError] = await prefillJob(ui.selected, variant);
    await refreshSelected();
    toast(message, isError);
  });
}

// Re-open each job's application page and fill it again (② opens a closed tab). One at a time,
// so each form gets the browser to itself.
function onRecover(ids) {
  const jobs = ids.map((id) => ui.apps.find((a) => a.job.job_id === id)).filter(Boolean);
  run('準備恢復', async () => {
    const done = [];
    const failed = [];
    for (const [i, a] of jobs.entries()) {
      ui.busy = `(${i + 1}/${jobs.length}) ${a.job.company || a.job.title}：開啟並填寫`;
      renderDetail(); renderList();
      try {
        const [message, isError] = await prefillJob(a.job.job_id);
        if (isError) failed.push(`${a.job.company}：${message}`); else done.push(a.job.job_id);
      } catch (err) {
        failed.push(`${a.job.company}：${err.message}`);
      }
    }
    await refreshSelected();
    toast(failed.length
      ? `已恢復 ${done.length} 個；${failed.join('；')}`
      : jobs.length === 1 ? '已恢復：申請頁重新開啟並自動填好了。' : `已恢復 ${done.length} 個申請頁。`, failed.length > 0);
  });
}

function onApplied(event) {
  confirmTwice(event, () => onStatus('applied'), '確定已送出？再按一次');
}

function onStatus(status) {
  run('正在更新狀態', async () => {
    await setJobStatus(ui.selected, status);
    await refreshSelected();
  });
}

async function onAdd(event) {
  event.preventDefault();
  const input = document.getElementById('url-input');
  const msg = document.getElementById('add-msg');
  const button = document.getElementById('add-btn');
  if (!input.value.trim()) { input.focus(); return; }
  button.disabled = true;
  msg.className = 'composer-msg';
  msg.textContent = '正在讀取職缺…';
  try {
    const res = await api('/api/applications', { method: 'POST', body: JSON.stringify({ urls: input.value }) });
    msg.textContent = [res.added.length ? `已加入 ${res.added.length} 個職缺` : '', ...res.errors].filter(Boolean).join('；');
    msg.className = `composer-msg${res.errors.length ? ' error' : ''}`;
    input.value = '';
    growComposer();
    ui.filter = 'active';
    syncFilter();
    await loadApps();
    if (res.added.length) await select(res.added[0]);
  } catch (err) {
    msg.textContent = err.message;
    msg.className = 'composer-msg error';
  } finally {
    button.disabled = false;
  }
}

function growComposer() {
  const input = document.getElementById('url-input');
  input.style.height = 'auto';
  input.style.height = `${Math.min(input.scrollHeight, 160)}px`;
}

function syncFilter() {
  for (const seg of document.querySelectorAll('.seg')) seg.classList.toggle('active', seg.dataset.filter === ui.filter);
}

// ---------- radar ----------

const LEVEL = { intern: 'Co-op / 實習', new_grad: '新鮮人' };
const SITE = { linkedin: 'LinkedIn', jobright: 'Jobright' };
const ROLE = { ds: 'Data Science', mle: 'MLE', ai_engineer: 'AI Engineer', de: 'Data Eng', da: 'Analyst', swe: 'SWE' };

async function loadRadar() {
  const wasFetching = Boolean(ui.radar && ui.radar.fetching);
  ui.radar = await api('/api/radar?limit=150&manual_limit=50');
  const r = ui.radar;
  if (wasFetching && !r.fetching && r.last_run) fetchDone(r);
  document.getElementById('nav-radar-count').textContent = r.recommended ? String(r.recommended) : '';
  if (ui.nav === 'radar') renderRadar();
  if (r.fetching) setTimeout(() => loadRadar().catch(() => {}), 3000);
}

// Say what a fetch brought in, including sites that refused (rate limit, bot check).
function fetchDone(r) {
  const run = r.last_run;
  const found = run.new ? `抓取完成：新增 ${run.new} 個職缺` : '抓取完成：這次沒有新職缺（距離上次抓取太近，或公司還沒貼新職缺）';
  toast([found, ...run.failed].join('；'), run.failed.length > 0);
}

function radarSummary(r) {
  if (!r) return '讀取中…';
  if (r.fetching) return '正在抓取職缺，約 2–4 分鐘…';
  const last = r.last_run;
  if (!last) return '還沒有抓取過職缺。';
  return [
    `上次抓取 ${formatTime(last.finished_at)}`,
    `${last.ok} 家公司`,
    `${r.recommended} 個符合（共 ${r.total.toLocaleString()} 個）`,
    r.new_recommended ? `近 ${r.new_days} 天新出現 ${r.new_recommended} 個` : `近 ${r.new_days} 天沒有新的推薦`,
    r.items.length < r.recommended - r.manual_total ? `列出分數最高的 ${r.items.length} 個` : '',
  ].filter(Boolean).join(' · ');
}

function renderRadar() {
  const root = document.getElementById('view-radar');
  const r = ui.radar;
  const busy = Boolean(ui.busy);
  const items = r ? r.items : [];
  const manual = r ? r.manual : [];
  ui.picked = new Set([...ui.picked].filter((id) => [...items, ...manual].some((m) => m.id === id)));
  const shown = (list) => list.filter((m) => (ui.role === 'all' || m.role === ui.role) && (!ui.onlyNew || m.is_new));

  const head = h('header', { class: 'page-head' },
    h('div', {},
      h('h1', { text: '推薦職缺' }),
      h('p', { class: 'page-sub' }, radarSummary(r),
        r && r.last_run && r.last_run.failed.length
          ? h('span', { class: 'warn-inline', title: r.last_run.failed.join('\n'), text: ` · ${r.last_run.failed.length} 個來源失敗` }) : null)),
    h('div', { class: 'page-actions' },
      h('label', { class: 'q-check' }, h('input', { type: 'checkbox', class: 'switch', checked: ui.autoPrefill, onchange: (e) => { ui.autoPrefill = e.target.checked; } }), '開啟後自動填寫'),
      h('button', { class: 'btn', disabled: busy || (r && r.fetching), onclick: onFetch },
        r && r.fetching ? spinner() : h('span', { 'aria-hidden': 'true', text: '↻' }), r && r.fetching ? '抓取中' : '重新抓取')));

  const parts = [head];
  if (r && !r.total) {
    parts.push(h('div', { class: 'banner info', text: '按「重新抓取」從 config/companies.yaml 的公司與 LinkedIn、Jobright 抓職缺（約 2–4 分鐘）。' }));
  }
  if (r && r.total) parts.push(radarFilters([...items, ...manual]));
  if (r && r.found_companies.length) parts.push(foundCompanies(r.found_companies));

  const fillable = shown(items);
  parts.push(h('div', { class: 'radar-list' }, ...fillable.map(radarRow),
    r && !fillable.length && items.length ? h('p', { class: 'list-empty', text: '沒有符合篩選的職缺。' }) : null));
  const manualShown = shown(manual);
  if (manualShown.length) {
    parts.push(h('section', { class: 'radar-manual' },
      h('header', { class: 'list-section-head' },
        h('h2', { text: '需要自己開啟' }),
        h('span', { class: 'count', text: `${r.manual_total} 個` }),
        h('p', { class: 'muted', text: 'LinkedIn / Jobright 上、沒找到可自動填的職缺板的公司。加入後會開原網頁，或用「找公司官網」到公司網站申請。' })),
      h('div', { class: 'radar-list' }, ...manualShown.map(radarRow))));
  }
  parts.push(pickBar(busy));
  root.replaceChildren(h('div', { class: 'radar-wrap' }, ...parts));
}

function radarFilters(all) {
  const counts = {};
  for (const m of all) counts[m.role] = (counts[m.role] || 0) + 1;
  const fresh = all.filter((m) => m.is_new).length;
  const chip = (role, label, n) => h('button', {
    class: `chip${ui.role === role ? ' active' : ''}`,
    onclick: () => { ui.role = role; renderRadar(); },
  }, label, h('span', { class: 'chip-count', text: String(n) }));
  return h('div', { class: 'filters' },
    chip('all', '全部', all.length),
    ...Object.keys(ROLE).filter((role) => counts[role]).map((role) => chip(role, ROLE[role], counts[role])),
    fresh ? h('button', {
      class: `chip new${ui.onlyNew ? ' active' : ''}`,
      onclick: () => { ui.onlyNew = !ui.onlyNew; renderRadar(); },
    }, `近 ${ui.radar.new_days} 天新增`, h('span', { class: 'chip-count', text: String(fresh) })) : null);
}

// Companies whose ATS board was found from job-site postings: one click adds them to the radar.
function foundCompanies(companies) {
  return h('details', { class: 'callout' },
    h('summary', {},
      h('span', { class: 'callout-icon', text: '✦' }),
      h('span', {}, h('strong', { text: `找到 ${companies.length} 家可以自動填的公司` }),
        h('span', { class: 'muted', text: '　LinkedIn / Jobright 上的職缺，在這些公司有公開職缺板。加入雷達後每天都會抓。' })),
      h('span', { class: 'chev', 'aria-hidden': 'true' })),
    h('div', { class: 'company-chips' }, ...companies.map((c) => h('span', { class: 'company-chip' },
      monogram(c.company, 'sm'),
      h('span', { text: c.company }),
      h('span', { class: 'muted', text: c.platform }),
      h('button', { class: 'btn small', disabled: Boolean(ui.busy), onclick: () => onAddCompany(c), text: '＋ 加入' })))));
}

function onAddCompany(c) {
  api('/api/radar/companies', { method: 'POST', body: JSON.stringify({ name: c.company, platform: c.platform, token: c.token }) })
    .then(() => { toast(`已加入 ${c.company}，下次抓取時會包含它的職缺`); return loadRadar(); })
    .catch((e) => toast(e.message, true));
}

function careersSearch(m) {
  return `https://www.google.com/search?q=${encodeURIComponent(`${m.company} ${m.title} careers`)}`;
}

function scoreRing(score, muted) {
  const tone = muted ? 'muted' : score >= 75 ? 'high' : score >= 55 ? 'mid' : 'low';
  return h('span', { class: `score ${tone}`, style: `--p:${Math.max(0, Math.min(100, score))}`, title: `符合度 ${score} / 100` },
    h('span', { class: 'score-value', text: String(score) }));
}

function togglePick(id) {
  if (ui.picked.has(id)) ui.picked.delete(id); else ui.picked.add(id);
  renderRadar();
}

function radarRow(m) {
  const picked = ui.picked.has(m.id);
  const site = SITE[m.platform] || m.platform;
  const meta = [
    locationText(m.location, m.other_locations.length), ROLE[m.role], LEVEL[m.level],
    m.posted_at ? `${formatDate(m.posted_at)} 發布` : '',
  ].filter(Boolean);
  const missing = m.missing_skills.slice(0, 4);
  return h('div', {
    class: `radar-row${picked ? ' picked' : ''}${m.manual ? ' manual' : ''}`,
    onclick: (e) => { if (!e.target.closest('a, button, input')) togglePick(m.id); },
  },
  h('input', { type: 'checkbox', class: 'pick', checked: picked, 'aria-label': `選擇 ${m.company} ${m.title}`, onchange: () => togglePick(m.id) }),
  scoreRing(m.score, m.manual),
  h('div', { class: 'radar-main' },
    h('div', { class: 'radar-top' },
      monogram(m.company, 'sm'),
      h('span', { class: 'radar-company', text: m.company }),
      m.is_new ? h('span', { class: 'tag new', text: '新' }) : null,
      ...m.also_on.map((s) => h('span', { class: 'tag', text: `也在 ${SITE[s] || s}` })),
      m.manual ? h('span', { class: 'tag manual', text: `${site} · 自己開啟` }) : null),
    h('a', { class: 'radar-title', href: m.url, target: '_blank', rel: 'noopener noreferrer', text: m.title }),
    h('div', { class: 'radar-meta' }, ...meta.map((t) => h('span', { text: t }))),
    m.matched_skills.length || missing.length ? h('div', { class: 'skills' },
      ...m.matched_skills.map((s) => h('span', { class: 'skill have', text: s })),
      ...missing.map((s) => h('span', { class: 'skill lack', title: 'JD 提到、你的資料沒有', text: s })),
      m.missing_skills.length > missing.length ? h('span', { class: 'skill more', text: `+${m.missing_skills.length - missing.length}` }) : null) : null,
    m.manual ? h('p', { class: 'radar-note' }, `${site} 不登入看不到申請連結。加入後會開原網頁；或 `,
      h('a', { href: careersSearch(m), target: '_blank', rel: 'noopener noreferrer', text: '找公司官網 ↗' })) : null),
  h('button', { class: 'dismiss', title: '不感興趣（不再推薦）', onclick: () => onDismiss(m.id), text: '不感興趣' }));
}

function pickBar(busy) {
  const n = ui.picked.size;
  return h('div', { class: `pick-bar${n || busy ? ' show' : ''}` },
    busy
      ? h('span', { class: 'pick-bar-text' }, spinner(), `${ui.busy}…`)
      : h('span', { class: 'pick-bar-text' }, h('strong', { text: `已選 ${n} 個` }),
        h('span', { class: 'pick-bar-note', text: ui.autoPrefill ? '開啟後會自動填寫基本資料' : '只開啟，不自動填寫' })),
    busy ? null : h('button', { class: 'btn ghost small', onclick: () => { ui.picked.clear(); renderRadar(); }, text: '清除' }),
    h('button', { class: 'btn primary', disabled: busy || !n, onclick: onOpenPicked, text: '加入並開啟 →' }));
}

function onFetch() {
  api('/api/radar/fetch', { method: 'POST' })
    .then(() => { toast('開始抓取職缺，約 2–4 分鐘'); return loadRadar(); })
    .catch((e) => toast(e.message, true));
}

function onDismiss(id) {
  ui.picked.delete(id);
  api('/api/radar/dismiss', { method: 'POST', body: JSON.stringify({ id }) })
    .then(loadRadar).catch((e) => toast(e.message, true));
}

// Each picked job: add it, open its application page in its own tab, and (optionally) run ②.
function onOpenPicked() {
  const picked = [...ui.radar.items, ...ui.radar.manual].filter((m) => ui.picked.has(m.id));
  run('準備開啟', async () => {
    const opened = [];
    const failed = [];
    for (const [i, m] of picked.entries()) {
      const step = `(${i + 1}/${picked.length}) ${m.company}`;
      try {
        ui.busy = `${step}：加入並開啟`; renderRadar();
        const res = await api('/api/applications', { method: 'POST', body: JSON.stringify({ urls: m.apply_url }) });
        if (!res.added.length) throw new Error(res.errors.join('；') || '無法加入');
        const jobId = res.added[0];
        await api(jobPath(jobId, '/open'), { method: 'POST' });
        if (ui.autoPrefill && !m.manual) {  // a job-site page has no form to fill
          ui.busy = `${step}：填寫基本資料`; renderRadar();
          await prefillJob(jobId);
        }
        opened.push(jobId);
        ui.picked.delete(m.id);
      } catch (err) {
        failed.push(`${m.company}：${err.message}`);
      }
    }
    await Promise.all([loadApps(), loadRadar()]);
    toast(failed.length ? `已開啟 ${opened.length} 個；失敗：${failed.join('；')}` : `已開啟 ${opened.length} 個申請頁${ui.autoPrefill ? '並填好基本資料' : ''}。沒填到的題目列在各職缺裡，到申請頁補上即可。`, failed.length > 0);
  });
}

// The side panel may have changed things while this tab was in the background.
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState !== 'visible' || ui.busy) return;
  loadApps().then(async () => {
    if (!ui.selected) return;
    ui.detail = await api(jobPath(ui.selected));
    if (ui.nav === 'apps') renderDetail();
  }).catch(() => {});
});

// ---------- boot ----------

document.getElementById('add-form').addEventListener('submit', onAdd);
document.getElementById('url-input').addEventListener('input', growComposer);
document.getElementById('url-input').addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) onAdd(e);
});
document.getElementById('add-open').addEventListener('click', () => {
  setNav('apps');
  document.getElementById('url-input').focus();
});
for (const item of document.querySelectorAll('.nav-item')) {
  item.addEventListener('click', () => setNav(item.dataset.nav));
}
for (const seg of document.querySelectorAll('.seg')) {
  seg.addEventListener('click', () => { ui.filter = seg.dataset.filter; syncFilter(); renderList(); });
}
const firstNav = storedNav();
setNav(firstNav === 'radar' ? 'radar' : 'apps');
Promise.all([loadStatus(), loadApps(), loadRadar()])
  .then(() => {
    if (!firstNav && !ui.apps.some((a) => ACTIVE.includes(a.status))) setNav('radar');
    else if (ui.nav === 'apps') renderDetail();
  })
  .catch((err) => toast(err.message, true));
