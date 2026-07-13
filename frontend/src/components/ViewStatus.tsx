import type { LiveStatus } from '../api/useLiveData';

/**
 * Honest placeholder for a data view that has nothing real to show: a spinner-free
 * loading line, an offline notice, or an empty-state message. Never renders fake data.
 */
export function ViewStatus({
  status,
  emptyLabel,
  hint,
}: {
  status: LiveStatus;
  emptyLabel: string;
  hint?: string;
}) {
  const message =
    status === 'loading'
      ? 'Loading…'
      : status === 'offline'
        ? 'Can’t reach the backend — start the API (make api).'
        : emptyLabel;
  return (
    <div className="view-empty">
      <div className="view-empty-msg">{message}</div>
      {status !== 'loading' && hint && <div className="view-empty-hint">{hint}</div>}
    </div>
  );
}
