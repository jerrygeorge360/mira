import { Unplug } from 'lucide-react';
import type { LiveStatus } from '../api/useLiveData';
import LoadingState from './LoadingState';
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty';

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
      <Empty className="border">
        <LoadingState label="Loading" />
      </Empty>
    );
  }
  const offline = status === 'offline';
  return (
    <Empty className="border">
      <EmptyHeader>
        {offline && (
          <EmptyMedia variant="icon">
            <Unplug />
          </EmptyMedia>
        )}
        <EmptyTitle>{offline ? 'Can’t reach the backend' : emptyLabel}</EmptyTitle>
        {(offline || hint) && (
          <EmptyDescription>
            {offline ? (
              <>
                Start the API with <code className="font-mono">make api</code>, then reload.
              </>
            ) : (
              hint
            )}
          </EmptyDescription>
        )}
      </EmptyHeader>
    </Empty>
  );
}
