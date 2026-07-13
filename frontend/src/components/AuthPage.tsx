import { useState } from 'react';
import { ArrowRight, GitBranch, ShieldCheck, Sparkles } from 'lucide-react';
import { api } from '../api/client';
import { useApp } from '../context/AppContext';
import BrandMark from './BrandMark';

export default function AuthPage() {
  const { signInDemo, setPage, theme, toggleTheme } = useApp();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function continueWithGithub() {
    window.location.href = api.githubAuthUrl();
  }

  async function continueWithDemo() {
    setBusy(true);
    setError(null);
    try {
      await signInDemo();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Demo access could not be created.');
      setBusy(false);
    }
  }

  return (
    <main className="auth-page">
      <div className="auth-orbit" aria-hidden="true" />

      <section className="auth-panel" aria-labelledby="auth-title">
        <button className="auth-brand" onClick={() => setPage('landing')}>
          <BrandMark className="brand-mark" size={25} />
          <span>MIRA</span>
        </button>

        <div className="auth-copy">
          <div className="auth-kicker">
            <ShieldCheck size={15} />
            Account access
          </div>
          <h1 id="auth-title">Open your MIRA workspace.</h1>
          <p>
            Sign in with GitHub for a personal workspace, or use the demo to inspect the
            memory system without creating an account.
          </p>
        </div>

        <div className="auth-actions">
          <button className="auth-button primary" onClick={continueWithGithub} disabled={busy}>
            <GitBranch size={18} />
            Continue with GitHub
            <ArrowRight size={16} />
          </button>
          <button className="auth-button secondary" onClick={continueWithDemo} disabled={busy}>
            <Sparkles size={18} />
            {busy ? 'Preparing demo…' : 'Use demo account'}
          </button>
        </div>

        {error && <div className="auth-error" role="alert">{error}</div>}

        <div className="auth-note">
          Demo workspaces are isolated and expire automatically. Do not enter private or sensitive information.
        </div>

        <button className="auth-theme" onClick={toggleTheme}>
          {theme === 'dark' ? 'Light mode' : 'Dark mode'}
        </button>
      </section>
    </main>
  );
}
