import test, { beforeEach } from 'node:test';
import assert from 'node:assert/strict';
import { demoSendMessage, extractDate, extractTime, getDemoEvents, clearDemoCreatedEvents, resetDemoConversation } from './demo.js';

const cache = new Map();
globalThis.localStorage = {
  getItem: k => cache.get(k) ?? null,
  setItem: (k, v) => cache.set(k,String(v)),
  removeItem: k => cache.delete(k),
};
beforeEach(() => { clearDemoCreatedEvents(); });

const now = new Date(2026, 9, 21, 14, 30);

test('1000 seed CSV rows are present', () => {
  assert.equal(getDemoEvents().length, 1000);
  assert.equal(getDemoEvents().filter(r => r.source === 'csv').length, 1000);
});

test('recognizes today / tomorrow / the day after tomorrow', () => {
  assert.equal(extractDate('сегодня',now),'2026-10-21');
  assert.equal(extractDate('завтра',now),'2026-10-22');
  assert.equal(extractDate('послезавтра',now),'2026-10-23');
});

test('extracts HH:mm time', () => {
  assert.equal(extractTime('завтра в 15:00',now), '15:00');
  assert.equal(extractTime('в 10 утра',now), '10:00');
  assert.equal(extractTime('через 2 часа',now), '16:30');
});

test('adds meeting into local storage with accurate date', () => {
  const response = demoSendMessage('Добавь встречу с командой завтра в 15:00',now);
  assert.match(response.reply,/добавлена/);
  const meeting = getDemoEvents().find(x => x.source === 'demo');
  assert.ok(meeting);
  assert.equal(meeting.type,'meeting');
  assert.equal(meeting.date,'2026-10-22');
  assert.equal(meeting.time,'15:00');
});

test('asks a clarification then creates the meeting', () => {
  const first = demoSendMessage('Добавь встречу с Иваном завтра',now);
  assert.match(first.reply,/время/);
  const second = demoSendMessage('в 11:00',now);
  assert.match(second.reply,/добавлена/);
});

test('finds historical events from CSV', () => {
  const found = demoSendMessage('Найди задачу про презентацию',now);
  assert.ok(found.events.length > 0);
  assert.match(found.reply,/Найдено/);
});

test('weekday words and conversational creation without hardcoded command', () => {
  assert.equal(extractDate('в пятницу', now), '2026-10-23');
  const response = demoSendMessage('В четверг в 11 у меня встреча с дизайнером', now);
  assert.match(response.reply, /добавлена/);
  const created = getDemoEvents().at(-1);
  assert.equal(created.type, 'meeting');
  assert.equal(created.date, '2026-10-22');
  assert.equal(created.time, '11:00');
});

test('list responds to day query', () => {
  const result = demoSendMessage('Что у меня сегодня?', now);
  assert.ok(typeof result.reply === 'string' && result.reply.length > 10);
});

// Clearing the chat must not complete an old pending meeting or delete saved plans.
test('reset conversation clears pending clarification and preserves events', () => {
  demoSendMessage('Добавь встречу с командой завтра в 15:00', now);
  demoSendMessage('Добавь встречу с Иваном завтра', now);
  const count = getDemoEvents().length;
  resetDemoConversation();
  demoSendMessage('в 11:00', now);
  assert.equal(getDemoEvents().length, count);
  assert.equal(getDemoEvents().at(-1).time, '15:00');
});
