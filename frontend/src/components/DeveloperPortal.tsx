import { ArrowRight, BookOpen, Code2, LogOut, ShieldCheck } from 'lucide-react';
import { api } from '../api/client';
import { useApp } from '../context/AppContext';
import BrandMark from './BrandMark';
import DeveloperDocsView from './DeveloperDocsView';
import DeveloperPlatformView from './DeveloperPlatformView';
import '../developer-portal.css';

export default function DeveloperPortal() {
  const { authReady, authUser, signOut } = useApp();
  const path = window.location.pathname.replace(/\/+$/, '') || '/developers';
  const dashboard = path === '/developers/dashboard';

  function signIn() {
    window.sessionStorage.setItem('mira.developerPortalReturnPath', '/developers/dashboard');
    window.location.assign(api.githubAuthUrl());
  }

  return (
    <div className="developer-portal-shell">
      <header className="developer-portal-header">
        <a className="developer-portal-brand" href="/" aria-label="MIRA home">
          <BrandMark className="brand-mark" size={23} />
          <span>MIRA <small>DEVELOPERS</small></span>
        </a>
        <nav className="developer-portal-nav" aria-label="Developer portal">
          <a href="/developers/docs" aria-current={!dashboard ? 'page' : undefined}>
            <BookOpen size={15} /> Docs
          </a>
          <a href="/developers/dashboard" aria-current={dashboard ? 'page' : undefined}>
            <Code2 size={15} /> Dashboard
          </a>
        </nav>
        <div className="developer-portal-account">
          {authUser ? (
            <>
              <span className="developer-portal-user">{authUser.username || authUser.name}</span>
              <button type="button" onClick={() => void signOut()} aria-label="Sign out">
                <LogOut size={15} /> <span>Sign out</span>
              </button>
            </>
          ) : (
            <a href="/developers/dashboard">Sign in</a>
          )}
        </div>
      </header>

      <main className="developer-portal-main">
        {dashboard ? (
          !authReady ? (
            <div className="developer-portal-message">Checking your MIRA account…</div>
          ) : authUser ? (
            <DeveloperPlatformView />
          ) : (
            <section className="developer-portal-signin">
              <div className="developer-portal-signin-icon"><ShieldCheck size={21} /></div>
              <div className="developer-docs-eyebrow">DEVELOPER DASHBOARD</div>
              <h1>Manage your MIRA integration.</h1>
              <p>Sign in to manage projects, API keys, usage, and billing. The API documentation is available without signing in.</p>
              <button className="developer-button" onClick={signIn}>
                Continue with GitHub <ArrowRight size={15} />
              </button>
              <a className="developer-portal-docs-link" href="/developers/docs">Read the developer docs</a>
            </section>
          )
        ) : (
          <DeveloperDocsView />
        )}
      </main>
    </div>
  );
}
