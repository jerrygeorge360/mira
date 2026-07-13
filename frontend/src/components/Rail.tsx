import {
  MessageSquare,
  Network,
  Layers,
  Search,
  Sparkles,
  Users,
  Timeline as TimelineIcon,
  CheckCircle,
  PanelLeftClose,
  PanelLeftOpen,
  Plus,
  Sun,
  Moon,
  LogOut,
} from 'lucide-react';
import { useApp } from '../context/AppContext';
import { api } from '../api/client';
import { useLiveData } from '../api/useLiveData';
import BrandMark from './BrandMark';

// lucide doesn't export Timeline – use a proxy
const TimelineIco = (TimelineIcon as unknown) as React.FC<{ size?: number }>;

const PRIMARY_VIEWS = [
  { label: 'Chat', icon: <MessageSquare size={16} /> },
] as const;

const MEMORY_VIEWS = [
  { label: 'Graph', icon: <Network size={16} /> },
  { label: 'Working Set', icon: <Layers size={16} /> },
  { label: 'Retrieval', icon: <Search size={16} /> },
  { label: 'Reflections', icon: <Sparkles size={16} /> },
  { label: 'Communities', icon: <Users size={16} /> },
  { label: 'Timeline', icon: <TimelineIco size={16} /> },
  { label: 'Results', icon: <CheckCircle size={16} /> },
] as const;

export default function Rail() {
  const {
    view, setView,
    theme, toggleTheme,
    setPage,
    activeThread, setActiveThread,
    sessionId, setSessionId,
    railCollapsed, setRailCollapsed,
    authUser, signOut,
  } = useApp();

  // Refetch when the active session changes so a brand-new conversation appears in history.
  const { data, status } = useLiveData(
    () => api.sessions({ limit: 30 }),
    [sessionId, authUser?.workspaceId],
  );
  const threads = data?.sessions ?? [];

  function startNewChat() {
    setView('Chat');
    setActiveThread('new');
    setSessionId(null);
  }

  function selectThread(id: string) {
    setView('Chat');
    setActiveThread(id);
    setSessionId(id);
  }

  return (
    <nav className={`rail${railCollapsed ? ' collapsed' : ''}`} aria-label="Navigation rail">
      {/* top row */}
      <div className="rail-top">
        {!railCollapsed && (
          <button className="rail-brand" onClick={() => setPage('landing')} title="Back to landing">
            <BrandMark className="brand-mark" size={21} />
            <span>MIRA</span>
          </button>
        )}
        {railCollapsed && (
          <button className="rail-brand" style={{ justifyContent: 'center', width: '100%' }} onClick={() => setPage('landing')}>
            <BrandMark className="brand-mark" size={21} title="MIRA" />
          </button>
        )}
        <button
          className="rail-icon-btn"
          onClick={() => setRailCollapsed(!railCollapsed)}
          title={railCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          {railCollapsed ? <PanelLeftOpen size={16} /> : <PanelLeftClose size={16} />}
        </button>
      </div>

      {/* new chat */}
      {!railCollapsed ? (
        <button className="rail-new-chat" onClick={startNewChat}>
          <Plus size={15} /> New chat
        </button>
      ) : (
        <button className="rail-icon-btn" style={{ margin: '8px auto', display: 'flex' }} onClick={startNewChat} title="New chat">
          <Plus size={16} />
        </button>
      )}

      {/* nav body */}
      <div className="rail-body">
        {/* primary views */}
        {PRIMARY_VIEWS.map(({ label, icon }) => (
          <button
            key={label}
            className={`rail-nav-btn${view === label ? ' active' : ''}`}
            onClick={() => setView(label)}
          >
            {icon}
            {!railCollapsed && label}
          </button>
        ))}

        {/* memory section */}
        {!railCollapsed && <div className="rail-section-label">Memory</div>}
        {MEMORY_VIEWS.map(({ label, icon }) => (
          <button
            key={label}
            className={`rail-nav-btn${view === label ? ' active' : ''}`}
            onClick={() => setView(label)}
            title={railCollapsed ? label : undefined}
          >
            {icon}
            {!railCollapsed && label}
          </button>
        ))}

        {/* history section */}
        {!railCollapsed && (
          <>
            <div className="rail-section-label">History</div>
            {threads.map(t => (
              <button
                key={t.session_id}
                className={`rail-history-btn${activeThread === t.session_id ? ' active' : ''}`}
                onClick={() => selectThread(t.session_id)}
              >
                <h4>{t.title || 'Untitled chat'}</h4>
                <small>{t.message_count} message{t.message_count === 1 ? '' : 's'}</small>
              </button>
            ))}
            {threads.length === 0 && (
              <div className="rail-history-empty">
                {status === 'offline' ? 'Backend offline' : 'No conversations yet'}
              </div>
            )}
          </>
        )}
      </div>

      {/* footer */}
      <div className="rail-footer">
        <div className="rail-avatar">{authUser?.avatarInitial ?? 'D'}</div>
        {!railCollapsed && (
          <div className="rail-user-meta">
            <strong>{authUser?.name ?? 'Demo account'}</strong>
            <small>{authUser?.workspaceName ?? 'Workspace'}</small>
          </div>
        )}
        <button className="theme-toggle" onClick={signOut} title="Sign out">
          <LogOut size={15} />
        </button>
        <button className="theme-toggle" onClick={toggleTheme} title="Toggle theme" style={{ marginLeft: 'auto' }}>
          {theme === 'dark' ? <Sun size={15} /> : <Moon size={15} />}
        </button>
      </div>
    </nav>
  );
}
