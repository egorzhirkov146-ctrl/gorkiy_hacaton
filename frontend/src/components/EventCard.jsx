import { BellRing, CalendarCheck2, CalendarClock, Check, Clock3, ListTodo } from 'lucide-react';
import { EVENT_TYPES, formatDate } from '../utils/events.js';

const ICONS = { task: ListTodo, meeting: CalendarClock, reminder: BellRing, event: CalendarCheck2 };

export default function EventCard({ event, compact = false }) {
  const meta = EVENT_TYPES[event.type] || EVENT_TYPES.event;
  const Icon = ICONS[event.type] || CalendarCheck2;
  const complete = ['completed', 'done', 'finished'].includes(event.status);
  return <article className={`event-card ${compact ? 'event-card-compact' : ''}`}>
    <div className={`event-type-icon event-type-${meta.color}`}><Icon size={18}/></div>
    <div className="event-info">
      <div className="event-title" title={event.title}>{event.title}</div>
      <div className="event-meta">
        <span><CalendarClock size={12}/>{formatDate(event.date)}</span>
        {event.time && <span><Clock3 size={12}/>{event.time}</span>}
      </div>
      {!compact && <div className="event-tags">
        <span className={`event-tag event-tag-${meta.color}`}>{meta.label}</span>
        {event.status && <span className={`event-status ${complete ? 'event-status-done' : ''}`}>{complete && <Check size={12} />}{complete ? 'Выполнено' : ({ pending: 'В планах', planned: 'В планах', in_progress: 'В работе', cancelled: 'Отменено' }[event.status] || event.status)}</span>}
      </div>}
    </div>
  </article>;
}
