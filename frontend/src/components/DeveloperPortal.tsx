import { ArrowRight, BookOpen, Code2, LogOut, Moon, ShieldCheck, Sun } from 'lucide-react';
import { api } from '../api/client';
import { useApp } from '../context/AppContext';
import BrandMark from './BrandMark';
import DeveloperDocsView from './DeveloperDocsView';
import DeveloperPlatformView from './DeveloperPlatformView';
import LoadingState from './LoadingState';
import { Eyebrow } from './view';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty';

/* ─────────────────────────────────────────────────────────
 * DEVELOPER PORTAL — /developers/docs and /developers/dashboard
 *
 * Its own page outside the app shell, styled like the landing
 * page: a sticky hairline header with the logo, two sections,
 * the theme toggle and the account. The docs are public; the
 * dashboard needs a signed-in MIRA account.
 * ───────────────────────────────────────────────────────── */

export default function DeveloperPortal() {
  const { authReady, authUser, signOut, theme, toggleTheme } = useApp();
  const path = window.location.pathname.replace(/\/+$/, '') || '/developers';
  const dashboard = path === '/developers/dashboard';

  function signIn() {
    window.sessionStorage.setItem('mira.developerPortalReturnPath', '/developers/dashboard');
    window.location.assign(api.githubAuthUrl());
  }

  const navItem = (href: string, active: boolean, icon: React.ReactNode, label: string) => (
    <Button
      variant="ghost"
      size="sm"
      nativeButton={false}
      aria-current={active ? 'page' : undefined}
      className={cn('relative text-muted-foreground', active && 'text-foreground after:absolute after:inset-x-2 after:-bottom-[13px] after:h-0.5 after:bg-signal')}
      render={<a href={href} />}
    >
      {icon}
      {label}
    </Button>
  );

  return (
    <div className="tw min-h-screen bg-background text-foreground">
      <header className="sticky top-0 z-20 border-b bg-background/90 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-6xl items-center gap-4 px-5">
          <a href="/" className="flex items-center gap-2.5" aria-label="MIRA home">
            <BrandMark lockup size={20} />
            <span className="hidden font-mono text-[11px] tracking-[0.18em] text-muted-foreground uppercase sm:inline">Developers</span>
          </a>
          <nav className="ml-2 flex items-center gap-1" aria-label="Developer portal">
            {navItem('/developers/docs', !dashboard, <BookOpen data-icon="inline-start" />, 'Docs')}
            {navItem('/developers/dashboard', dashboard, <Code2 data-icon="inline-start" />, 'Dashboard')}
          </nav>
          <div className="ml-auto flex items-center gap-1">
            <Button
              variant="ghost"
              size="icon-sm"
              onClick={toggleTheme}
              aria-label={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
            >
              {theme === 'dark' ? <Sun /> : <Moon />}
            </Button>
            {authUser ? (
              <>
                <span className="hidden px-2 font-mono text-xs text-muted-foreground sm:inline">{authUser.username || authUser.name}</span>
                <Button variant="ghost" size="sm" onClick={() => void signOut()}>
                  <LogOut data-icon="inline-start" />
                  Sign out
                </Button>
              </>
            ) : (
              <Button variant="outline" size="sm" nativeButton={false} render={<a href="/developers/dashboard" />}>
                Sign in
              </Button>
            )}
          </div>
        </div>
      </header>

      <main className="px-5 py-10 sm:py-14">
        {dashboard ? (
          !authReady ? (
            <div className="mx-auto max-w-6xl">
              <LoadingState size="page" label="Checking your MIRA account" />
            </div>
          ) : authUser ? (
            <DeveloperPlatformView />
          ) : (
            <Empty className="mx-auto max-w-xl border">
              <EmptyHeader>
                <EmptyMedia variant="icon">
                  <ShieldCheck />
                </EmptyMedia>
                <Eyebrow>Developer dashboard</Eyebrow>
                <EmptyTitle className="text-xl tracking-tight">Manage your MIRA integration.</EmptyTitle>
                <EmptyDescription>
                  Sign in to manage projects, API keys, usage and billing. The API documentation is open to everyone.
                </EmptyDescription>
              </EmptyHeader>
              <EmptyContent className="flex-row justify-center">
                <Button onClick={signIn}>
                  Continue with GitHub
                  <ArrowRight data-icon="inline-end" />
                </Button>
                <Button variant="ghost" nativeButton={false} render={<a href="/developers/docs" />}>
                  Read the docs
                </Button>
              </EmptyContent>
            </Empty>
          )
        ) : (
          <DeveloperDocsView />
        )}
      </main>
    </div>
  );
}
