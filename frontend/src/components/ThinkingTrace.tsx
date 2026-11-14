import { useEffect, useState } from 'react';
import { Check, ChevronDown, Sparkles } from 'lucide-react';

/* ─────────────────────────────────────────────────────────
 * THINKING TRACE — the agent's memory run, as it happens
 *
 * Built from the real `stage` events the chat stream sends
 * (routing, retrieval, verification, …). While the agent works,
 * the trace is open: finished steps get a muted check and their
 * duration, the current one a spinner. When the answer starts
 * streaming it collapses to a one-line summary that stays
 * expandable. Opening or closing it by hand wins over the auto
 * behaviour.
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
  /** no answer text yet: the trace is open and the last step is in progress */
  working: boolean;
  /** when the turn was sent, for the live timer */
  startedAt?: number;
  /** send → first answer token, for the settled summary */
  thoughtMs?: number;
}) {
  const [manual, setManual] = useState<boolean | null>(null);
  const expanded = manual ?? working;
  const now = useNow(working);

  if (!steps.length) return null;

  const elapsed = startedAt ? now - startedAt : 0;
  const current = steps[steps.length - 1];
  const summary = `Worked through ${steps.length} ${steps.length === 1 ? 'step' : 'steps'}${
    thoughtMs !== undefined ? ` in ${formatSeconds(thoughtMs)}` : ''
  }`;

  return (
    <div className={`thinking-trace${working ? ' working' : ''}`}>
      <button
        type="button"
        className="thinking-trace-header"
        aria-expanded={expanded}
        onClick={() => setManual(!expanded)}
      >
        <Sparkles size={14} className="thinking-trace-icon" />
        <span role="status" className="thinking-trace-status">
          {working ? (
            <span className="thinking-trace-active">{stepLabel(current.message)}</span>
          ) : (
            <span className="thinking-trace-done">{summary}</span>
          )}
        </span>
        {working && startedAt && <span className="thinking-trace-elapsed">{formatSeconds(elapsed)}</span>}
        <ChevronDown size={14} className="thinking-trace-chevron" />
      </button>

      <div className={`thinking-trace-body${expanded ? ' open' : ''}`}>
        <div className="thinking-trace-inner">
          <ol className="thinking-trace-steps">
            {steps.map((step, i) => {
              const inProgress = working && i === steps.length - 1;
              const next = steps[i + 1];
              const duration = next ? next.at - step.at : null;
              return (
                <li key={`${step.stage}-${i}`} className="thinking-trace-step">
                  {inProgress ? (
                    <span className="thinking-trace-spinner" aria-label="In progress" />
                  ) : (
                    <Check size={13} strokeWidth={2.5} className="thinking-trace-check" aria-hidden="true" />
                  )}
                  <span className="thinking-trace-label">{stepLabel(step.message)}</span>
                  {duration !== null && duration >= 50 && (
                    <span className="thinking-trace-duration">{formatSeconds(duration)}</span>
                  )}
                </li>
              );
            })}
          </ol>
        </div>
      </div>
    </div>
  );
}
