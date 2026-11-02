// Describe an element before SafePage clicks it, so submit controls can be refused.
(el) => {
  const tag = el.tagName.toLowerCase();
  const type = (el.getAttribute('type') || '').toLowerCase();
  const label = el.getAttribute('aria-label') || '';
  const text = `${el.innerText || el.value || ''} ${label}`.trim();
  const inForm = !!el.closest('form');
  // A <button> without a type attribute inside a form submits it.
  const submitButton = tag === 'button' && (type === 'submit' || (type === '' && inForm));
  const submitInput = tag === 'input' && (type === 'submit' || type === 'image');
  return {
    tag,
    type,
    role: (el.getAttribute('role') || '').toLowerCase(),
    text,
    submit: submitButton || submitInput,
  };
}
