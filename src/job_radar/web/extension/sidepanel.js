'use strict';
// The panel itself is served by the local assistant (JR_ORIGIN/panel) inside this iframe, so its
// code and token live in one place. This page only tells it which tab is active; the extension
// has no content scripts and never reads or touches the job pages.

const frame = document.getElementById('jr');
const offline = document.getElementById('offline');

async function activeUrl() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return (tab && tab.url) || '';
}

async function sendTab() {
  if (!frame.contentWindow) return;
  frame.contentWindow.postMessage({ type: 'jr-tab', url: await activeUrl() }, JR_ORIGIN);
}

async function connect() {
  try {
    // no-cors: resolves (opaque) whenever the server answers, rejects only when it is down.
    await fetch(`${JR_ORIGIN}/healthz`, { cache: 'no-store', mode: 'no-cors' });
  } catch {
    frame.hidden = true;
    offline.hidden = false;
    setTimeout(connect, 3000);
    return;
  }
  offline.hidden = true;
  frame.hidden = false;
  frame.src = `${JR_ORIGIN}/panel`;
}

window.addEventListener('message', (event) => {
  if (event.origin !== JR_ORIGIN || event.source !== frame.contentWindow) return;
  if (event.data && event.data.type === 'jr-ready') sendTab();
  if (event.data && event.data.type === 'jr-offline') connect();
});
chrome.tabs.onActivated.addListener(sendTab);
chrome.tabs.onUpdated.addListener((_id, info, tab) => {
  if (tab.active && (info.url || info.status === 'complete')) sendTab();
});
connect();
