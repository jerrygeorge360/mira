import { useApp } from '../context/AppContext';

const VIEW_TITLES: Record<string, string> = {
  Chat: 'Chat',
  'Memory Graph': 'Memory Graph',
  'Session Working Set': 'Session Working Set',
  'Memory Pipeline': 'Memory Pipeline',
  'Memory Health': 'Memory Health',
  'Retrieval Trace': 'Retrieval Trace',
  Reflections: 'Reflections',
  Communities: 'Communities',
  Foresight: 'Foresight',
  Evaluation: 'Evaluation',
};

export default function Topbar() {
  const { view, authUser } = useApp();
  const title = VIEW_TITLES[view] ?? view;

  return (
    <div className="topbar">
      <div className="topbar-title">
        {title} <span className="topbar-caret">⌄</span>
      </div>
      <span className="plan-pill">
        {authUser?.provider === 'github' ? 'GitHub' : 'Demo'} · <b>{authUser?.workspaceName}</b>
      </span>
    </div>
  );
}
