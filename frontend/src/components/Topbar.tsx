import { useApp } from '../context/AppContext';

const VIEW_TITLES: Record<string, string> = {
  Chat: 'Chat',
  Graph: 'Memory Graph',
  'Working Set': 'Session Working Set',
  Retrieval: 'Retrieval Trace',
  Reflections: 'Reflections',
  Communities: 'Communities',
  Timeline: 'Foresight Timeline',
  Results: 'Evaluation Results',
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
