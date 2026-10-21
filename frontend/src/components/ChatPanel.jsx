import { useEffect, useRef, useState } from 'react';
import { ArrowDown, ArrowUp, AudioLines, CalendarDays, CheckCheck, CircleStop, Mic, Search, Sparkles, Trash2, Volume2, X } from 'lucide-react';
import EventCard from './EventCard.jsx';

const SUGGESTIONS = [
  { label: 'Мои планы на сегодня', text: 'Что у меня сегодня?', Icon: CalendarDays },
  { label: 'Запланировать встречу', text: 'Добавь встречу с командой завтра в 15:00', Icon: CheckCheck },
  { label: 'Найти задачу', text: 'Найди задачу про презентацию', Icon: Search },
];
function Message({ message, speakingId, onPlay }) {
  const assistant = message.role === 'assistant';
  const playing = speakingId === message.id;
  return <article className={`chat-message ${assistant ? 'assistant-message' : 'user-message'}`}>
    {assistant && <div className="message-avatar assistant-avatar"><Sparkles size={16}/></div>}
    <div className="bubble-container">
      <div className="message-author">{assistant ? 'Пульс' : 'Вы'}<time>{message.time}</time></div>
      <div className="message-bubble">{message.text}</div>
      {assistant && !!message.events?.length && <div className="message-events">{message.events.map(event => <EventCard event={event} compact key={event.id}/>)}</div>}
      {assistant && <button className={`speak-reply ${playing ? 'speak-playing' : ''}`} aria-label={playing ? 'Остановить голосовой ответ' : 'Озвучить ответ'} onClick={() => onPlay(message.id, message.text)}>{playing ? <CircleStop size={14}/> : <Volume2 size={14}/>}<span>{playing ? 'Остановить' : 'Прослушать'}</span></button>}
    </div>
  </article>;
}
export default function ChatPanel({ messages, draft, setDraft, onSend, onAudioStart, onAudioStop, onAudioCancel, recording, preparing, recordingSeconds, busy, phase, speakingId, onPlay, error, onDismissError, onClear, onTextSuggestion, inputRef }) {
  const scrollRef = useRef(null);
  const nearBottom = useRef(true);
  const [showJump, setShowJump] = useState(false);
  const empty = messages.every(m => m.welcome);
  const locked = busy || recording || preparing;
  const toBottom = () => {
    const el = scrollRef.current;
    el?.scrollTo({ top: el.scrollHeight, behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
  };
  useEffect(() => {
    if (nearBottom.current || messages.at(-1)?.role === 'user') toBottom();
    else setShowJump(true);
  }, [messages.length, phase, error]);
  useEffect(() => {
    const el = inputRef.current;
    if (el) { el.style.height = 'auto'; el.style.height = `${Math.min(el.scrollHeight, 144)}px`; }
  }, [draft, inputRef]);
  const timer = `${String(Math.floor(recordingSeconds / 60)).padStart(2, '0')}:${String(recordingSeconds % 60).padStart(2, '0')}`;
  return <section className="chat-panel" aria-label="Переписка с ассистентом">
    <div className="chat-heading"><div className="chat-title-group"><div className="chat-heading-mark"><Sparkles size={20}/></div><div><h1>Пульс <span className="ai-label">AI</span></h1><div className="assistant-presence"><span/>{recording ? 'Слушаю вас' : preparing ? 'Ожидаю доступ к микрофону' : busy ? 'Обрабатываю запрос' : 'Готов помочь с планами'}</div></div></div><button className="clear-button" disabled={locked || empty} onClick={onClear} title="Очистить историю переписки"><Trash2 size={15}/><span>Очистить</span></button></div>
    <div className={`chat-scroll ${empty ? 'chat-scroll-empty' : ''}`} ref={scrollRef} onScroll={() => { const el = scrollRef.current; nearBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 90; setShowJump(!nearBottom.current); }} role="log" aria-live="polite" aria-relevant="additions text">
      {empty ? <div className="empty-chat"><div className="hero-symbol"><Sparkles size={32} strokeWidth={1.5}/><span className="orbit-dot"/></div><div className="hero-eyebrow">ПРОСТО НАЧНИТЕ ДИАЛОГ</div><h2>Освободите мысли.<br/><span>Я запомню ваши планы.</span></h2><p>Помогу с задачами и встречами.<br/>Напишите мне или расскажите голосом.</p><div className="suggestions">{SUGGESTIONS.map(({label, text, Icon}) => <button className="suggestion" key={text} disabled={locked} onClick={() => onTextSuggestion(text)}><Icon size={17}/><span>{label}</span><ArrowUp className="suggestion-arrow" size={15}/></button>)}</div></div> : <><div className="chat-day-separator"><span>Ваш диалог</span></div>{messages.filter(m => !m.welcome).map(message => <Message key={message.id} message={message} speakingId={speakingId} onPlay={onPlay}/>)}</>}
      {busy && <div className="chat-message assistant-message typing-row"><div className="message-avatar assistant-avatar"><Sparkles size={16}/></div><div className="thinking-bubble" role="status"><span className="typing-dots"><i/><i/><i/></span>{phase === 'transcribing' ? 'Распознаю речь…' : 'Обдумываю ответ…'}</div></div>}
    </div>
    {showJump && <button className="jump-button" onClick={toBottom}><ArrowDown size={14}/> К последним сообщениям</button>}
    <div className="composer-wrap">
      {error && <div className="chat-error" role="alert"><span>{error}</span><button onClick={onDismissError} aria-label="Закрыть сообщение об ошибке"><X size={17}/></button></div>}
      {preparing && <div className="recording-indicator" role="status"><span className="spinner"/>Разрешите доступ к микрофону в браузере</div>}
      {recording && <div className="recording-indicator" role="status"><span className="recording-pulse"/><span>Запись</span><div className="waveform" aria-hidden="true">{Array.from({length:17}, (_,i) => <b key={i} style={{animationDelay:`${i*0.07}s`}}/>)}</div><time>{timer} / 01:30</time><button onClick={onAudioCancel}>Отменить</button></div>}
      <form className="composer" onSubmit={e => { e.preventDefault(); if (!locked && draft.trim()) onSend(); }}>
        <textarea rows={1} ref={inputRef} value={draft} onChange={e => setDraft(e.target.value)} onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); if (!locked && draft.trim()) onSend(); } }} placeholder={recording ? 'Слушаю вас…' : 'Какие у вас планы?'} aria-label="Введите сообщение" disabled={locked} maxLength={2000}/>
        <div className="composer-actions"><button type="button" className={`mic-button ${recording ? 'mic-recording' : ''}`} onClick={recording ? onAudioStop : onAudioStart} disabled={busy || preparing} aria-label={recording ? 'Завершить и отправить запись' : 'Начать запись голоса'} title={recording ? 'Завершить и отправить' : 'Записать голос'}>{recording ? <CircleStop size={21}/> : <Mic size={20}/>}</button><button type="submit" className="send-button" disabled={locked || !draft.trim()} aria-label="Отправить сообщение"><ArrowUp size={21}/></button></div>
      </form>
      <div className="composer-helper"><span><AudioLines size={13}/> Голосом или текстом</span><span>{draft.length > 1600 ? `${draft.length} / 2000` : 'Enter — отправить · Shift + Enter — новая строка'}</span></div>
    </div>
  </section>;
}
