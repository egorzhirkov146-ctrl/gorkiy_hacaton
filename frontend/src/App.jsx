import { useCallback, useEffect, useRef, useState } from 'react';
import { CalendarDays, Menu, ShieldCheck, Sparkles, Volume2, VolumeX } from 'lucide-react';
import ChatPanel from './components/ChatPanel.jsx';
import EventPanel from './components/EventPanel.jsx';
import Sidebar from './components/Sidebar.jsx';
import { useAudioRecorder } from './hooks/useAudioRecorder.js';
import { useSpeechPlayback } from './hooks/useSpeechPlayback.js';
import { resetDemoConversation } from './services/demo.js';
import { DEMO_MODE, getEvents, sendChat, speechToText } from './services/api.js';

const HISTORY_KEY = 'pulse-chat-history-v1';
const SESSION_KEY = 'pulse-session-v1';
const GREETING = 'Привет! Я Пульс — ваш ассистент по задачам и встречам. ✨\n\nПомогу спланировать день, создать напоминание или найти старую запись. Просто напишите мне или нажмите на микрофон.';
const makeId = () => typeof crypto !== 'undefined' && crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`;
const timeNow = () => new Date().toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
const defaultHistory = () => [{ id: 'welcome', role: 'assistant', text: GREETING, time: timeNow(), welcome: true }];

function savedMessages() {
  try {
    const value = JSON.parse(localStorage.getItem(HISTORY_KEY) || 'null');
    if (Array.isArray(value) && value.length && value.every(m => (m?.role === 'assistant' || m?.role === 'user') && typeof m.text === 'string' && typeof m.id === 'string')) return value.slice(-100);
  } catch { /* localStorage unavailable or invalid */ }
  return defaultHistory();
}

function savedSession() {
  try {
    const value = localStorage.getItem(SESSION_KEY);
    if (value) return value;
  } catch { /* storage disabled */ }
  return makeId();
}

export default function App() {
  const [screen, setScreen] = useState('chat');
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [messages, setMessages] = useState(savedMessages);
  const [sessionId, setSessionId] = useState(savedSession);
  const [draft, setDraft] = useState('');
  const [events, setEvents] = useState([]);
  const [eventsLoading, setEventsLoading] = useState(true);
  const [eventsError, setEventsError] = useState('');
  const [busy, setBusy] = useState(false);
  const [phase, setPhase] = useState(null);
  const [error, setError] = useState('');
  const clearDialog = useRef(null);
  const [soundEnabled, setSoundEnabled] = useState(false);
  const busyRef = useRef(false);
  const inputRef = useRef(null);
  const { play, stop: stopPlayback, speakingId } = useSpeechPlayback();

  useEffect(() => {
    try { localStorage.setItem(HISTORY_KEY, JSON.stringify(messages.slice(-100))); } catch { /* storage disabled */ }
  }, [messages]);
  useEffect(() => {
    try { localStorage.setItem(SESSION_KEY, sessionId); } catch { /* storage disabled */ }
  }, [sessionId]);

  const reloadEvents = useCallback(async () => {
    setEventsLoading(true);
    setEventsError('');
    try { setEvents(await getEvents()); }
    catch (err) { setEventsError(err.message || 'Не удалось получить события.'); }
    finally { setEventsLoading(false); }
  }, []);

  useEffect(() => { reloadEvents(); }, [reloadEvents]);

  const appendMessage = (role, text, relatedEvents = []) => {
    const message = { id: makeId(), role, text, time: timeNow(), events: relatedEvents.slice(0, 3) };
    setMessages(prev => [...prev, message].slice(-100));
    return message;
  };

  const submit = async (message, { fromVoice = false, alreadyLocked = false } = {}) => {
    const text = message?.trim();
    if (!text || (busyRef.current && !alreadyLocked)) return;
    busyRef.current = true;
    setBusy(true);
    setPhase('thinking');
    setError('');
    setDraft('');
    stopPlayback();
    appendMessage('user', text);
    try {
      const result = await sendChat(text, sessionId, messages);
      const response = appendMessage('assistant', result.reply, result.events || []);
      if (result.is_stub) setError('Backend /chat пока работает как заглушка: реальные задачи не создаются. Дождитесь реализации dialog_service.');
      if (result.session_id && result.session_id !== sessionId) setSessionId(result.session_id);
      // A successful /chat can mutate saved events; refresh the side panel.
      void reloadEvents();
      if (soundEnabled || fromVoice) {
        try { await play(response.id, response.text); }
        catch { setError('Ответ готов, но озвучивание не удалось. Нажмите «Прослушать», чтобы повторить.'); }
      }
    } catch (err) {
      setDraft(text);
      setError(err.message || 'Не удалось отправить запрос. Попробуйте снова.');
    } finally {
      busyRef.current = false;
      setBusy(false);
      setPhase(null);
    }
  };

  const onRecorded = async (blob, browserTranscript = '') => {
    if (busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    setPhase('transcribing');
    setError('');
    try {
      const transcript = DEMO_MODE && browserTranscript ? browserTranscript : await speechToText(blob);
      if (!transcript.trim()) throw new Error('Речь не распознана. Попробуйте ещё раз или напишите запрос.');
      await submit(transcript, { fromVoice: true, alreadyLocked: true });
    } catch (err) {
      setError(err.message || 'Ошибка обработки записи.');
    } finally {
      busyRef.current = false;
      setBusy(false);
      setPhase(null);
    }
  };

  const { recording, preparing, seconds, start, stop, cancel } = useAudioRecorder({
    onRecorded,
    enableBrowserSTT: DEMO_MODE,
    onError: (message) => setError(message),
  });

  const clearChat = () => {
    clearDialog.current?.close();
    if (DEMO_MODE) resetDemoConversation();
    stopPlayback();
    setMessages(defaultHistory());
    setDraft('');
    setError('');
    setSessionId(makeId());
  };

  const onPlay = async (id, text) => {
    try { await play(id, text); }
    catch (err) { setError(err.message || 'Не удалось озвучить ответ.'); }
  };

  const handleSuggestion = (text) => { setDraft(text); inputRef.current?.focus(); };

  return <div className="app-shell">
    <Sidebar screen={screen} setScreen={setScreen} demoMode={DEMO_MODE} mobileOpen={mobileMenuOpen} onClose={() => setMobileMenuOpen(false)} />
    <main className="workspace">
      <header className="workspace-header">
        <div className="header-left">
          <button className="menu-button" aria-label="Открыть меню" onClick={() => setMobileMenuOpen(true)}><Menu size={22}/></button>
          <div className="breadcrumb"><span>Моё пространство</span><b>/</b><strong>{screen === 'chat' ? 'Ассистент' : 'Мои события'}</strong></div>
        </div>
        <div className="header-actions">{DEMO_MODE && <span className="header-demo">DEMO</span>}<span className="secure-label"><ShieldCheck size={15}/> Задачи и встречи</span><button className={`sound-toggle ${soundEnabled ? 'sound-toggle-on' : ''}`} onClick={() => { setSoundEnabled(e => !e); stopPlayback(); }} title={soundEnabled ? 'Выключить автоозвучивание' : 'Включить автоозвучивание'} aria-pressed={soundEnabled} aria-label={soundEnabled ? 'Выключить автоозвучивание' : 'Включить автоозвучивание'}>{soundEnabled ? <Volume2 size={18}/> : <VolumeX size={18}/>}</button><div className="user-badge">Я</div></div>
      </header>
      {screen === 'chat' ? <div className="workspace-content">
        <div className="main-chat"><div className="welcome-heading"><div className="welcome-overline"><span className="welcome-star"><Sparkles size={13}/></span> МЕНЬШЕ РУТИНЫ. БОЛЬШЕ ЖИЗНИ.</div><h2>Хороший день начинается с плана.</h2><p>Ваши дела в порядке. Вы можете сосредоточиться на главном.</p></div>
          <ChatPanel messages={messages} draft={draft} setDraft={setDraft} onSend={() => submit(draft)} onAudioStart={() => { stopPlayback(); setError(''); start(); }} onAudioStop={() => stop(false)} onAudioCancel={cancel} recording={recording} preparing={preparing} recordingSeconds={seconds} busy={busy} phase={phase} speakingId={speakingId} onPlay={onPlay} error={error} onDismissError={() => setError('')} onClear={() => clearDialog.current?.showModal()} onTextSuggestion={handleSuggestion} inputRef={inputRef}/>
        </div>
        <aside className="right-aside"><EventPanel events={events} loading={eventsLoading} error={eventsError} onRetry={reloadEvents}/></aside>
      </div> : <div className="all-events-screen"><div className="events-page-header"><div className="welcome-overline"><CalendarDays size={15}/> СОБЫТИЯ</div><h1>Ваши планы <span>✦</span></h1><p>Просматривайте события, фильтруйте записи и возвращайтесь к задачам.</p></div><EventPanel events={events} loading={eventsLoading} error={eventsError} onRetry={reloadEvents} full/></div>}
      <footer className="workspace-footer"><span>Создано для GorkyCode Hackathon</span><span>{DEMO_MODE ? 'Демо-режим · данные в этом браузере' : 'Голосовой ассистент'}</span></footer>
    </main>
    <dialog ref={clearDialog} className="confirm-dialog" aria-labelledby="clear-title"><form method="dialog"><div className="dialog-icon"><Sparkles size={24}/></div><h2 id="clear-title">Начнём с чистого листа?</h2><p>Переписка будет удалена. Ваши задачи и встречи сохранятся.</p><div className="dialog-actions"><button autoFocus value="cancel">Отмена</button><button type="button" className="danger-button" onClick={clearChat}>Очистить чат</button></div></form></dialog>
  </div>;
}
