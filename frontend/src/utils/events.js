export const EVENT_TYPES = {
  task: { label: 'Задача', color: 'amber' },
  meeting: { label: 'Встреча', color: 'violet' },
  reminder: { label: 'Напоминание', color: 'blue' },
  event: { label: 'Событие', color: 'slate' },
};

const pad = (n) => String(n).padStart(2, '0');

// Work with local calendar dates, not UTC; avoids +/- one day in non-UTC zones.
export function toDateKey(date) {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

export function addDays(date, days) {
  const next = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  next.setDate(next.getDate() + days);
  return next;
}

export function getRange(period, now = new Date()) {
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  if (period === 'today') return { from: toDateKey(today), to: toDateKey(today) };
  if (period === 'week') {
    const day = (today.getDay() + 6) % 7;
    return { from: toDateKey(addDays(today, -day)), to: toDateKey(addDays(today, 6 - day)) };
  }
  if (period === 'upcoming') return { from: toDateKey(today), to: null };
  return { from: null, to: null };
}

export function fromCsv(row) {
  return {
    id: `csv-${row.id}`,
    title: row.text,
    date: row.date,
    time: row.time,
    type: 'event', // CSV lacks type. Do not invent task/meeting labels.
    status: null,  // CSV lacks status. No invented completion state.
    source: 'csv',
  };
}

export function normalizeEvent(raw) {
  const title = raw?.title ?? raw?.text ?? raw?.name ?? '';
  const rawDate = raw?.date ?? raw?.scheduled_date ?? raw?.start_date ?? '';
  const date = String(rawDate).slice(0, 10);
  const rawTime = raw?.time ?? raw?.scheduled_time ?? (String(rawDate).includes('T') ? String(rawDate).slice(11, 16) : '');
  const type = EVENT_TYPES[raw?.type] ? raw.type : 'event';
  return {
    id: String(raw?.id ?? `${title}:${date}:${rawTime}`),
    title: String(title),
    date,
    time: String(rawTime).slice(0, 5),
    type,
    status: raw?.status ?? null,
    source: raw?.source ?? 'backend',
  };
}

export function sortEvents(events) {
  return [...events].sort((a, b) => `${a.date}T${a.time || '00:00'}`.localeCompare(`${b.date}T${b.time || '00:00'}`));
}

export function filterEvents(events, { period = 'upcoming', type = 'all', search = '' } = {}, now = new Date()) {
  const { from, to } = getRange(period, now);
  const query = search.trim().toLocaleLowerCase('ru');
  return sortEvents(events.filter((event) => (
    (!from || event.date >= from) &&
    (!to || event.date <= to) &&
    (type === 'all' || event.type === type) &&
    (!query || event.title.toLocaleLowerCase('ru').includes(query))
  )));
}

export function formatDate(dateStr) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(String(dateStr))) return 'Без даты';
  const date = new Date(`${dateStr}T12:00:00`);
  if (Number.isNaN(date.getTime())) return dateStr;
  return new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'short' }).format(date);
}

export function formatLongDate(dateStr) {
  const date = new Date(`${dateStr}T12:00:00`);
  if (Number.isNaN(date.getTime())) return dateStr || 'без даты';
  return new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'long' }).format(date);
}
