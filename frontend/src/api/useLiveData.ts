import { useEffect, useState } from 'react';

export type LiveStatus = 'loading' | 'live' | 'offline';

export interface LiveState<T> {
  data: T | null;
  status: LiveStatus;
}

/**
 * Fetch live data from the API with graceful fallback. `status` is 'live' on success,
 * 'offline' if the API is unreachable (so a view can fall back to demo data), 'loading'
 * until the first response. Re-runs when `deps` change.
 */
export function useLiveData<T>(fetcher: () => Promise<T>, deps: unknown[] = []): LiveState<T> {
  const [data, setData] = useState<T | null>(null);
  const [status, setStatus] = useState<LiveStatus>('loading');

  useEffect(() => {
    let active = true;
    setStatus('loading');
    fetcher()
      .then((d) => {
        if (!active) return;
        setData(d);
        setStatus('live');
      })
      .catch(() => {
        if (active) setStatus('offline');
      });
    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return { data, status };
}

/** Format a stored ISO timestamp for compact display; passes through non-ISO strings. */
export function formatTime(value: unknown): string {
  if (typeof value !== 'string' || !value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const today = new Date();
  const sameDay = date.toDateString() === today.toDateString();
  return sameDay
    ? date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    : date.toLocaleDateString([], { month: 'short', day: 'numeric' });
}
