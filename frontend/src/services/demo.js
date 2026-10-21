import seed from '../data/seedEvents.js';
import { addDays, filterEvents, formatLongDate, fromCsv, toDateKey } from '../utils/events.js';

const RECORDS_KEY = 'pulse-demo-events-v1';
const data = seed.map(fromCsv);
let clarification = null;

function userRecords() {
  try {
    const saved = JSON.parse(localStorage.getItem(RECORDS_KEY) || '[]');
    return Array.isArray(saved) ? saved : [];
  } catch { return []; }
}

function persist(records) {
  localStorage.setItem(RECORDS_KEY, JSON.stringify(records));
}

export function getDemoEvents() {
  return [...data, ...userRecords()];
}

export function resetDemoConversation() {
  clarification = null;
}

export function clearDemoCreatedEvents() {
  localStorage.removeItem(RECORDS_KEY);
  clarification = null;
}

const WEEKDAYS = { понедельник: 1, вторник: 2, среду: 3, четверг: 4, пятницу: 5, субботу: 6, воскресенье: 0 };
const normalize = (s) => s.toLocaleLowerCase('ru').replace(/ё/g, 'е');

export function extractDate(text, now = new Date()) {
  const query = normalize(text);
  const numeric = query.match(/\b(\d{4})-(\d{2})-(\d{2})\b|\b(\d{1,2})[./](\d{1,2})(?:[./](\d{4}))?\b/);
  if (numeric) {
    const year = Number(numeric[1] || numeric[6] || now.getFullYear());
    const month = Number(numeric[2] || numeric[5]);
    const day = Number(numeric[3] || numeric[4]);
    const result = new Date(year, month - 1, day);
    if (result.getFullYear() === year && result.getMonth() === month - 1 && result.getDate() === day) return toDateKey(result);
  }
  if (/послезавтра/.test(query)) return toDateKey(addDays(now, 2));
  if (/завтра/.test(query)) return toDateKey(addDays(now, 1));
  if (/сегодня/.test(query)) return toDateKey(now);
  const hours = query.match(/через\s+(\d+)\s+час/);
  if (hours) return toDateKey(new Date(now.getTime() + Number(hours[1]) * 3600000));
  if (/на следующей неделе/.test(query)) {
    const sinceMonday = (now.getDay() + 6) % 7;
    return toDateKey(addDays(now, 7 - sinceMonday));
  }
  if (/до конца недели/.test(query)) {
    const sinceMonday = (now.getDay() + 6) % 7;
    return toDateKey(addDays(now, 6 - sinceMonday));
  }
  for (const [name, weekday] of Object.entries(WEEKDAYS)) {
    if (new RegExp(`(?<![\\p{L}])${name}(?![\\p{L}])`, 'u').test(query)) {
      const diff = (weekday - now.getDay() + 7) % 7;
      return toDateKey(addDays(now, diff));
    }
  }
  return null;
}

export function extractTime(text, now = new Date()) {
  const query = normalize(text);
  const relative = query.match(/через\s+(\d+)\s+час/);
  if (relative) {
    const later = new Date(now.getTime() + Number(relative[1]) * 3600000);
    return `${String(later.getHours()).padStart(2,'0')}:${String(later.getMinutes()).padStart(2,'0')}`;
  }
  const time = query.match(/(?:^|\s)(?:в\s*)?(\d{1,2}):([0-5]\d)(?=\s|$|[.,!?])/);
  if (time && Number(time[1]) < 24) return `${time[1].padStart(2,'0')}:${time[2]}`;
  const ampm = query.match(/(?:^|\s)в\s+(\d{1,2})(?:\s+час(?:ов|а)?)?\s*(утра|вечера|дня|ночи)?(?=$|\s|[.,!?])/);
  if (!ampm) return null;
  let hour = Number(ampm[1]);
  if (hour > 23) return null;
  if ((ampm[2] === 'вечера' || ampm[2] === 'дня') && hour < 12) hour += 12;
  if (ampm[2] === 'ночи' && hour === 12) hour = 0;
  return `${String(hour).padStart(2,'0')}:00`;
}

function titleFrom(text, type) {
  return text
    .replace(/^(напомни(?:\s+мне)?|создай|добавь|поставь|запиши|запланируй|мне нужно|нужно)\s*/i, '')
    .replace(/^(?:задачу|напоминание|встречу|созвон)\s*/i, '')
    .replace(/(?:сегодня|послезавтра|завтра|на следующей неделе|до конца недели)/gi, '')
    .replace(/(?:в понедельник|во вторник|в среду|в четверг|в пятницу|в субботу|в воскресенье)/gi, '')
    .replace(/(?:в\s+\d{1,2}:\d{2}|в\s+\d{1,2}(?:\s+час(?:ов|а)?)?\s*(?:утра|вечера|дня|ночи)?|через\s+\d+\s+час\w*)/gi, '')
    .replace(/\s+/g, ' ').replace(/^[,:\s]+|[,:.!?\s]+$/g, '')
    .replace(/^у меня встреча/i, 'Встреча')
    .replace(/^нужно\s+/i, '')
    || (type === 'meeting' ? 'Встреча' : 'Новая задача');
}

function replyWithEvents(events, verb = 'Найдено') {
  const top = events.slice(0, 5);
  if (!events.length) return 'По запросу ничего не нашлось. Попробуйте другое слово или период.';
  const word = events.length % 10 === 1 && events.length % 100 !== 11 ? 'запись' : [2,3,4].includes(events.length % 10) && ![12,13,14].includes(events.length % 100) ? 'записи' : 'записей';
  const action = events.length % 10 === 1 && events.length % 100 !== 11 ? 'Найдена' : 'Найдено';
  return `${action} ${events.length} ${word}.\n${top.map(e => `• ${formatLongDate(e.date)}${e.time ? ` в ${e.time}` : ''} — ${e.title}`).join('\n')}${events.length > 5 ? '\nПервые пять результатов показаны выше. Полный список доступен в панели событий.' : ''}`;
}

function lookup(query) {
  const stopWords = new Set(['найди','найти','отыщи','поищи','когда','у','меня','была','был','задачу','задача','встреча','встречу','по','про','старую','старые','где','мои','кто','с','что','я','ставил','покажи','найденные','когда-то']);
  const terms = normalize(query).replace(/[^\p{L}\p{N}\s-]/gu, ' ').split(/\s+/).filter(t => t.length >= 3 && !stopWords.has(t));
  if (!terms.length) return [];
  return getDemoEvents()
    .map(e => ({ e, score: terms.reduce((sum,t) => {
      const words = normalize(e.title).split(/[^\p{L}\p{N}]+/u);
      return sum + (words.some(w => w === t) ? 3 : words.some(w => w.startsWith(t) || t.startsWith(w) && w.length >= 4) ? 2 : normalize(e.title).includes(t) ? 1 : 0);
    }, 0) }))
    .filter(x => x.score > 0)
    .sort((a,b) => b.score - a.score || b.e.date.localeCompare(a.e.date))
    .map(x => x.e);
}

function detectList(query) {
  return /что у меня|какие планы|что запланировано|какие задачи|покажи.*(?:встреч|задач|событи|запис)|есть ли.*встреч|список.*(?:задач|встреч|событи)|расписани|планы на/i.test(query);
}

function detectSearch(query) {
  return /найд|поиск|поищи|отыщи|когда.*(?:был|была).*встреч|когда-то|помню.*задач/i.test(query);
}

function detectCreate(query) {
  return /^(?:напомни|поставь|добавь|создай|запланируй|запиши|мне нужно|нужно)|(?:у меня|будет)\s+встреча|в\s+(?:понедельник|вторник|среду|четверг|пятницу|субботу|воскресенье).*?(?:нужно|встреча)/i.test(query);
}

function addRecord(draft) {
  const event = {
    id: `demo-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    title: draft.title,
    date: draft.date,
    time: draft.time || '',
    type: draft.type,
    status: 'pending',
    source: 'demo',
  };
  persist([...userRecords(), event]);
  return event;
}

export function demoSendMessage(message, now = new Date()) {
  const text = message.trim();
  const q = normalize(text);
  if (!text) return { reply: 'Напишите сообщение.' };

  if (clarification) {
    if (/^(отмена|отмени|не надо|стоп)/i.test(q)) {
      clarification = null;
      return { reply: 'Хорошо, создание отменено.' };
    }
    const date = extractDate(text, now) || clarification.date;
    const time = extractTime(text, now) || clarification.time;
    if (date && (time || clarification.type !== 'meeting')) {
      const created = addRecord({ ...clarification, date, time });
      clarification = null;
      return { reply: `Готово! ${created.type === 'meeting' ? 'Встреча' : 'Задача'} «${created.title}» добавлена на ${formatLongDate(date)}${time ? ` в ${time}` : ''}.`, events: [created] };
    }
    clarification = { ...clarification, date, time };
    return { reply: !date ? 'Уточните дату, пожалуйста. Например: «завтра».' : 'На какое время поставить встречу? Например: «в 15:00».' };
  }

  if (detectSearch(q)) {
    const found = lookup(text);
    return { reply: replyWithEvents(found), events: found.slice(0, 20) };
  }

  if (detectList(q)) {
    const period = /завтра/.test(q) ? 'tomorrow' : /недел/.test(q) ? 'week' : /сегодня/.test(q) ? 'today' : 'upcoming';
    const type = /встреч/.test(q) && !/задач/.test(q) ? 'meeting' : /задач/.test(q) && !/встреч/.test(q) ? 'task' : 'all';
    // The imported CSV doesn't contain type; keep its entries visible for all-events queries.
    const range = period === 'tomorrow' ? { from: toDateKey(addDays(now,1)), to: toDateKey(addDays(now,1)) } : null;
    const filtered = range ? getDemoEvents().filter(e => e.date >= range.from && e.date <= range.to && (type === 'all' || e.type === type)) : filterEvents(getDemoEvents(), { period, type }, now);
    return { reply: replyWithEvents(filtered), events: filtered.slice(0, 20) };
  }

  if (detectCreate(q)) {
    const type = /встреч|созвон/.test(q) ? 'meeting' : /напомни|напоминани/.test(q) ? 'reminder' : 'task';
    const title = titleFrom(text, type);
    const date = extractDate(text, now);
    const time = extractTime(text, now);
    if (!date || (type === 'meeting' && !time)) {
      clarification = { title, date, time, type };
      return { reply: !date ? `Когда запланировать «${title}»? Укажите дату, например «завтра».` : `На какое время назначить встречу «${title}»?` };
    }
    const created = addRecord({ title, date, time, type });
    return { reply: `Готово! ${type === 'meeting' ? 'Встреча' : type === 'reminder' ? 'Напоминание' : 'Задача'} «${title}» добавлена на ${formatLongDate(date)}${time ? ` в ${time}` : ''}.`, events: [created] };
  }

  return { reply: 'Могу создать задачу или встречу, показать планы за период и найти старую запись. Например: «Добавь встречу с командой завтра в 15:00» или «Найди задачу про презентацию».\n\nВ демо-режиме работает упрощённый разбор текста. Понимание произвольных формулировок обеспечит backend с LLM.' };
}
