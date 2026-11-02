// After typing into a date-picker input (react-datepicker): is its calendar open, and which
// day did it read from the typed text? That day is tagged with data-jr-id so SafePage can
// click it, which commits the date the site's way and closes the calendar.
// Read-only apart from the tag.
(fieldId) => {
  const visible = (el) => Boolean(el) && el.getClientRects().length > 0;
  const calendar = Array.from(document.querySelectorAll('.react-datepicker-popper, .react-datepicker')).find(visible);
  if (!calendar) return { open: false, day: '' };
  const day = calendar.querySelector('.react-datepicker__day--selected');
  if (!visible(day)) return { open: true, day: '' };
  day.dataset.jrId = `${fieldId}-day`;
  return { open: true, day: day.dataset.jrId };
}
