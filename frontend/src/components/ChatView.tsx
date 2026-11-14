import { useState, useRef, useEffect } from 'react';
import { Paperclip, Send, Sparkles } from 'lucide-react';
import { useApp } from '../context/AppContext';
import BrandMark from './BrandMark';
import LoadingState from './LoadingState';
import AssistantMessage, { type MessageMeta } from './AssistantMessage';
import { api } from '../api/client';

type Message = {
  role: 'user' | 'assistant';
  content: string;
  /** answered in this session (not loaded from history), so it streams in */
  live?: boolean;
  meta?: MessageMeta;
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
  const listRef = useRef<HTMLDivElement>(null);
  // Follow new content only while the reader is at the bottom; scrolling up to read stops it.
  const pinnedRef = useRef(true);
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
        pinnedRef.current = true;
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
    const el = listRef.current;
    if (!el) return;
    const onScroll = () => {
      pinnedRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
    };
    // the streamed answer keeps growing after each delta, so follow DOM changes, not state
    const follow = new MutationObserver(() => {
      if (pinnedRef.current) el.scrollTop = el.scrollHeight;
    });
    el.addEventListener('scroll', onScroll, { passive: true });
    follow.observe(el, { childList: true, subtree: true, characterData: true });
    return () => {
      el.removeEventListener('scroll', onScroll);
      follow.disconnect();
    };
  }, []);

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

  async function send(retry?: { text: string; base: Message[] }) {
    const text = retry ? retry.text : input.trim();
    if (!text || loading) return;
    if (!retry) {
      setInput('');
      if (composerRef.current) composerRef.current.style.height = 'auto';
    }
    const next: Message[] = [...(retry ? retry.base : messages), { role: 'user', content: text }];
    pinnedRef.current = true;
    setMessages(next);
    setLoading(true);
    setStatus('Thinking');

    if (useRealAgent) {
      const body = {
        message: text,
        session_id: sessionId ?? undefined,
      };
      try {
        let assistantText = '';
        let meta: MessageMeta | undefined;
        const show = () => setMessages([...next, { role: 'assistant', content: assistantText, live: true, meta }]);
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
              show();
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
              meta = {
                usedMemoryItems: event.used_memory_items ?? [],
                usedSessionItems: event.used_session_items ?? [],
                traceId: event.trace_id,
                retrievalMode: event.retrieval_mode,
              };
              if (assistantText) show();
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
          setMessages([
            ...next,
            {
              role: 'assistant',
              content: res.answer,
              live: true,
              meta: {
                usedMemoryItems: res.used_memory_items ?? [],
                usedSessionItems: res.used_session_items ?? [],
                traceId: res.trace_id,
                retrievalMode: res.retrieval_mode,
              },
            },
          ]);
          setStatus(`Real backend · ${res.retrieval_mode}`);
        }
      }
    } else {
      await new Promise(r => setTimeout(r, 600));
      const reply =
        "I've pulled context from your durable memory and session working set. The main signal is still active — let me know if you'd like a deeper trace or a retrieval breakdown.";
      setMessages([...next, { role: 'assistant', content: reply, live: true }]);
      setStatus('Demo response · quick retrieval');
    }
    setLoading(false);
  }


  /** Re-ask the user turn that produced the answer at `index`. */
  function retry(index: number) {
    const userIndex = index - 1;
    const userTurn = messages[userIndex];
    if (!userTurn || userTurn.role !== 'user') return;
    send({ text: userTurn.content, base: messages.slice(0, userIndex) });
  }

  function openTrace(traceId: string) {
    setLastTraceId(traceId);
    setView('Retrieval Trace');
  }

  return (
    <div className="chat-view">
      {/* messages */}
      <div className="chat-messages" ref={listRef}>
        {messages.map((m, i) => (
          <div key={i} className={`chat-turn ${m.role}`}>
            {m.role === 'assistant' && <div className="bot-avatar"><BrandMark size={17} /></div>}
            <div className="chat-bubble">
              {m.role === 'assistant' ? (
                <AssistantMessage
                  content={m.content}
                  animate={Boolean(m.live)}
                  streaming={loading && i === messages.length - 1}
                  meta={m.meta}
                  onRetry={i === messages.length - 1 && !loading ? () => retry(i) : undefined}
                  onOpenTrace={openTrace}
                />
              ) : (
                m.content
              )}
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

        {loading && messages[messages.length - 1]?.role !== 'assistant' && (
          <div className="chat-turn">
            <div className="bot-avatar"><BrandMark size={17} /></div>
            <div className="chat-bubble">
              <LoadingState label={status} />
            </div>
          </div>
        )}
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
          <button
            className="composer-attach"
            type="button"
            onClick={() => setView('Knowledge Bases')}
            title="Add a document"
            aria-label="Add a document"
          >
            <Paperclip size={17} />
          </button>
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
          <button className="composer-send" onClick={() => send()} disabled={loading || !input.trim()} aria-label="Send message">
            <Send size={16} />
          </button>
        </div>
        <div className="chat-disclaimer">MIRA can make mistakes. Verify important details.</div>
      </div>
    </div>
  );
}
