import { useEffect, useState } from 'react';
import { Check, LoaderCircle } from 'lucide-react';
import {
  Trace,
  TraceCollapsible,
  TraceCollapsibleContent,
  TraceCollapsibleTrigger,
  TraceDescription,
  TraceIcon,
  TraceLine,
  TraceTitle,
} from '@/components/ui/trace';

/* ─────────────────────────────────────────────────────────
 * THINKING TRACE — the agent's memory run, as a Reasoning line
 *
 * The shadcn/ui Reasoning pattern, built from its Trace
 * component: the line reads "Thinking" and is open while the
 * agent works, then reads "Thought for 5s" and closes once the
 * answer starts. Opening or closing it by hand wins over the
 * auto behaviour.
 *
 * MIRA's model sends no reasoning text, so what sits inside is
 * the real `stage` events of the turn (routing, retrieval,
 * verification, …), one TraceLine each: finished steps get a
 * check and their duration, the current one a spinner.
 * ───────────────────────────────────────────────────────── */

export type TraceStep = { stage: string; message: string; at: number };

function formatSeconds(ms: number) {
  const s = ms / 1000;
  return s < 10 ? `${s.toFixed(1)}s` : `${Math.round(s)}s`;
}

/** Backend messages end with a period ("Saving the turn."); rows read better without. */
function stepLabel(message: string) {
  return message.replace(/\.\s*$/, '');
}

function useNow(active: boolean) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const t = setInterval(() => setNow(Date.now()), 100);
    return () => clearInterval(t);
  }, [active]);
  return now;
}

export default function ThinkingTrace({
  steps,
  working,
  startedAt,
  thoughtMs,
}: {
  steps: TraceStep[];
  /** no answer text yet: the line is open and the last step is in progress */
  working: boolean;
  /** when the turn was sent, for the live timer */
  startedAt?: number;
  /** send → first answer token, for the settled title */
  thoughtMs?: number;
}) {
  const [manual, setManual] = useState<boolean>();
  const now = useNow(working);

  if (!steps.length) return null;

  const title = working ? 'Thinking' : thoughtMs !== undefined ? `Thought for ${formatSeconds(thoughtMs)}` : 'Thought';

  return (
    // the chat bubble is pre-wrap for user text; the trace lays itself out
    <Trace className="mb-1.5 whitespace-normal">
      <TraceCollapsible open={manual ?? working} onOpenChange={setManual}>
        <TraceCollapsibleTrigger>
          <TraceLine status={working ? 'running' : undefined}>
            <TraceTitle role="status">{title}</TraceTitle>
            {working && startedAt !== undefined && <TraceDescription>{formatSeconds(now - startedAt)}</TraceDescription>}
          </TraceLine>
        </TraceCollapsibleTrigger>
        <TraceCollapsibleContent>
          <Trace className="gap-1.5">
            {steps.map((step, i) => {
              const inProgress = working && i === steps.length - 1;
              const next = steps[i + 1];
              const duration = next ? next.at - step.at : null;
              return (
                <TraceLine key={`${step.stage}-${i}`} status={inProgress ? 'running' : undefined}>
                  <TraceIcon>{inProgress ? <LoaderCircle className="animate-spin" /> : <Check />}</TraceIcon>
                  <TraceTitle>{stepLabel(step.message)}</TraceTitle>
                  {duration !== null && duration >= 50 && <TraceDescription>{formatSeconds(duration)}</TraceDescription>}
                </TraceLine>
              );
            })}
          </Trace>
        </TraceCollapsibleContent>
      </TraceCollapsible>
    </Trace>
  );
}
