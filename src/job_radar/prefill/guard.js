// Installed once per document. While window.__jrGuard is true, every way of submitting a
// form is swallowed: the submit event (capture phase, before the site's own handlers) and
// programmatic form.submit() / requestSubmit(). When the guard is off, both pass through,
// so the person's own click on the submit button works normally.
(on) => {
  if (!window.__jrGuardInstalled) {
    window.__jrGuardInstalled = true;
    window.__jrBlocked = 0;
    window.addEventListener('submit', (event) => {
      if (window.__jrGuard) {
        event.preventDefault();
        event.stopImmediatePropagation();
        window.__jrBlocked++;
      }
    }, true);
    const proto = HTMLFormElement.prototype;
    const nativeSubmit = proto.submit;
    proto.submit = function () {
      if (window.__jrGuard) { window.__jrBlocked++; return undefined; }
      return nativeSubmit.call(this);
    };
    if (proto.requestSubmit) {
      const nativeRequest = proto.requestSubmit;
      proto.requestSubmit = function (...args) {
        if (window.__jrGuard) { window.__jrBlocked++; return undefined; }
        return nativeRequest.apply(this, args);
      };
    }
  }
  window.__jrGuard = on;
}
