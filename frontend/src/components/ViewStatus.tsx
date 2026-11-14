import type { LiveStatus } from '../api/useLiveData';
import LoadingState from './LoadingState';

/**
 * Honest placeholder for a data view that has nothing real to show: a pixel-grid
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
  if (status === 'loading') {
    return (
      <div className="view-empty">
        <LoadingState label="Loading" />
      </div>
    );
  }
  const message =
    status === 'offline'
        ? 'Can’t reach the backend — start the API (make api).'
        : emptyLabel;
  return (
    <div className="view-empty">
      <div className="view-empty-msg">{message}</div>
      {hint && <div className="view-empty-hint">{hint}</div>}
    </div>
  );
}
