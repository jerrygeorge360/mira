import { createContext, useContext, useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { api, type AuthResponse } from '../api/client';

export interface AuthUser {
  id: string;
  name: string;
  username: string;
  avatarInitial: string;
  provider: 'demo' | 'github';
  avatarUrl: string | null;
  workspaceId: string;
  workspaceName: string;
  expiresAt: string | null;
  isPlatformAdmin: boolean;
}

interface AppState {
  view: string;
  setView: (v: string) => void;
  theme: 'dark' | 'light';
  toggleTheme: () => void;
  page: 'landing' | 'auth' | 'app';
  setPage: (p: 'landing' | 'auth' | 'app') => void;
  authUser: AuthUser | null;
  authReady: boolean;
  signInDemo: () => Promise<void>;
  signOut: () => Promise<void>;
  deleteWorkspaceData: () => Promise<void>;
  activeThread: string;
  setActiveThread: (id: string) => void;
  useRealAgent: boolean;
  setUseRealAgent: (v: boolean) => void;
  sessionId: string | null;
  setSessionId: (id: string | null) => void;
  lastTraceId: string | null;
  setLastTraceId: (id: string | null) => void;
  railCollapsed: boolean;
  setRailCollapsed: (v: boolean) => void;
  historyRefreshKey: number;
  refreshHistory: () => void;
  memoryRefreshKey: number;
  refreshMemory: () => void;
}

const AppCtx = createContext<AppState | null>(null);

export function AppProvider({ children }: { children: ReactNode }) {
  const [view, setView] = useState('Chat');
  const [theme, setTheme] = useState<'dark' | 'light'>(() => {
    const saved = window.localStorage.getItem('mira.theme');
    if (saved === 'dark' || saved === 'light') return saved;
    return window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
  });
  const [page, setPage] = useState<'landing' | 'auth' | 'app'>(() =>
    new URLSearchParams(window.location.search).get('auth') === 'success' ? 'auth' : 'landing'
  );
  const [authUser, setAuthUser] = useState<AuthUser | null>(null);
  const [authReady, setAuthReady] = useState(false);
  const [activeThread, setActiveThread] = useState('new');
  const [useRealAgent, setUseRealAgent] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [lastTraceId, setLastTraceId] = useState<string | null>(null);
  const [railCollapsed, setRailCollapsed] = useState(false);
  const [historyRefreshKey, setHistoryRefreshKey] = useState(0);
  const [memoryRefreshKey, setMemoryRefreshKey] = useState(0);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    window.localStorage.setItem('mira.theme', theme);
  }, [theme]);

  useEffect(() => {
    let active = true;
    api.authMe()
      .then((auth) => {
        if (!active) return;
        setAuthUser(toAuthUser(auth));
        setUseRealAgent(true);
        setPage('app');
        if (window.location.search) window.history.replaceState({}, '', window.location.pathname);
      })
      .catch(() => {
        if (!active) return;
        setAuthUser(null);
      })
      .finally(() => {
        if (active) setAuthReady(true);
      });
    return () => { active = false; };
  }, []);

  const toggleTheme = () => setTheme(t => (t === 'dark' ? 'light' : 'dark'));
  const refreshHistory = () => setHistoryRefreshKey(value => value + 1);
  const refreshMemory = () => setMemoryRefreshKey(value => value + 1);
  const signInDemo = async () => {
    await api.startDemo();
    const auth = await api.authMe();
    setAuthUser(toAuthUser(auth));
    setUseRealAgent(true);
    setPage('app');
  };
  const signOut = async () => {
    try { await api.logout(); } catch { /* Clear local state even if the session expired. */ }
    setAuthUser(null);
    setSessionId(null);
    setActiveThread('new');
    setView('Chat');
    setPage('auth');
  };
  const deleteWorkspaceData = async () => {
    await api.deleteWorkspaceData();
    setSessionId(null);
    setActiveThread('new');
    setLastTraceId(null);
    setView('Chat');
    refreshHistory();
    refreshMemory();
  };

  return (
    <AppCtx.Provider
      value={{ view, setView, theme, toggleTheme, page, setPage, authUser, authReady, signInDemo, signOut, deleteWorkspaceData, activeThread, setActiveThread, useRealAgent, setUseRealAgent, sessionId, setSessionId, lastTraceId, setLastTraceId, railCollapsed, setRailCollapsed, historyRefreshKey, refreshHistory, memoryRefreshKey, refreshMemory }}
    >
      <div className="theme-root" data-theme={theme}>{children}</div>
    </AppCtx.Provider>
  );
}

function toAuthUser(auth: AuthResponse): AuthUser {
  const name = auth.user.display_name || auth.user.github_login || (auth.auth_mode === 'demo' ? 'Demo visitor' : 'Development user');
  return {
    id: auth.user.id || auth.workspace.id,
    name,
    username: auth.user.github_login || auth.auth_mode,
    avatarInitial: name.charAt(0).toUpperCase(),
    provider: auth.auth_mode === 'github' ? 'github' : 'demo',
    avatarUrl: auth.user.avatar_url,
    workspaceId: auth.workspace.id,
    workspaceName: auth.workspace.name,
    expiresAt: auth.expires_at,
    isPlatformAdmin: auth.is_platform_admin,
  };
}

export function useApp() {
  const ctx = useContext(AppCtx);
  if (!ctx) throw new Error('useApp must be inside AppProvider');
  return ctx;
}
