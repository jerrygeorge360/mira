import { useState, useRef, useEffect } from 'react';
import type { ReactNode } from 'react';
import { Send, Sparkles } from 'lucide-react';
import { useApp } from '../context/AppContext';
import BrandMark from './BrandMark';
import { api } from '../api/client';

type Message = { role: 'user' | 'assistant'; content: string };

export default function ChatView() {
  const {
    activeThread,
    setActiveThread,
    useRealAgent,
    setUseRealAgent,
    sessionId,
    setSessionId,
    setLastTraceId,
  } = useApp();
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState('New chat');
  const bottomRef = useRef<HTMLDivElement>(null);
  const composerRef = useRef<HTMLTextAreaElement>(null);
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
        setMessages(res.messages.map((m) => ({ role: m.role as Message['role'], content: m.content })));
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
      try {
        const res = await api.chat({
          message: text,
          session_id: sessionId ?? undefined,
        });
        if (res.session_id) {
          setSessionId(res.session_id);
          if (activeThread !== res.session_id) {
            loadedRef.current = res.session_id; // this session's turns are already on screen
            setActiveThread(res.session_id);
          }
        }
        if (res.trace_id) setLastTraceId(res.trace_id);
        setMessages([...next, { role: 'assistant', content: res.answer }]);
        setStatus(`Real backend · ${res.retrieval_mode}`);
      } catch (err) {
        setMessages([...next, { role: 'assistant', content: `Error: ${(err as Error).message}` }]);
        setStatus('Backend error');
      }
    } else {
      await new Promise(r => setTimeout(r, 600));
      const reply =
        "I've pulled context from your durable memory and session working set. The main signal is still active — let me know if you'd like a deeper trace or a retrieval breakdown.";
      setMessages([...next, { role: 'assistant', content: reply }]);
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
            <div className="chat-bubble">
              {m.role === 'assistant' ? <MarkdownText content={m.content} /> : m.content}
            </div>
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
              <span style={{ animation: 'pulse 1s infinite' }}>Thinking…</span>
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
