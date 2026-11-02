// Enumerate fillable form controls in this document and tag each with data-jr-id.
// Returns plain objects matching job_radar.apply.models.FormField. Read-only apart from the tag.
(frameIndex) => {
  const MAX_LABEL = 300;
  const GENERIC_LABEL = /^(attach|upload|choose( a)? file|browse|select( a)? file|drop files?( here)?)$/i;
  const SKIP_TYPES = new Set(['hidden', 'submit', 'button', 'reset', 'image', 'password']);
  const LABELISH = 'legend, label, [class*="label" i], [class*="question" i], [class*="title" i]';
  const CONTROLS = 'input, select, textarea';

  const squash = (s) => (s || '').replace(/[\s ]+/g, ' ').trim();
  const clean = (s) => squash((s || '').replace(/[*✱]/g, ' '));
  const hasStar = (s) => /[*✱]/.test(s || '');

  // Rendered text (innerText skips hidden status messages), minus text that belongs to
  // nested controls such as a <select>'s options.
  const visibleText = (el) => {
    if (!el) return '';
    let text = el.innerText || el.textContent || '';
    for (const sub of el.querySelectorAll('select, textarea, button, [role="listbox"]')) {
      const inner = sub.innerText || '';
      if (inner) text = text.replace(inner, ' ');
    }
    return text;
  };
  const firstLine = (s) => (s || '').split('\n').map((l) => l.trim()).find(Boolean) || '';

  const byIds = (ids) =>
    (ids || '')
      .split(/\s+/)
      .map((id) => id && document.getElementById(id))
      .filter(Boolean)
      .map(visibleText)
      .join(' ');

  const visible = (el) => {
    const style = getComputedStyle(el);
    if (style.display === 'none' || style.visibility === 'hidden') return false;
    if (parseFloat(style.opacity || '1') === 0) return false;
    const rect = el.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  };

  const usable = (el, type) => {
    if (el.disabled) return false;
    if (type === 'file') return true; // usually hidden behind a styled "Attach" button
    if (el.closest('[aria-hidden="true"]')) return false;
    if (visible(el)) return true;
    if (type === 'radio' || type === 'checkbox') {
      const label = (el.labels && el.labels[0]) || el.closest('label');
      return !!label && visible(label);
    }
    return false;
  };

  // The nearest label-like element before `start` in document order, provided no other
  // question's control sits in between.
  const precedingLabel = (start, own, excludeTexts) => {
    const scope = start.closest('form') || document.body;
    const nodes = Array.from(scope.querySelectorAll(`${LABELISH}, ${CONTROLS}`));
    for (let i = nodes.indexOf(start) - 1; i >= 0; i--) {
      const node = nodes[i];
      if (node.matches(CONTROLS)) {
        if (own.includes(node) || node.type === 'hidden' || node.closest('[aria-hidden="true"]')) continue;
        return '';
      }
      if (own.some((o) => node.contains(o)) || node.querySelector(CONTROLS)) continue;
      const text = clean(visibleText(node));
      if (text && !excludeTexts.includes(text)) return visibleText(node);
    }
    return '';
  };

  const isGeneric = (raw) => !clean(raw) || GENERIC_LABEL.test(clean(raw));

  const labelFor = (el, type) => {
    let raw = '';
    const labelledBy = el.getAttribute('aria-labelledby');
    if (labelledBy) raw = byIds(labelledBy);
    if (!clean(raw) && el.labels && el.labels.length) {
      raw = Array.from(el.labels).map(visibleText).join(' ');
    }
    if (type === 'file' && isGeneric(firstLine(raw))) {
      const group = el.closest('[role="group"]');
      if (group) raw = byIds(group.getAttribute('aria-labelledby')) || group.getAttribute('aria-label') || raw;
    }
    if (isGeneric(raw)) raw = el.getAttribute('aria-label') || raw;
    if (isGeneric(raw)) raw = precedingLabel(el, [el], []) || raw;
    if (!clean(raw)) raw = el.getAttribute('placeholder') || el.getAttribute('name') || '';
    return raw;
  };

  // An option's own label: never a <label> that wraps the whole group.
  const optionText = (el, members) => {
    const ownsOnly = (node) => node && !members.some((m) => m !== el && node.contains(m));
    let raw = '';
    const labels = Array.from(el.labels || []).filter(ownsOnly);
    if (labels.length) raw = visibleText(labels[0]);
    if (!clean(raw) && ownsOnly(el.closest('label'))) raw = visibleText(el.closest('label'));
    if (!clean(raw)) raw = el.getAttribute('aria-label') || '';
    if (!clean(raw) && ownsOnly(el.parentElement)) raw = visibleText(el.parentElement);
    if (!clean(raw)) raw = el.value || '';
    return clean(firstLine(raw));
  };

  const groupLabel = (members, options) => {
    const first = members[0];
    const fieldset = first.closest('fieldset');
    if (fieldset && members.every((m) => fieldset.contains(m))) {
      const legend = fieldset.querySelector('legend');
      if (legend && clean(visibleText(legend))) return visibleText(legend);
    }
    const group = first.closest('[role="radiogroup"], [role="group"]');
    if (group && members.every((m) => group.contains(m))) {
      const text = byIds(group.getAttribute('aria-labelledby')) || group.getAttribute('aria-label');
      if (clean(text)) return text;
    }
    return precedingLabel(first, members, options);
  };

  const comboValue = (el) => {
    const control = el.closest('[class*="control" i]') || el.parentElement;
    const single = control && control.querySelector('[class*="single-value" i], [class*="singleValue" i]');
    return single ? clean(single.textContent) : el.value || '';
  };

  // The heading of the part of the form a control sits in ("Employment", "Education"...):
  // the last short heading-like element before it whose block also contains the control.
  // A heading's block is its nearest ancestor holding form controls, so a section ends with
  // its container and questions after it are not mistaken for, say, education fields.
  const HEADINGS = 'h1, h2, h3, h4, h5, h6, legend, [role="heading"], [class*="header" i], [class*="heading" i]';
  // A question's own label is not a section heading (Ashby styles labels as headings).
  const labelIds = new Set(Array.from(document.querySelectorAll('[aria-labelledby]'))
    .flatMap((el) => el.getAttribute('aria-labelledby').split(/\s+/)));
  const headings = Array.from(document.querySelectorAll(HEADINGS))
    .filter((h) => {
      if (h.querySelector(CONTROLS)) return false;
      if (h.closest('label') || h.querySelector('label') || (h.id && labelIds.has(h.id))) return false;
      const text = clean(firstLine(visibleText(h)));
      return text && text.length <= 60;
    })
    .map((h) => {
      let block = h.parentElement;
      while (block && !block.querySelector(CONTROLS)) block = block.parentElement;
      return { h, block };
    })
    // A heading whose block holds (almost) every control describes the page, not a section
    // (Ashby's job-details sidebar "Compensation" sits beside the whole form).
    .filter(({ block }) => {
      const all = document.querySelectorAll(CONTROLS).length;
      return !block || all < 5 || block.querySelectorAll(CONTROLS).length < 0.9 * all;
    });
  const sectionOf = (el) => {
    const form = el.closest('form');
    let found = null;
    for (const { h, block } of headings) {
      if (h.contains(el)) continue;
      if (!(h.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING)) break;
      // Inside a <form>, only its own headings count (not the JD's "Compensation" above it).
      if (form && !form.contains(h)) continue;
      if (block && block.contains(el)) found = h;
    }
    return found ? clean(firstLine(visibleText(found))).slice(0, 60) : '';
  };

  const required = (el, raw) =>
    el.required || el.getAttribute('aria-required') === 'true' || hasStar(raw);

  let counter = window.__jrCounter || 0;
  const tag = (el) => {
    if (!el.dataset.jrId) el.dataset.jrId = `f${frameIndex}-${counter++}`;
    return el.dataset.jrId;
  };

  const controls = Array.from(document.querySelectorAll(CONTROLS));
  const fields = [];
  const doneGroups = new Set();
  let previous = null;

  for (const el of controls) {
    const tagName = el.tagName.toLowerCase();
    const type = tagName === 'input' ? (el.getAttribute('type') || 'text').toLowerCase() : tagName;
    if (SKIP_TYPES.has(type) || !usable(el, type)) continue;

    if (type === 'radio' || type === 'checkbox') {
      const key = el.name ? `${type}:${el.name}` : null;
      if (key && doneGroups.has(key)) continue;
      if (key) doneGroups.add(key);
      const members = key
        ? controls.filter((c) => c.type === type && c.name === el.name && c.form === el.form && usable(c, type))
        : [el];
      if (type === 'checkbox' && members.length === 1) {
        const raw = labelFor(el, type) || optionText(el, [el]);
        fields.push({
          field_id: tag(el), frame_index: frameIndex, kind: 'checkbox',
          label: clean(raw).slice(0, MAX_LABEL), name: el.name || '', html_id: el.id || '',
          required: required(el, raw), options: [], option_ids: [], max_length: null,
          value: el.checked ? 'true' : '', placeholder: '', autocomplete: '', accept: '',
          section: sectionOf(el),
        });
        continue;
      }
      const options = members.map((m) => optionText(m, members));
      const raw = groupLabel(members, options);
      const ids = members.map(tag);
      fields.push({
        field_id: `g-${ids[0]}`, frame_index: frameIndex,
        kind: type === 'radio' ? 'radio' : 'checkboxes',
        label: clean(raw).slice(0, MAX_LABEL), name: el.name || '', html_id: '',
        required: members.some((m) => required(m, '')) || hasStar(raw),
        options, option_ids: ids, max_length: null,
        value: members.filter((m) => m.checked).map((m) => options[members.indexOf(m)]).join('; '),
        placeholder: '', autocomplete: '', accept: '', section: sectionOf(el),
      });
      continue;
    }

    let kind = 'text';
    let options = [];
    let value = el.value || '';
    if (tagName === 'select') {
      kind = 'select';
      options = Array.from(el.options)
        .filter((o, i) => !(i === 0 && (o.value === '' || /^(select|choose|please|--)/i.test(o.text.trim()))))
        .map((o) => squash(o.text))
        .filter(Boolean);
      const selected = el.options[el.selectedIndex];
      value = selected && selected.value !== '' ? squash(selected.text) : '';
    } else if (tagName === 'textarea') {
      kind = 'textarea';
    } else if (el.getAttribute('role') === 'combobox' || el.getAttribute('aria-autocomplete') === 'list') {
      kind = 'combobox';
      value = comboValue(el);
    } else if (['email', 'tel', 'url', 'number', 'date', 'file'].includes(type)) {
      kind = type;
      if (type === 'file') value = el.files && el.files.length ? el.files[0].name : '';
    }

    let raw = labelFor(el, type);
    // An unlabeled control right after another in the same small group shares its question
    // (Ashby's "Start Date" is a month <select> and an unlabeled year <select>).
    if (!clean(raw) && previous && previous.el.parentElement && previous.el.parentElement.parentElement
        && previous.el.parentElement.parentElement.contains(el)) raw = previous.raw;
    // A file input's label often wraps its "Attach" button; the question is the first line.
    const label = kind === 'file' ? clean(firstLine(raw)) : clean(raw);
    previous = { el, raw };
    fields.push({
      field_id: tag(el), frame_index: frameIndex, kind,
      label: label.slice(0, MAX_LABEL),
      name: el.getAttribute('name') || '', html_id: el.id || '',
      required: required(el, raw), options, option_ids: [],
      max_length: el.maxLength > 0 && el.maxLength < 100000 ? el.maxLength : null,
      value, placeholder: el.getAttribute('placeholder') || '',
      autocomplete: el.getAttribute('autocomplete') || '', accept: el.getAttribute('accept') || '',
      section: sectionOf(el),
      picker: Boolean(el.closest('.react-datepicker__input-container, .react-datepicker-wrapper')),
    });
  }

  window.__jrCounter = counter;
  return fields;
}
