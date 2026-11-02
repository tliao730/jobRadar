// Is this frame's form ready for input? Server-rendered React apps (Greenhouse job-boards,
// Remix, Next.js) show their inputs before the client hydrates; an input event that arrives
// before hydration can crash the whole app (React #426/#345). Visible form controls count
// as attached once React has put its fiber/props keys on them.
() => {
  const reactKey = (node) => Object.keys(node).some((k) =>
    k.startsWith('__reactFiber$') || k.startsWith('__reactProps$') || k.startsWith('__reactInternalInstance$'));
  const containerKey = (node) => node && Object.keys(node).some((k) =>
    k.startsWith('__reactContainer$') || k === '_reactRootContainer');
  const visible = (el) => el.getClientRects().length > 0;
  const controls = [...document.querySelectorAll('input:not([type=hidden]), select, textarea')].filter(visible);
  const attached = controls.filter(reactKey).length;
  const roots = [document, document.documentElement, document.body,
    ...document.querySelectorAll('body > *, body > * > *')];
  // Server-rendered frameworks leave inline data before any bundle runs; on a cold cache React
  // may not have marked its root yet, but the page is still waiting to hydrate.
  const ssr = !!(window.__remixContext || window.__reactRouterContext
    || window.__staticRouterHydrationData || window.__next_f
    || document.getElementById('__NEXT_DATA__') || document.querySelector('[data-reactroot]'));
  const react = attached > 0 || ssr || roots.some(containerKey);
  return { react, total: controls.length, attached, ready: !react || attached === controls.length };
}
