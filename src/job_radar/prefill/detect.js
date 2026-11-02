// What would stop us: a full-page human check, a login form, or a visible CAPTCHA challenge.
// A small CAPTCHA checkbox on the form itself is only a notice: the person completes it
// before submitting.
() => {
  const shown = (el, minHeight) => {
    const style = getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return style.display !== 'none' && style.visibility !== 'hidden'
      && rect.height >= minHeight && rect.width >= 50;
  };
  const blockers = new Set();
  const notices = new Set();
  const bodyStart = document.body ? document.body.innerText.slice(0, 400) : '';
  const head = `${document.title || ''} ${bodyStart}`;
  const humanCheck = /just a moment|attention required|verify you are (a )?human|are you a robot/i;
  if (humanCheck.test(head)
      || document.querySelector('#challenge-form, #challenge-stage, [id^="cf-chl"]')) {
    blockers.add('captcha_page');
  }
  const passwords = Array.from(document.querySelectorAll('input[type="password"]'));
  if (passwords.some((el) => shown(el, 8))) blockers.add('login');
  for (const frame of document.querySelectorAll('iframe')) {
    const src = frame.getAttribute('src') || '';
    if (!/recaptcha|hcaptcha|challenges\.cloudflare\.com/i.test(src)) continue;
    if (frame.closest('.grecaptcha-badge')) continue; // invisible reCAPTCHA badge
    if (shown(frame, 150)) blockers.add('captcha_challenge');
    else if (shown(frame, 40)) notices.add('captcha_widget');
  }
  return { blockers: Array.from(blockers), notices: Array.from(notices) };
}
