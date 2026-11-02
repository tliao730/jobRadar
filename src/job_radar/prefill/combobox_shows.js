// The value a searchable dropdown (react-select) shows next to its input, '' if none. Stops
// at a container that also holds another field, so it never reads a neighbour's value.
(input) => {
  let node = input;
  for (let depth = 0; node && depth < 6; depth++, node = node.parentElement) {
    if (node.querySelectorAll('input[data-jr-id]').length > 1) return '';
    const shown = node.querySelector('[class*="singleValue"], [class*="single-value"]');
    if (shown) return shown.textContent.trim();
  }
  return '';
}
