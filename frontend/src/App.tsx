import { lazy, Suspense, type ReactNode } from 'react';
import { useApp } from './context/AppContext';
import Landing from './components/Landing';
import AuthPage from './components/AuthPage';
import Rail from './components/Rail';
import Topbar from './components/Topbar';
import ChatView from './components/ChatView';
import DemoWalkthrough from './components/DemoWalkthrough';
import LoadingState from './components/LoadingState';

// The landing page, sign-in and chat load up front. Everything else is split into its own
// chunk: the data views pull in d3 and Recharts, and the developer portal pulls in Shiki,
// so most visitors never download them.
const MemoryGraphView = lazy(() => import('./components/MemoryGraphView'));
const WorkingSetView = lazy(() => import('./components/WorkingSetView'));
const RetrievalView = lazy(() => import('./components/RetrievalView'));
const PipelineView = lazy(() => import('./components/PipelineView'));
const MemoryHealthView = lazy(() => import('./components/MemoryHealthView'));
const ReflectionsView = lazy(() => import('./components/ReflectionsView'));
const CommunitiesView = lazy(() => import('./components/CommunitiesView'));
const TimelineView = lazy(() => import('./components/TimelineView'));
const ResultsView = lazy(() => import('./components/ResultsView'));
const AdminView = lazy(() => import('./components/AdminView'));
const KnowledgeBasesView = lazy(() => import('./components/KnowledgeBasesView'));
const DeveloperPortal = lazy(() => import('./components/DeveloperPortal'));

function ViewArea({ children }: { children: ReactNode }) {
  return (
    <div className="view-area">
      <Suspense fallback={<LoadingState size="page" label="Loading" showElapsed={false} />}>{children}</Suspense>
    </div>
  );
}

function ViewRouter() {
  const { view } = useApp();
  switch (view) {
    case 'Chat': return <ChatView />;
    case 'Memory Graph': return <ViewArea><MemoryGraphView /></ViewArea>;
    case 'Session Working Set': return <ViewArea><WorkingSetView /></ViewArea>;
    case 'Retrieval Trace': return <ViewArea><RetrievalView /></ViewArea>;
    case 'Memory Pipeline': return <ViewArea><PipelineView /></ViewArea>;
    case 'Memory Health': return <ViewArea><MemoryHealthView /></ViewArea>;
    case 'Reflections': return <ViewArea><ReflectionsView /></ViewArea>;
    case 'Communities': return <ViewArea><CommunitiesView /></ViewArea>;
    case 'Foresight': return <ViewArea><TimelineView /></ViewArea>;
    case 'Evaluation': return <ViewArea><ResultsView /></ViewArea>;
    case 'Knowledge Bases': return <ViewArea><KnowledgeBasesView /></ViewArea>;
    case 'Administration': return <ViewArea><AdminView /></ViewArea>;
    default: return <ChatView />;
  }
}

export default function App() {
  const { page, authUser, authReady } = useApp();

  if (window.location.pathname === '/developers' || window.location.pathname.startsWith('/developers/')) {
    return (
      <Suspense fallback={<LoadingState size="page" label="Loading developer portal" showElapsed={false} className="min-h-screen" />}>
        <DeveloperPortal />
      </Suspense>
    );
  }
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
