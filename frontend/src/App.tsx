import { useApp } from './context/AppContext';
import Landing from './components/Landing';
import AuthPage from './components/AuthPage';
import Rail from './components/Rail';
import Topbar from './components/Topbar';
import ChatView from './components/ChatView';
import MemoryGraphView from './components/MemoryGraphView';
import WorkingSetView from './components/WorkingSetView';
import RetrievalView from './components/RetrievalView';
import PipelineView from './components/PipelineView';
import MemoryHealthView from './components/MemoryHealthView';
import ReflectionsView from './components/ReflectionsView';
import CommunitiesView from './components/CommunitiesView';
import TimelineView from './components/TimelineView';
import ResultsView from './components/ResultsView';
import DemoWalkthrough from './components/DemoWalkthrough';

function ViewRouter() {
  const { view } = useApp();
  switch (view) {
    case 'Chat': return <ChatView />;
    case 'Memory Graph': return <div className="view-area"><MemoryGraphView /></div>;
    case 'Session Working Set': return <div className="view-area"><WorkingSetView /></div>;
    case 'Retrieval Trace': return <div className="view-area"><RetrievalView /></div>;
    case 'Memory Pipeline': return <div className="view-area"><PipelineView /></div>;
    case 'Memory Health': return <div className="view-area"><MemoryHealthView /></div>;
    case 'Reflections': return <div className="view-area"><ReflectionsView /></div>;
    case 'Communities': return <div className="view-area"><CommunitiesView /></div>;
    case 'Foresight': return <div className="view-area"><TimelineView /></div>;
    case 'Evaluation': return <div className="view-area"><ResultsView /></div>;
    default: return <ChatView />;
  }
}

export default function App() {
  const { page, authUser, authReady } = useApp();

  if (page === 'landing') return <Landing />;
  if (!authReady) return <AuthPage />;
  if (page === 'auth' || !authUser) return <AuthPage />;

  return (
    <div className="app-shell">
      <Rail />
      <div className="workspace">
        <Topbar />
        <ViewRouter />
      </div>
      <DemoWalkthrough />
    </div>
  );
}
