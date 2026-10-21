import { useMemo, useState } from 'react';
import { CalendarDays, ChevronDown, Search, SlidersHorizontal, RotateCw } from 'lucide-react';
import EventCard from './EventCard.jsx';
import { filterEvents, formatLongDate } from '../utils/events.js';

const PERIODS = [
  { id: 'upcoming', label: 'Ближайшие' },
  { id: 'today', label: 'Сегодня' },
  { id: 'week', label: 'Неделя' },
  { id: 'all', label: 'Все' },
];
const TYPE_OPTIONS = [
  { value: 'all', label: 'Все типы' },
  { value: 'task', label: 'Задачи' },
  { value: 'meeting', label: 'Встречи' },
  { value: 'reminder', label: 'Напоминания' },
  { value: 'event', label: 'Другие события' },
];

export default function EventPanel({ events, loading, error, onRetry, full = false }) {
  const [period, setPeriod] = useState('upcoming');
  const [type, setType] = useState('all');
  const [search, setSearch] = useState('');
  const [limit, setLimit] = useState(8);
  const filtered = useMemo(() => filterEvents(events, {period, type, search}), [events, period, type, search]);
  const shown = filtered.slice(0, limit);
  const isEmpty = !loading && !error && filtered.length === 0;
  return <section className={`event-panel ${full ? 'event-panel-full' : ''}`} aria-label="Задачи и встречи">
    <div className="events-top">
      <div><div className="panel-overline">ВАШЕ РАСПИСАНИЕ</div><h2>Задачи и встречи</h2></div>
      <button className="panel-icon" onClick={onRetry} disabled={loading} aria-label="Обновить события" title="Обновить события"><RotateCw size={17}/></button>
    </div>
    <p className="events-subtitle">Всё важное — под рукой</p>
    <div className="period-tabs" role="group" aria-label="Период событий">
      {PERIODS.map(item => <button key={item.id} aria-pressed={period === item.id} className={period === item.id ? 'tab-active' : ''} onClick={() => { setPeriod(item.id); setLimit(8); }}>{item.label}</button>)}
    </div>
    <div className="event-controls">
      <label className="searchbox"><Search size={16}/><input aria-label="Поиск событий по названию" value={search} onChange={e => { setSearch(e.target.value); setLimit(8); }} placeholder="Поиск по событиям..."/></label>
      <label className="type-select-wrap"><SlidersHorizontal size={15}/><select aria-label="Фильтр по типу" value={type} onChange={e => { setType(e.target.value); setLimit(8); }}>{TYPE_OPTIONS.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}</select><ChevronDown size={13}/></label>
    </div>
    <div className="event-section-heading"><span>{period === 'all' ? 'Все записи' : period === 'today' ? 'На сегодня' : period === 'week' ? 'На этой неделе' : 'Предстоящие'}</span><span className="event-count">{filtered.length}</span></div>
    {loading && <div className="event-message"><div className="spinner"/>Загружаем события…</div>}
    {error && <div className="event-message event-error"><span>{error}</span><button onClick={onRetry}>Повторить</button></div>}
    {isEmpty && <div className="event-empty"><CalendarDays size={27}/><strong>Пока здесь пусто</strong><span>{search ? 'Попробуйте другой запрос' : 'Выберите другой период или добавьте планы в чате'}</span>{(search || type !== 'all' || period !== 'all') && <button className="reset-filters" onClick={() => {setSearch(''); setType('all'); setPeriod('all'); setLimit(8);}}>Показать все события</button>}</div>}
    {!loading && !error && <div className="event-list">{shown.map((event, index) => <div key={event.id} className="event-entry">{(index === 0 || event.date !== shown[index - 1].date) && <h3 className="event-date-heading">{formatLongDate(event.date)}</h3>}<EventCard event={event}/></div>)}</div>}
    {!loading && !error && filtered.length > limit && <button className="show-more" onClick={() => setLimit(l => l + 16)}>Показать ещё <ChevronDown size={16}/></button>}
    <div className="events-footer-note">Добавляйте и уточняйте планы в диалоге с Пульсом.</div>
  </section>;
}
