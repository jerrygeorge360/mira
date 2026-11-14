import { useEffect, useId, useState } from 'react';
import { Check, ChevronRight } from 'lucide-react';

/* ─────────────────────────────────────────────────────────
 * THINKING TRACE — the agent's memory run, as a Reasoning line
 *
 * Follows the shadcn/ui Reasoning pattern (a Trace line with a
 * collapsible): the line reads "Thinking" and is open while the
 * agent works, then reads "Thought for 5s" and closes once the
 * answer starts. Opening or closing it by hand wins over the
 * auto behaviour.
 *
 * MIRA's model sends no reasoning text, so what sits inside is
 * the real `stage` events of the turn (routing, retrieval,
 * verification, …): finished steps get a check and their
 * duration, the current one a spinner.
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
  const open = manual ?? working;
  const now = useNow(working);
  const contentId = useId();

  if (!steps.length) return null;

  const title = working ? 'Thinking' : thoughtMs !== undefined ? `Thought for ${formatSeconds(thoughtMs)}` : 'Thought';

  return (
    <div className="reasoning">
      <button
        type="button"
        className="reasoning-trigger"
        aria-expanded={open}
        aria-controls={contentId}
        onClick={() => setManual(!open)}
      >
        <span className="reasoning-line" data-status={working ? 'running' : undefined}>
          <span role="status" className="reasoning-title">
            {title}
          </span>
          {working && startedAt !== undefined && (
            <span className="reasoning-description">{formatSeconds(now - startedAt)}</span>
          )}
        </span>
        <ChevronRight size={14} className="reasoning-chevron" aria-hidden="true" />
      </button>

      <div id={contentId} className={`reasoning-content${open ? ' open' : ''}`} inert={!open}>
        <div className="reasoning-content-clip">
          <ol className="reasoning-steps">
            {steps.map((step, i) => {
              const inProgress = working && i === steps.length - 1;
              const next = steps[i + 1];
              const duration = next ? next.at - step.at : null;
              return (
                <li key={`${step.stage}-${i}`} className="reasoning-step">
                  {inProgress ? (
                    <span className="reasoning-spinner" aria-label="In progress" />
                  ) : (
                    <Check size={13} strokeWidth={2.5} className="reasoning-check" aria-hidden="true" />
                  )}
                  <span className="reasoning-step-label">{stepLabel(step.message)}</span>
                  {duration !== null && duration >= 50 && (
                    <span className="reasoning-description">{formatSeconds(duration)}</span>
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
