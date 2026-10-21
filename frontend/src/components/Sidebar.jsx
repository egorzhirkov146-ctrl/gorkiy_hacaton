import { CalendarDays, Github, Headphones, MessageCircleMore, Sparkles, X } from 'lucide-react';

export default function Sidebar({ screen, setScreen, demoMode, mobileOpen, onClose }) {
  const items = [
    { id: 'chat', label: 'Ассистент', Icon: MessageCircleMore },
    { id: 'events', label: 'Мои события', Icon: CalendarDays },
  ];
  return <>
    {mobileOpen && <button className="mobile-backdrop" aria-label="Закрыть меню" onClick={onClose} />}
    <aside className={`sidebar ${mobileOpen ? 'sidebar-open' : ''}`}>
      <div className="brand">
        <div className="brand-mark"><Sparkles size={23} strokeWidth={2.2} /></div>
        <div><strong>пульс<span>.</span></strong><small>умный помощник</small></div>
        <button className="sidebar-close" aria-label="Закрыть меню" onClick={onClose}><X size={20} /></button>
      </div>
      <div className="sidebar-overline">РАБОЧЕЕ ПРОСТРАНСТВО</div>
      <nav className="side-navigation" aria-label="Основная навигация">
        {items.map(({ id, label, Icon }) => <button key={id} aria-current={screen === id ? 'page' : undefined} className={`side-nav-item ${screen === id ? 'side-nav-active' : ''}`} onClick={() => { setScreen(id); onClose(); }}>
          <Icon size={19}/><span>{label}</span>{screen === id && <span className="nav-dot" />}
        </button>)}
      </nav>
      <div className="sidebar-spacer" />
      <div className="assistant-tip">
        <div className="tip-icon"><Headphones size={18} /></div>
        <strong>Меньше рутины,<br/>больше времени</strong>
        <p>Расскажите о своих планах. Я помогу ничего не забыть.</p>
        <div className="tip-stars">✦ ✧ ✦</div>
      </div>
      <div className="sidebar-foot">
        <div className="mode-indicator"><span className={`mode-dot ${demoMode ? 'mode-dot-demo' : ''}`} />{demoMode ? 'Демо-режим' : 'Режим API'}</div>
        <div className="powered">GORKYCODE HACKATHON <Github size={14}/></div>
      </div>
    </aside>
  </>;
}
