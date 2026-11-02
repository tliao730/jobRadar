// Find the "Add another" button of the repeatable block (work history, education) whose
// fields are tagged `blockIds`, starting from the field `fieldId`; tag the button with
// data-jr-id and return that id ('' if none). The search walks up from the field and stops
// once an ancestor holds a field of another block, so it never reaches a neighbour's button.
// Read-only apart from the tag; SafePage does the click after its own checks.
([fieldId, buttonId, blockIds]) => {
  const ADD = /^\s*\+?\s*add\s+(another|more|employment|experience|position|job|education|school|degree)\b/i;
  const mine = new Set(blockIds);
  const foreign = (node) => Array.from(node.querySelectorAll('input[data-jr-id], select[data-jr-id], textarea[data-jr-id]'))
    .some((el) => !mine.has(el.dataset.jrId));
  let node = document.querySelector(`[data-jr-id="${fieldId}"]`);
  for (let depth = 0; node && depth < 15; depth++, node = node.parentElement) {
    if (foreign(node)) return '';
    const button = Array.from(node.querySelectorAll('button, [role="button"]')).find((b) =>
      b.type !== 'submit' && ADD.test(b.innerText || b.textContent || '') && b.getClientRects().length);
    if (button) {
      button.dataset.jrId = button.dataset.jrId || buttonId;
      return button.dataset.jrId;
    }
  }
  return '';
}
