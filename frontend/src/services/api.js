import { demoSendMessage, getDemoEvents } from './demo.js';
import { makeChatRequest, parseChatResponse, parseEventList, parseTtsResponse } from './backendContract.js';

export const DEMO_MODE = import.meta.env.VITE_DEMO_MODE !== 'false';
const API = (import.meta.env.VITE_API_BASE_URL || '/api').replace(/\/$/, '');

async function request(path, { method = 'GET', json, body, timeout = 30000 } = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  try {
    const res = await fetch(path.startsWith('/static/') ? path : `${API}${path}`, {
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
  return parseEventList(await res.json());
}

export async function sendChat(message, sessionId, history = []) {
  if (DEMO_MODE) return demoSendMessage(message);
  const res = await request('/chat', { method: 'POST', json: makeChatRequest(message, sessionId, history) });
  return parseChatResponse(await res.json(), sessionId);
}

export async function speechToText(blob) {
  if (DEMO_MODE) throw new Error('Для распознавания голоса требуется /stt. Переключите VITE_DEMO_MODE=false и запустите backend.');
  if (!blob || !blob.size) throw new Error('Аудиозапись пуста. Попробуйте снова.');
  const mime = blob.type.split(';')[0].trim();
  const ext = mime.includes('mp4') ? 'm4a' : mime.includes('ogg') ? 'ogg' : mime.includes('wav') ? 'wav' : 'webm';
  const form = new FormData();
  // Backend: async def stt(audio: UploadFile = File(...))
  form.append('audio', blob, `speech.${ext}`);
  const res = await request('/stt', { method: 'POST', body: form, timeout: 45000 });
  const data = await res.json();
  if (typeof data?.text !== 'string') throw new Error('Некорректный ответ /stt: отсутствует text.');
  if (data.text.startsWith('[stub]')) {
    throw new Error('Backend /stt пока возвращает заглушку. Нужен работающий модуль распознавания речи.');
  }
  return data.text.trim();
}

export async function textToSpeech(text) {
  if (DEMO_MODE) return null;
  const res = await request('/tts', { method: 'POST', json: { text }, timeout: 45000 });
  const audioUrl = parseTtsResponse(await res.json());
  // Only relative API URLs are accepted; never pass arbitrary remote URLs to fetch.
  if (!audioUrl.startsWith('/') || audioUrl.startsWith('//') || audioUrl.includes('\\')) {
    throw new Error('Небезопасный URL аудио от /tts. Ожидается относительный путь.');
  }
  const path = audioUrl.startsWith('/api/') ? audioUrl.slice(4) : audioUrl;
  // /static is proxied by Vite alongside /api; production needs matching routing.
  const audioRes = await request(path, { timeout: 45000 });
  const contentType = audioRes.headers.get('content-type') || '';
  if (!contentType.toLowerCase().startsWith('audio/')) throw new Error('Ссылка /tts не вернула аудиофайл.');
  const blob = await audioRes.blob();
  if (!blob.size) throw new Error('Сервис /tts вернул пустое аудио.');
  return blob;
}
