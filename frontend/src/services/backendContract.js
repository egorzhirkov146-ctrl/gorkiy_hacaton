// Adapters for the API models in backend/schemas/*.py.
import { normalizeEvent } from '../utils/events.js';

export function parseEventList(payload) {
  if (!payload || !Array.isArray(payload.items)) throw new Error('Некорректный ответ /events: ожидается массив items.');
  return payload.items.map(normalizeEvent);
}

export function makeChatRequest(text, sessionId, history = []) {
  return {
    user_id: 1,
    session_id: sessionId,
    text,
    history: history.filter(m => ['user', 'assistant'].includes(m.role) && typeof m.text === 'string' && !m.welcome)
      .slice(-20).map(m => ({ role: m.role, content: m.text })),
  };
}

export function parseChatResponse(payload, sessionId) {
  if (!payload || typeof payload.reply_text !== 'string') throw new Error('Некорректный ответ /chat: отсутствует reply_text.');
  const action = payload.action || {};
  const records = [ ...(Array.isArray(action.records) ? action.records : []), ...(action.record ? [action.record] : []) ];
  return {
    reply: payload.reply_text,
    session_id: typeof payload.session_id === 'string' ? payload.session_id : sessionId,
    events: records.map(normalizeEvent),
    needs_clarification: Boolean(payload.needs_clarification),
    is_stub: payload.reply_text.startsWith('[stub]'),
  };
}

export function parseTtsResponse(payload) {
  if (!payload || typeof payload.audio_url !== 'string' || !payload.audio_url.trim()) {
    throw new Error('Некорректный ответ /tts: отсутствует audio_url.');
  }
  if (payload.audio_url.includes('stub.mp3')) {
    throw new Error('Backend /tts пока возвращает заглушку. Попросите разработчика голосового модуля подключить синтез речи.');
  }
  return payload.audio_url;
}
