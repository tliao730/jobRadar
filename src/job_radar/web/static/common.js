'use strict';

// Shared by the main page (app.js) and the Chrome side panel (panel.js).
// Every string that comes from a job page (labels, options, notes) is untrusted: the DOM is
// built with textContent only, never innerHTML.

const TOKEN = document.querySelector('meta[name="jr-token"]').content;

const STATUS = {
  queued: '待處理', prefilled: '待送出', ready: '待送出', applied: '已送出', skipped: '已略過',
  interviewing: '面試中', offer: 'Offer', rejected: '未錄取', withdrawn: '已撤回',
};
const SOURCE = {
  greenhouse: 'Greenhouse', lever: 'Lever', ashby: 'Ashby', linkedin: 'LinkedIn',
  indeed: 'Indeed', glassdoor: 'Glassdoor', jobright: 'Jobright', other: '其他網站',
};
const KIND = {
  text: '短答', textarea: '長答', email: 'Email', tel: '電話', url: '網址', number: '數字',
  date: '日期', select: '單選', combobox: '單選', radio: '單選', checkboxes: '複選',
  checkbox: '勾選', file: '檔案',
};
const ACTIVE = ['queued', 'prefilled', 'ready'];
const DONE = ['applied', 'interviewing', 'offer', 'rejected', 'withdrawn'];
const SOURCE_NAMES = {
  'basic.first_name': '名', 'basic.last_name': '姓', 'basic.full_name': '姓名',
  'basic.email': 'Email', 'basic.phone': '電話', resume: '履歷', answers: '答案庫',
  learned: '記住的答案', eeo: 'EEO 設定',
};
const sourceName = (source) => SOURCE_NAMES[source]
  || source.replace(/^employment\[(\d+)\]$/, (_, i) => `工作經歷第 ${Number(i) + 1} 筆`)
    .replace(/^education\[(\d+)\]$/, (_, i) => `學歷第 ${Number(i) + 1} 筆`);

// ---------- helpers ----------

async function api(path, options = {}) {
  const res = await fetch(path, {
    ...options,
    headers: { 'Content-Type': 'application/json', 'X-JR-Token': TOKEN },
  });
  let data = null;
  try { data = await res.json(); } catch { /* empty body */ }
  if (!res.ok) {
    const detail = data && data.detail;
    throw new Error(typeof detail === 'string' ? detail : `HTTP ${res.status}`);
  }
  return data;
}

function h(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === 'class') node.className = value;
    else if (key === 'text') node.textContent = value;
    else if (key.startsWith('on')) node.addEventListener(key.slice(2), value);
    else if (value === true) node.setAttribute(key, '');
    else node.setAttribute(key, value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

let toastTimer;
function toast(message, isError = false) {
  const box = document.getElementById('toast');
  box.textContent = message;
  box.className = `toast show${isError ? ' error' : ''}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { box.className = 'toast'; }, isError ? 7000 : 3500);
}

// The pages run inside the Playwright-controlled Chrome, which dismisses confirm() / alert()
// on its own, so a risky button asks for a second click instead.
function confirmTwice(event, action, prompt = '再按一次確認') {
  const button = event.currentTarget;
  if (button.dataset.armed) {
    delete button.dataset.armed;
    action();
    return;
  }
  const original = button.textContent;
  button.dataset.armed = '1';
  button.textContent = prompt;
  button.classList.add('armed');
  setTimeout(() => {
    if (!button.dataset.armed) return;
    delete button.dataset.armed;
    button.textContent = original;
    button.classList.remove('armed');
  }, 4000);
}

const jobPath = (jobId, action = '') => `/api/applications/${encodeURIComponent(jobId)}${action}`;

// Times come from the server in UTC without a zone.
const parseTime = (value) => new Date(/[zZ]|[+-]\d\d:\d\d$/.test(value) ? value : `${value}Z`);

function formatTime(value) {
  if (!value) return '';
  const d = parseTime(value);
  return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

function formatDate(value) {
  if (!value) return '';
  const d = parseTime(value);
  return `${d.getMonth() + 1}/${d.getDate()}`;
}

function timeAgo(value) {
  if (!value) return '';
  const minutes = Math.round((Date.now() - parseTime(value).getTime()) / 60000);
  if (minutes < 1) return '剛剛';
  if (minutes < 60) return `${minutes} 分鐘前`;
  if (minutes < 60 * 24) return `${Math.round(minutes / 60)} 小時前`;
  if (minutes < 60 * 24 * 7) return `${Math.round(minutes / 60 / 24)} 天前`;
  return formatDate(value);
}

// "San Francisco, CA, US; Palo Alto, CA, US" → "San Francisco, CA, US" and 1 more.
function locationText(location, extra = 0) {
  const places = (location || '').split(';').map((p) => p.trim()).filter(Boolean);
  if (!places.length) return '';
  const more = places.length - 1 + extra;
  return more ? `${places[0]} 等 ${more + 1} 個地點` : places[0];
}

// ---------- small components ----------

// A company's initial on a tint derived from its name, so the same company always looks the same.
function monogram(name, size = '') {
  const text = (name || '').trim() || '?';
  const letter = (text.match(/[A-Za-z0-9\u4e00-\u9fff]/) || ['?'])[0].toUpperCase();
  let hash = 7;
  for (const ch of text) hash = (hash * 31 + ch.codePointAt(0)) >>> 0;
  return h('span', { class: `mono ${size}`, style: `--hue:${hash % 360}`, 'aria-hidden': 'true', text: letter });
}

const statusPill = (status) => h('span', { class: `pill ${status}`, text: STATUS[status] || status });

const spinner = () => h('span', { class: 'spinner', 'aria-hidden': 'true' });

function jobRow(a, { selected = false, side = null, onclick } = {}) {
  const company = a.job.company || SOURCE[a.job.source] || a.job.source;
  return h('button', { class: `job-row${selected ? ' selected' : ''}`, onclick },
    monogram(company),
    h('span', { class: 'job-row-text' },
      h('span', { class: 'job-row-company', text: company }),
      h('span', { class: 'job-row-title', text: a.job.title || a.job.url })),
    side);
}

// ---------- steps ----------

const STEPS = ['開啟申請頁', '自動填寫', '檢查並送出'];

// Questions left for you to answer on the site: everything not filled automatically.
const leftToYou = (form) => form.answers.filter((a) => !a.filled);

// Answers confirmed with ③ in earlier versions; a re-scan of a re-opened tab fills them again.
const confirmedAnswers = (form) => form.answers.filter(
  (a) => a.confirmed || (a.filled && (a.category === 'thought' || a.category === 'suggested')));

// The job was filled in a tab that has since been closed (by accident, or by quitting).
const WORKED_ON = ['prefilled', 'ready'];
const tabClosed = (app, pageOpen) => WORKED_ON.includes(app.status) && !pageOpen;

// Which of the three steps a job is on: 0–2, or 3 once it has been sent.
function stageOf(detail) {
  const { application: app, form } = detail;
  if (DONE.includes(app.status)) return 3;
  if (!form || !form.answers.length) return detail.page_open ? 1 : 0;
  return 2;
}

function stepper(stage) {
  return h('ol', { class: 'stepper', 'aria-label': '申請進度' }, ...STEPS.map((label, i) => h('li', {
    class: i < stage ? 'done' : i === stage ? 'current' : '',
    'aria-current': i === stage ? 'step' : null,
  }, h('span', { class: 'bullet', text: i < stage ? '✓' : String(i + 1) }), h('span', { class: 'step-label', text: label }))));
}

// [title, explanation] for the step a job is on.
function nextStep(detail, drafts) {
  const app = detail.application;
  if (app.status === 'skipped') return ['已略過', '這個職缺不會出現在「進行中」。'];
  if (tabClosed(app, detail.page_open) && detail.form) {
    const n = confirmedAnswers(detail.form).length;
    return ['申請頁已關閉', `按「恢復」重新開啟申請頁並自動填寫${n ? `，也會帶回之前確認過的 ${n} 題` : ''}。直接在申請頁上打的字救不回來。`];
  }
  const stage = stageOf(detail);
  const left = detail.form ? leftToYou(detail.form).length : 0;
  switch (stage) {
    case 0: return ['打開申請頁', '在受控的 Chrome 開啟申請頁。需要登入或要先按 Apply 的網站，請先在瀏覽器裡處理。'];
    case 1: return [drafts ? '自動填寫並產生建議' : '自動填寫', '看到申請表後按 ②：掃描表單，填入基本資料、經歷與答案庫，沒填到的題目會列在下面。'];
    case 2: return ['檢查並送出', `${left ? `到申請頁補上下面列出的 ${left} 題，` : '全部都自動填好了。'}逐欄檢查後自己按網站上的送出，再回來按「我已送出」。`];
    default: return [`${STATUS[app.status]}${app.applied_at ? ` · ${formatDate(app.applied_at)}${app.status === 'applied' ? '' : ' 送出'}` : ''}`, '之後的進度可以在這裡更新。'];
  }
}

// ---------- job actions (both pages show the result their own way) ----------

const prefillLabel = (drafts) => (drafts ? '正在自動填寫並產生建議（約 10–60 秒）' : '正在自動填寫');

async function prefillJob(jobId, resumeVariant = null) {
  const state = await api(jobPath(jobId, '/prefill'), {
    method: 'POST', body: JSON.stringify({ resume_variant: resumeVariant }),
  });
  if (state.blockers.length) return ['需要你先在瀏覽器處理，請看紅色提示', true];
  const filled = state.answers.filter((a) => a.filled).length;
  const left = leftToYou(state).length;
  return [`已自動填寫 ${filled} 題${left ? `，${left} 題請到申請頁自己填` : '，全部填好了'}`, false];
}

function setJobStatus(jobId, status) {
  return api(jobPath(jobId, '/status'), { method: 'POST', body: JSON.stringify({ status }) });
}

// ---------- answers ----------

function banners(form) {
  return [
    ...form.blockers.map((b) => h('div', { class: 'banner block', text: b })),
    ...form.notices.map((n) => h('div', { class: 'banner note', text: n })),
    form.llm_error ? h('div', { class: 'banner block', text: `建議答案：${form.llm_error}` }) : null,
  ].filter(Boolean);
}

// Counts at a glance; each one jumps to its section.
function formStats(form) {
  const left = leftToYou(form);
  const required = left.filter((a) => a.field.required).length;
  const jump = (id) => () => {
    const target = document.getElementById(id);
    if (!target) return;
    const details = target.querySelector('details');
    if (details) details.open = true;
    target.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };
  const stat = (tone, value, label, id) => h('button', { class: `stat ${tone}`, onclick: jump(id) },
    h('span', { class: 'stat-value', text: value }), h('span', { class: 'stat-label', text: label }));
  return h('div', { class: 'stats' },
    stat('good', `${form.answers.length - left.length}/${form.answers.length}`, '已自動填寫', 'sec-auto'),
    stat(left.length ? 'warn' : 'quiet', String(left.length), '要你自己填', 'sec-left'),
    required ? stat('bad', String(required), '其中必填', 'sec-left') : null);
}

// What is left to do on the site, then (folded) what was filled. `jobTitle` hides a section
// heading that is just the job title.
function renderAnswers(form, jobTitle = '') {
  currentJobTitle = jobTitle;
  return [leftSection(leftToYou(form)), autoSection(form.answers.filter((a) => a.filled))].filter(Boolean);
}

// The form part a question sits in ("Employment › Start date month"); the page's top heading
// is usually the job title, which says nothing about the question.
let currentJobTitle = '';
function sectionTag(field) {
  const section = (field.section || '').trim();
  if (!section || section.toLowerCase() === currentJobTitle.trim().toLowerCase()) return null;
  return h('span', { class: 'q-tag', text: section });
}

const WHY = {
  thought: '開放題', suggested: '需要你確認', user: '留給你決定（人口統計、聲明、檔案等）',
};

function leftSection(answers) {
  if (!answers.length) return null;
  // A note every question shares ("no model yet, answer it yourself") is not worth repeating.
  const notes = new Set(answers.map((a) => a.note || ''));
  const shared = notes.size === 1 && answers.length > 1 ? [...notes][0] : '';
  const rows = answers.map((a) => {
    const value = Array.isArray(a.value) ? a.value.join('、') : a.value;
    const hint = a.error ? `沒填進去：${a.error}` : (a.note && a.note !== shared ? a.note : WHY[a.category] || '');
    return h('li', { class: `left-row${a.field.required ? ' required' : ''}` },
      h('div', { class: 'left-q' },
        sectionTag(a.field),
        h('span', { class: 'left-label', text: a.field.label }),
        a.field.required ? h('span', { class: 'q-req', text: '必填' }) : null),
      value ? h('p', { class: 'left-suggest' }, h('span', { class: 'muted', text: '建議：' }), value) : null,
      hint ? h('p', { class: a.error ? 'q-error' : 'q-note', text: hint }) : null);
  });
  return h('section', { class: 'q-section left', id: 'sec-left' },
    h('header', { class: 'q-section-head' },
      h('span', { class: 'dot thought' }), h('h3', { text: '要你在申請頁自己填' }), h('span', { class: 'count', text: String(answers.length) })),
    h('p', { class: 'q-section-desc', text: '依頁面上的順序列出。想之後自動填，把答案寫進 profile/applicant.yaml 的 answers。' }),
    h('ol', { class: 'left-list' }, ...rows));
}

function autoSection(answers) {
  if (!answers.length) return null;
  const rows = answers.map((a) => {
    const value = Array.isArray(a.value) ? a.value.join('、') : a.value;
    return h('div', { class: 'auto-row' },
      h('span', { class: 'mark ok', text: '✓' }),
      h('div', { class: 'auto-q' }, sectionTag(a.field), h('span', { text: a.field.label })),
      h('div', { class: 'auto-a' },
        h('span', { class: 'auto-value', text: value || '（空白）' }),
        h('span', { class: 'auto-source', text: sourceName(a.source) }),
        a.note ? h('p', { class: 'q-note', text: a.note }) : null));
  });
  return h('section', { class: 'q-section auto', id: 'sec-auto' },
    h('details', {},
      h('summary', { class: 'q-section-head' },
        h('span', { class: 'dot auto' }), h('h3', { text: '已自動填寫' }),
        h('span', { class: 'count', text: String(answers.length) }),
        h('span', { class: 'chev', 'aria-hidden': 'true' })),
      h('div', { class: 'auto-list' }, ...rows)));
}
