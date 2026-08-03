import { useState, useRef, useEffect } from 'react';
import type { ReactNode } from 'react';
import { Route, Send, Sparkles } from 'lucide-react';
import { useApp } from '../context/AppContext';
import BrandMark from './BrandMark';
import { api } from '../api/client';
import type { LlmUsageSummary } from '../api/client';

type Message = {
  role: 'user' | 'assistant';
  content: string;
  contextScope?: string | null;
  retrievalMode?: string | null;
  traceId?: string | null;
  llmUsage?: LlmUsageSummary | null;
};

export default function ChatView() {
  const {
    activeThread,
    setActiveThread,
    useRealAgent,
    setUseRealAgent,
    sessionId,
    setSessionId,
    setLastTraceId,
    setView,
  } = useApp();
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState('New chat');
  const bottomRef = useRef<HTMLDivElement>(null);
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const streamAbortRef = useRef<AbortController | null>(null);
  // The session whose messages are currently loaded, so we don't reload after sending.
  const loadedRef = useRef<string | null>(null);

  // Load a conversation's turns when a thread is selected from the sidebar (or cleared).
  useEffect(() => {
    if (activeThread === 'new' || !activeThread) {
      setMessages([]);
      setStatus('New chat');
      loadedRef.current = null;
      return;
    }
    if (activeThread === loadedRef.current) return; // already loaded / just created here
    let active = true;
    api
      .sessionMessages(activeThread)
      .then((res) => {
        if (!active) return;
        setMessages(res.messages.map((m) => ({
          role: m.role as Message['role'],
          content: m.content,
          contextScope: m.context_scope,
          retrievalMode: m.retrieval_mode,
          traceId: m.trace_id,
        })));
        setStatus(`${res.messages.length} message${res.messages.length === 1 ? '' : 's'}`);
        loadedRef.current = activeThread;
      })
      .catch(() => {
        if (!active) return;
        setMessages([]);
        loadedRef.current = null;
        setStatus('New chat');
      });
    return () => {
      active = false;
    };
  }, [activeThread]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  useEffect(() => {
    adjustComposerHeight();
  }, [input]);

  useEffect(() => {
    return () => {
      streamAbortRef.current?.abort();
    };
  }, []);

  function adjustComposerHeight() {
    const composer = composerRef.current;
    if (!composer) return;
    composer.style.height = 'auto';
    composer.style.height = `${Math.min(composer.scrollHeight, 170)}px`;
  }

  async function send() {
    const text = input.trim();
    if (!text) return;
    setInput('');
    if (composerRef.current) composerRef.current.style.height = 'auto';
    const next: Message[] = [...messages, { role: 'user', content: text }];
    setMessages(next);
    setLoading(true);

    if (useRealAgent) {
      const body = {
        message: text,
        session_id: sessionId ?? undefined,
      };
      try {
        let assistantText = '';
        const controller = new AbortController();
        streamAbortRef.current = controller;
        await api.chatStream(
          body,
          (event) => {
            if (event.type === 'stage') {
              setStatus(event.message);
              return;
            }
            if (event.type === 'answer') {
              assistantText += event.delta;
              setMessages([...next, { role: 'assistant', content: assistantText }]);
              return;
            }
            if (event.type === 'trace') {
              if (event.session_id) {
                setSessionId(event.session_id);
                if (activeThread !== event.session_id) {
                  loadedRef.current = event.session_id;
                  setActiveThread(event.session_id);
                }
              }
              if (event.trace_id) setLastTraceId(event.trace_id);
              setMessages(current => withRoutingMetadata(current, {
                contextScope: stringValue(event.routing_decision?.context_scope),
                retrievalMode: event.retrieval_mode,
                traceId: event.trace_id,
                llmUsage: event.llm_usage,
              }));
              setStatus(`Real backend · ${event.retrieval_mode}`);
              return;
            }
            if (event.type === 'complete') {
              setStatus('Answer complete');
              return;
            }
            if (event.type === 'cancelled') {
              setStatus('Response stopped');
              return;
            }
            if (event.type === 'error') {
              throw new Error(event.message);
            }
          },
          controller.signal,
        );
        streamAbortRef.current = null;
        if (!assistantText) {
          setMessages([...next, { role: 'assistant', content: 'No answer was returned.' }]);
        }
      } catch (err) {
        streamAbortRef.current = null;
        const message = (err as Error).message;
        if (!message.includes('API 404')) {
          setMessages([...next, { role: 'assistant', content: `Error: ${message}` }]);
          setStatus('Backend error');
        } else {
          const res = await api.chat(body);
          if (res.session_id) {
            setSessionId(res.session_id);
            if (activeThread !== res.session_id) {
              loadedRef.current = res.session_id; // this session's turns are already on screen
              setActiveThread(res.session_id);
            }
          }
          if (res.trace_id) setLastTraceId(res.trace_id);
          setMessages([...next, {
            role: 'assistant',
            content: res.answer,
            contextScope: stringValue(res.routing_decision?.context_scope),
            retrievalMode: res.retrieval_mode,
            traceId: res.trace_id,
            llmUsage: res.llm_usage,
          }]);
          setStatus(`Real backend · ${res.retrieval_mode}`);
        }
      }
    } else {
      await new Promise(r => setTimeout(r, 600));
      const reply =
        "I've pulled context from your durable memory and session working set. The main signal is still active — let me know if you'd like a deeper trace or a retrieval breakdown.";
      setMessages([...next, {
        role: 'assistant',
        content: reply,
        contextScope: 'durable_memory',
        retrievalMode: 'quick',
      }]);
      setStatus('Demo response · quick retrieval');
    }
    setLoading(false);
  }


  return (
    <div className="chat-view">
      {/* messages */}
      <div className="chat-messages">
        {messages.map((m, i) => (
          <div key={i} className={`chat-turn ${m.role}`}>
            {m.role === 'assistant' && <div className="bot-avatar"><BrandMark size={17} /></div>}
            {m.role === 'assistant' ? (
              <div className="assistant-message">
                <div className="chat-bubble"><MarkdownText content={m.content} /></div>
                <RoutingIndicator
                  contextScope={m.contextScope}
                  retrievalMode={m.retrievalMode}
                  traceId={m.traceId}
                  llmUsage={m.llmUsage}
                  onInspect={(traceId) => {
                    setLastTraceId(traceId);
                    setView('Retrieval Trace');
                  }}
                />
              </div>
            ) : (
              <div className="chat-bubble">{m.content}</div>
            )}
          </div>
        ))}

        {messages.length === 0 && !loading && (
          <div className="chat-empty">
            <div className="chat-empty-mark"><BrandMark size={30} /></div>
            <div className="chat-empty-title">What should MIRA remember?</div>
            <div className="chat-empty-sub">
              {useRealAgent
                ? 'Ask naturally. MIRA keeps the conversation, memory, and retrieval trace connected.'
                : 'Demo mode is on. Switch to the live agent when you want real memory writes.'}
            </div>
          </div>
        )}

        {loading && (
          <div className="chat-turn">
            <div className="bot-avatar"><BrandMark size={17} /></div>
            <div className="chat-bubble" style={{ color: 'var(--muted)' }}>
              <span style={{ animation: 'pulse 1s infinite' }}>{status}</span>
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* composer */}
      <div className="chat-composer-shell">
        <div className="chat-runtime-strip">
          <label className="agent-toggle">
            <div className="toggle-switch">
              <input
                type="checkbox"
                checked={useRealAgent}
                onChange={e => setUseRealAgent(e.target.checked)}
              />
              <span className="toggle-slider" />
            </div>
            {useRealAgent ? 'Live memory' : 'Demo mode'}
          </label>
          <span className="chat-status">
            <Sparkles size={13} />
            {status}
          </span>
        </div>
        <div className="chat-composer">
          <textarea
            ref={composerRef}
            className="composer-input"
            placeholder="Message MIRA"
            rows={1}
            value={input}
            onChange={e => {
              setInput(e.target.value);
            }}
            onKeyDown={e => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                send();
              }
            }}
          />
          <button className="composer-send" onClick={send} disabled={loading || !input.trim()} aria-label="Send message">
            <Send size={16} />
          </button>
        </div>
        <div className="chat-disclaimer">MIRA can make mistakes. Verify important details.</div>
      </div>
    </div>
  );
}

function RoutingIndicator({
  contextScope,
  retrievalMode,
  traceId,
  llmUsage,
  onInspect,
}: {
  contextScope?: string | null;
  retrievalMode?: string | null;
  traceId?: string | null;
  llmUsage?: LlmUsageSummary | null;
  onInspect: (traceId: string) => void;
}) {
  if (!contextScope && !retrievalMode) return null;
  const compressionPercent = llmUsage && llmUsage.gateway_input_tokens_original > 0
    ? Math.round(
      (llmUsage.gateway_tokens_saved / llmUsage.gateway_input_tokens_original) * 100,
    )
    : 0;
  const content = (
    <>
      <Route size={12} />
      <span>{routingLabel(contextScope)}</span>
      <span aria-hidden="true">·</span>
      <span>{retrievalLabel(retrievalMode)}</span>
      {llmUsage && llmUsage.calls > 0 && (
        <>
          <span aria-hidden="true">·</span>
          <span title={llmUsage.fully_measured ? 'Provider-reported usage' : 'Includes estimates'}>
            {llmUsage.input_tokens.toLocaleString()} in / {llmUsage.output_tokens.toLocaleString()} out
          </span>
        </>
      )}
      {llmUsage && llmUsage.paritok_calls > 0 && llmUsage.gateway_savings_fully_measured && (
        <>
          <span aria-hidden="true">·</span>
          <span
            className="chat-token-saving"
            title="Request-scoped token reduction reported by the Paritok proxy"
          >
            Paritok saved {llmUsage.gateway_tokens_saved.toLocaleString()} ({compressionPercent}%)
          </span>
        </>
      )}
    </>
  );
  if (!traceId) return <div className="chat-routing-indicator">{content}</div>;
  return (
    <button
      type="button"
      className="chat-routing-indicator is-action"
      onClick={() => onInspect(traceId)}
      title="Open this answer's retrieval trace"
    >
      {content}
    </button>
  );
}

function routingLabel(value?: string | null): string {
  const labels: Record<string, string> = {
    no_retrieval: 'No retrieval context',
    general_knowledge: 'General knowledge',
    recent_conversation: 'Recent conversation',
    session_memory: 'Session memory',
    durable_memory: 'Durable memory',
    mixed: 'Mixed context',
  };
  return value ? labels[value] ?? titleCase(value) : 'Context unavailable';
}

function retrievalLabel(value?: string | null): string {
  if (!value || value === 'general') return 'No durable retrieval';
  return `${titleCase(value)} retrieval`;
}

function titleCase(value: string): string {
  return value
    .replaceAll('_', ' ')
    .replace(/\b\w/g, character => character.toUpperCase());
}

function stringValue(value: unknown): string | null {
  return typeof value === 'string' ? value : null;
}

function withRoutingMetadata(messages: Message[], metadata: Partial<Message>): Message[] {
  let index = -1;
  for (let candidate = messages.length - 1; candidate >= 0; candidate -= 1) {
    if (messages[candidate].role === 'assistant') {
      index = candidate;
      break;
    }
  }
  if (index < 0) return messages;
  const updated = [...messages];
  updated[index] = { ...updated[index], ...metadata };
  return updated;
}

function MarkdownText({ content }: { content: string }) {
  const lines = content.split(/\r?\n/);
  const nodes: ReactNode[] = [];
  let paragraph: string[] = [];
  let listItems: string[] = [];
  let orderedItems: string[] = [];
  let codeLines: string[] = [];
  let inCode = false;

  function flushParagraph() {
    if (!paragraph.length) return;
    nodes.push(
      <p key={`p-${nodes.length}`}>
        {renderInline(paragraph.join(' '))}
      </p>
    );
    paragraph = [];
  }

  function flushList() {
    if (listItems.length) {
      nodes.push(
        <ul key={`ul-${nodes.length}`}>
          {listItems.map((item, index) => (
            <li key={`${index}-${item}`}>{renderInline(item)}</li>
          ))}
        </ul>
      );
      listItems = [];
    }
    if (orderedItems.length) {
      nodes.push(
        <ol key={`ol-${nodes.length}`}>
          {orderedItems.map((item, index) => (
            <li key={`${index}-${item}`}>{renderInline(item)}</li>
          ))}
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
      const level = heading[1].length;
      const text = heading[2];
      const Tag = (`h${level}` as 'h1' | 'h2' | 'h3');
      nodes.push(<Tag key={`h-${nodes.length}`}>{renderInline(text)}</Tag>);
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

  return <div className="chat-markdown">{nodes.length ? nodes : content}</div>;
}

function renderInline(text: string): ReactNode[] {
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
    return part;
  });
}
