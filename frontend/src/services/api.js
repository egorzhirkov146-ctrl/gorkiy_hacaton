import { demoSendMessage, getDemoEvents } from './demo.js';
import { normalizeEvent } from '../utils/events.js';

export const DEMO_MODE = import.meta.env.VITE_DEMO_MODE !== 'false';
const API = (import.meta.env.VITE_API_BASE_URL || '/api').replace(/\/$/, '');

async function request(path, { method = 'GET', json, body, timeout = 30000 } = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  try {
    const res = await fetch(`${API}${path}`, {
      method,
      headers: json === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: json === undefined ? body : JSON.stringify(json),
      signal: controller.signal,
    });
    if (!res.ok) {
      let detail;
      try { const data = await res.json(); detail = data.detail ?? data.error ?? data.message; } catch { /* no JSON body */ }
      const reason = typeof detail === 'string' ? detail : `Сервер вернул ошибку ${res.status}`;
      throw new Error(reason);
    }
    return res;
  } catch (error) {
    if (error.name === 'AbortError') throw new Error('Сервер долго не отвечает. Повторите запрос.');
    if (error instanceof TypeError) throw new Error('Нет соединения с сервером. Проверьте backend и адрес API.');
    throw error;
  } finally {
    clearTimeout(timer);
  }
}

export async function getEvents() {
  if (DEMO_MODE) return getDemoEvents();
  const res = await request('/events');
  const payload = await res.json();
  const items = Array.isArray(payload) ? payload : payload?.events;
  if (!Array.isArray(items)) throw new Error('Некорректный формат ответа GET /events. Ожидается массив events.');
  return items.map(normalizeEvent);
}

export async function sendChat(message, sessionId) {
  if (DEMO_MODE) return demoSendMessage(message);
  const res = await request('/chat', { method: 'POST', json: { message, session_id: sessionId } });
  const json = await res.json();
  if (typeof json?.reply !== 'string') throw new Error('Некорректный ответ /chat: отсутствует поле reply.');
  return {
    reply: json.reply,
    session_id: typeof json.session_id === 'string' ? json.session_id : sessionId,
    events: Array.isArray(json.events) ? json.events.map(normalizeEvent) : [],
  };
}

export async function speechToText(blob) {
  if (DEMO_MODE) throw new Error('Для распознавания голоса требуется /stt. Переключите VITE_DEMO_MODE=false и запустите backend.');
  if (!blob || !blob.size) throw new Error('Аудиозапись пуста. Попробуйте снова.');
  const mime = blob.type.split(';')[0].trim();
  const ext = mime.includes('mp4') ? 'm4a' : mime.includes('ogg') ? 'ogg' : mime.includes('wav') ? 'wav' : 'webm';
  const form = new FormData();
  form.append('file', blob, `speech.${ext}`);
  const res = await request('/stt', { method: 'POST', body: form, timeout: 45000 });
  const data = await res.json();
  const transcript = data?.text ?? data?.transcript;
  if (typeof transcript !== 'string') throw new Error('Некорректный ответ /stt: отсутствует text.');
  return transcript.trim();
}

export async function textToSpeech(text) {
  if (DEMO_MODE) return null; // In demo mode the browser's built-in voice is used.
  const res = await request('/tts', { method: 'POST', json: { text }, timeout: 45000 });
  const contentType = res.headers.get('content-type') || '';
  if (!contentType.toLowerCase().startsWith('audio/')) {
    throw new Error('Некорректный ответ /tts: ожидается аудиофайл, а не JSON.');
  }
  const blob = await res.blob();
  if (!blob.size) throw new Error('Сервис /tts вернул пустое аудио.');
  return blob;
}
