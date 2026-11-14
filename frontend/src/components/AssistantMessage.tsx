import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { Check, ChevronDown, Copy, CornerDownRight, RotateCcw } from 'lucide-react';
import ThinkingTrace, { type TraceStep } from './ThinkingTrace';

/* ─────────────────────────────────────────────────────────
 * ASSISTANT MESSAGE — streaming text for the chat thread
 *
 * Words resolve out of blur as they stream in. Bursty network
 * deltas are smoothed into a steady word cadence that speeds up
 * when it falls behind. Once the answer is complete, the action
 * row fades in: copy, retry, and a toggle listing the memory and
 * session items retrieval actually used, with a link to the trace.
 *
 * Only real data is shown — no sources row when retrieval used
 * nothing, no follow-ups (the backend does not suggest any).
 * Messages loaded from history render instantly, unanimated.
 * ───────────────────────────────────────────────────────── */

const WORD_MS = 40;

export type MessageMeta = {
  usedMemoryItems: string[];
  usedSessionItems: string[];
  traceId: string | null;
  retrievalMode: string | null;
};

/** Reveal `content` word by word. Returns the visible prefix and whether it has caught up. */
function useReveal(content: string, animate: boolean) {
  const tokens = content.split(/(?<=\s)/); // words with their trailing whitespace
  const total = tokens.length;
  const [shown, setShown] = useState(animate ? 0 : total);

  useEffect(() => {
    if (!animate) {
      setShown(total);
      return;
    }
    if (shown >= total) return;
    // background tabs throttle timers to ~1/s; nobody is watching, so don't animate
    if (document.hidden) {
      setShown(total);
      return;
    }
    const backlog = total - shown;
    const t = setTimeout(() => setShown((s) => Math.min(total, s + Math.max(1, Math.ceil(backlog / 10)))), WORD_MS);
    return () => clearTimeout(t);
  }, [shown, total, animate]);

  const visible = shown >= total ? content : tokens.slice(0, shown).join('');
  return { visible, caughtUp: shown >= total };
}

export default function AssistantMessage({
  content,
  animate = false,
  streaming = false,
  meta,
  steps,
  startedAt,
  thoughtMs,
  onRetry,
  onOpenTrace,
}: {
  content: string;
  /** reveal word by word (new answers); false for history */
  animate?: boolean;
  /** the backend is still sending this answer */
  streaming?: boolean;
  meta?: MessageMeta;
  /** stage events for this turn (live answers only) */
  steps?: TraceStep[];
  startedAt?: number;
  thoughtMs?: number;
  /** offered only on the latest answer */
  onRetry?: () => void;
  onOpenTrace?: (traceId: string) => void;
}) {
  const { visible, caughtUp } = useReveal(content, animate);
  const done = caughtUp && !streaming;
  const shown = done ? visible : tidyPartial(visible);
  const [copied, setCopied] = useState(false);
  const [sourcesOpen, setSourcesOpen] = useState(false);

  const memory = meta?.usedMemoryItems ?? [];
  const session = meta?.usedSessionItems ?? [];
  const usedCount = memory.length + session.length;
  const hasSources = usedCount > 0 || Boolean(meta?.traceId);

  async function copy() {
    try {
      await navigator.clipboard.writeText(content);
      setCopied(true);
      setTimeout(() => setCopied(false), 1400);
    } catch {
      /* clipboard blocked; leave the icon as is */
    }
  }

  return (
    <div className="assistant-message">
      {steps && steps.length > 0 && (
        <ThinkingTrace steps={steps} working={streaming && !content} startedAt={startedAt} thoughtMs={thoughtMs} />
      )}
      {content && <MarkdownText content={shown} animate={animate} caret={!done} />}

      <div className={`assistant-actions${done ? ' visible' : ''}`} aria-hidden={!done}>
        <button type="button" className="assistant-action" onClick={copy} aria-label={copied ? 'Copied' : 'Copy answer'} title={copied ? 'Copied' : 'Copy'} tabIndex={done ? 0 : -1}>
          {copied ? <Check size={14} /> : <Copy size={14} />}
        </button>
        {onRetry && (
          <button type="button" className="assistant-action" onClick={onRetry} aria-label="Retry this answer" title="Retry" tabIndex={done ? 0 : -1}>
            <RotateCcw size={14} />
          </button>
        )}
        {hasSources && (
          <button
            type="button"
            className="assistant-sources-toggle"
            aria-expanded={sourcesOpen}
            onClick={() => setSourcesOpen((o) => !o)}
            tabIndex={done ? 0 : -1}
          >
            <span>
              {usedCount === 0 ? 'No memories used' : `${usedCount} ${usedCount === 1 ? 'item' : 'items'} recalled`}
              {meta?.retrievalMode ? ` · ${meta.retrievalMode}` : ''}
            </span>
            <ChevronDown size={13} className="assistant-sources-chevron" />
          </button>
        )}
      </div>

      {hasSources && (
        <div className={`assistant-sources${done && sourcesOpen ? ' open' : ''}`}>
          <div className="assistant-sources-inner">
            <div className="assistant-sources-list">
              <SourceGroup label="Memory" ids={memory} />
              <SourceGroup label="Session" ids={session} />
              {meta?.traceId && onOpenTrace && (
                <button type="button" className="assistant-trace-link" onClick={() => onOpenTrace(meta.traceId!)}>
                  <CornerDownRight size={12} />
                  Open retrieval trace
                </button>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * While an answer is still arriving, hide markdown that is only half typed so it
 * doesn't flash as literal text: a list or heading marker with no text yet, and
 * an unclosed ** or ` on the last line (the text after it shows plain until it closes).
 */
function tidyPartial(text: string) {
  const lines = text.split('\n');
  const last = lines[lines.length - 1];
  if (/^\s*([-*]|\d+\.|#{1,3})\s*$/.test(last)) {
    lines[lines.length - 1] = '';
  } else {
    let line = last;
    for (const marker of ['**', '`']) {
      if (line.split(marker).length % 2 === 0) {
        const at = line.lastIndexOf(marker);
        line = line.slice(0, at) + line.slice(at + marker.length);
      }
    }
    lines[lines.length - 1] = line;
  }
  return lines.join('\n');
}

function SourceGroup({ label, ids }: { label: string; ids: string[] }) {
  if (!ids.length) return null;
  return (
    <div className="assistant-source-group">
      <span className="assistant-source-label">{label}</span>
      <div className="assistant-source-ids">
        {ids.map((id) => (
          <code key={id} className="assistant-source-id" title={id}>{id}</code>
        ))}
      </div>
    </div>
  );
}

/* ── lightweight markdown (moved from ChatView) ─────────────────── */

export function MarkdownText({ content, animate = false, caret = false }: { content: string; animate?: boolean; caret?: boolean }) {
  const lines = content.split(/\r?\n/);
  const nodes: ReactNode[] = [];
  let paragraph: string[] = [];
  let listItems: string[] = [];
  let orderedItems: string[] = [];
  let codeLines: string[] = [];
  let inCode = false;
  const inline = (text: string) => renderInline(text, animate);

  function flushParagraph() {
    if (!paragraph.length) return;
    nodes.push(<p key={`p-${nodes.length}`}>{inline(paragraph.join(' '))}</p>);
    paragraph = [];
  }

  function flushList() {
    if (listItems.length) {
      nodes.push(
        <ul key={`ul-${nodes.length}`}>
          {listItems.map((item, index) => <li key={index}>{inline(item)}</li>)}
        </ul>
      );
      listItems = [];
    }
    if (orderedItems.length) {
      nodes.push(
        <ol key={`ol-${nodes.length}`}>
          {orderedItems.map((item, index) => <li key={index}>{inline(item)}</li>)}
        </ol>
      );
      orderedItems = [];
    }
  }

  function flushCode() {
    if (!codeLines.length) return;
    nodes.push(
      <pre key={`code-${nodes.length}`}>
        <code>{codeLines.join('\n')}</code>
      </pre>
    );
    codeLines = [];
  }

  for (const line of lines) {
    const trimmed = line.trim();
    if (trimmed.startsWith('```')) {
      if (inCode) {
        flushCode();
        inCode = false;
      } else {
        flushParagraph();
        flushList();
        inCode = true;
      }
      continue;
    }
    if (inCode) {
      codeLines.push(line);
      continue;
    }
    if (!trimmed) {
      flushParagraph();
      flushList();
      continue;
    }
    const heading = /^(#{1,3})\s+(.+)$/.exec(trimmed);
    if (heading) {
      flushParagraph();
      flushList();
      const Tag = `h${heading[1].length}` as 'h1' | 'h2' | 'h3';
      nodes.push(<Tag key={`h-${nodes.length}`}>{inline(heading[2])}</Tag>);
      continue;
    }
    const bullet = /^[-*]\s+(.+)$/.exec(trimmed);
    if (bullet) {
      flushParagraph();
      orderedItems = [];
      listItems.push(bullet[1]);
      continue;
    }
    const ordered = /^\d+\.\s+(.+)$/.exec(trimmed);
    if (ordered) {
      flushParagraph();
      listItems = [];
      orderedItems.push(ordered[1]);
      continue;
    }
    paragraph.push(trimmed);
  }

  flushParagraph();
  flushList();
  if (inCode) flushCode();

  return (
    <div className="chat-markdown">
      {nodes.length ? nodes : content}
      {caret && <span className="stream-caret" aria-hidden="true" />}
    </div>
  );
}

function renderInline(text: string, animate: boolean): ReactNode[] {
  const parts = text.split(/(`[^`]+`|\*\*[^*]+\*\*|\*[^*]+\*)/g).filter(Boolean);
  return parts.map((part, index) => {
    if (part.startsWith('`') && part.endsWith('`')) {
      return <code key={index}>{part.slice(1, -1)}</code>;
    }
    if (part.startsWith('**') && part.endsWith('**')) {
      return <strong key={index}>{part.slice(2, -2)}</strong>;
    }
    if (part.startsWith('*') && part.endsWith('*')) {
      return <em key={index}>{part.slice(1, -1)}</em>;
    }
    if (!animate) return part;
    // stable keys per word, so only newly revealed words mount and run the blur-in
    return (
      <span key={index}>
        {part.split(/(?<=\s)/).map((word, w) => (
          <span key={w} className="stream-word">{word}</span>
        ))}
      </span>
    );
  });
}
