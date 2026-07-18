import { useEffect, useMemo, useState } from 'react';
import { ArrowLeft, ArrowRight, Compass, X } from 'lucide-react';
import { useApp } from '../context/AppContext';

type GuideStep = {
  view: string;
  label: string;
  title: string;
  body: string;
  task: string;
};

const STEPS: GuideStep[] = [
  {
    view: 'Chat',
    label: 'Conversation',
    title: 'Start with a normal conversation',
    body: 'Ask MIRA something simple, then add a fact or correction. The fast path saves the turn immediately before slower memory work begins.',
    task: 'Try: “My demo deadline is July 20, 2026.”',
  },
  {
    view: 'Memory Pipeline',
    label: 'Lifecycle',
    title: 'Watch the two-speed memory pipeline',
    body: 'This view shows what was persisted immediately, what the worker picked up, and which durable artifacts were produced.',
    task: 'Look for observations, atomic facts, graph edges, reflections, and foresight counts.',
  },
  {
    view: 'Session Working Set',
    label: 'Hot context',
    title: 'Inspect active session memory',
    body: 'Session memory keeps corrections, constraints, open questions, and decisions close to the prompt without pretending everything is durable.',
    task: 'Check the type, scope, priority, source message, and promotion status.',
  },
  {
    view: 'Memory Graph',
    label: 'Graph',
    title: 'Open the typed memory graph',
    body: 'The graph exposes entities, facts, observations, reflections, and relationship edges so memory is inspectable instead of hidden in raw chat history.',
    task: 'Click a node or edge to inspect evidence and relationship details.',
  },
  {
    view: 'Retrieval Trace',
    label: 'Answer trace',
    title: 'See why an answer happened',
    body: 'After a chat turn, the trace shows retrieval mode, evidence, context sources, and memory records used to build the answer.',
    task: 'Ask a question in Chat, then return here to inspect the latest trace.',
  },
  {
    view: 'Reflections',
    label: 'Synthesis',
    title: 'Review higher-level reflections',
    body: 'Reflections are slow-path summaries derived from evidence. They should capture reusable patterns, not random facts.',
    task: 'Confirm each reflection has a clear source and status.',
  },
  {
    view: 'Communities',
    label: 'Clusters',
    title: 'Check memory communities',
    body: 'Communities group related graph memories for broader retrieval. Overlap is visible so duplicate-looking clusters are explainable.',
    task: 'Compare member counts, cohesion, overlap, and merge recommendation.',
  },
  {
    view: 'Foresight',
    label: 'Temporal',
    title: 'Inspect time-bound memory',
    body: 'Foresight records track future commitments and timing-sensitive context. They should appear when a query makes them relevant.',
    task: 'Look for status, validity window, and source observation.',
  },
  {
    view: 'Memory Health',
    label: 'Retention',
    title: 'Check memory pressure and cleanup',
    body: 'Memory Health shows what is active, stale, expired, cancelled, or retained across hot, warm, cold, and time-bound tiers.',
    task: 'Use this after deleting chats to confirm memory actually changed.',
  },
  {
    view: 'Evaluation',
    label: 'Evidence',
    title: 'Read the evaluation story',
    body: 'The result screen summarizes local regression behavior and mechanism checks so the demo is grounded in observed runs.',
    task: 'Open failures and evidence rows when you want to explain the architecture.',
  },
];

export default function DemoWalkthrough() {
  const { authUser, setView, setActiveThread, setSessionId } = useApp();
  const storageKey = useMemo(
    () => `mira.demoGuide.dismissed.${authUser?.workspaceId ?? 'unknown'}`,
    [authUser?.workspaceId],
  );
  const [open, setOpen] = useState(false);
  const [stepIndex, setStepIndex] = useState(0);

  const isDemo = authUser?.provider === 'demo';
  const step = STEPS[stepIndex];

  useEffect(() => {
    if (!isDemo) return;
    if (window.localStorage.getItem(storageKey) === '1') return;
    setOpen(true);
  }, [isDemo, storageKey]);

  useEffect(() => {
    if (!open || !step) return;
    setView(step.view);
    if (step.view === 'Chat') {
      setActiveThread('new');
      setSessionId(null);
    }
  }, [open, setActiveThread, setSessionId, setView, step]);

  if (!isDemo) return null;

  function closeGuide() {
    window.localStorage.setItem(storageKey, '1');
    setOpen(false);
  }

  function showGuide() {
    setStepIndex(0);
    setOpen(true);
  }

  function move(delta: number) {
    setStepIndex((current) => Math.min(Math.max(current + delta, 0), STEPS.length - 1));
  }

  if (!open) {
    return (
      <button className="demo-guide-launcher" onClick={showGuide}>
        <Compass size={16} />
        Guide
      </button>
    );
  }

  return (
    <aside className="demo-guide-panel" aria-label="Demo walkthrough">
      <div className="demo-guide-top">
        <div>
          <span className="demo-guide-kicker">Demo walkthrough</span>
          <h2>{step.title}</h2>
        </div>
        <button className="demo-guide-icon" onClick={closeGuide} aria-label="Close guide">
          <X size={16} />
        </button>
      </div>

      <div className="demo-guide-progress" aria-label={`Step ${stepIndex + 1} of ${STEPS.length}`}>
        {STEPS.map((item, index) => (
          <button
            key={item.label}
            className={index === stepIndex ? 'active' : ''}
            onClick={() => setStepIndex(index)}
            aria-label={`Open ${item.label}`}
          />
        ))}
      </div>

      <div className="demo-guide-meta">
        <strong>{step.label}</strong>
        <span>{stepIndex + 1} / {STEPS.length}</span>
      </div>
      <p>{step.body}</p>
      <div className="demo-guide-task">{step.task}</div>

      <div className="demo-guide-actions">
        <button onClick={() => move(-1)} disabled={stepIndex === 0}>
          <ArrowLeft size={15} />
          Back
        </button>
        {stepIndex === STEPS.length - 1 ? (
          <button className="primary" onClick={closeGuide}>
            Finish
          </button>
        ) : (
          <button className="primary" onClick={() => move(1)}>
            Next
            <ArrowRight size={15} />
          </button>
        )}
      </div>
    </aside>
  );
}
