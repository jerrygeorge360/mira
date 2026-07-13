import { useState, useRef, useEffect } from 'react';
import { Send, Plus } from 'lucide-react';
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
        if (active) setStatus('Could not load conversation');
      });
    return () => {
      active = false;
    };
  }, [activeThread]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  async function send() {
    const text = input.trim();
    if (!text) return;
    setInput('');
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
      {/* mode bar */}
      <div className="chat-mode-bar">
        <label className="agent-toggle">
          <div className="toggle-switch">
            <input
              type="checkbox"
              checked={useRealAgent}
              onChange={e => setUseRealAgent(e.target.checked)}
            />
            <span className="toggle-slider" />
          </div>
          Use real MIRA agent
        </label>
        <span className="badge badge-neutral">{useRealAgent ? 'Real backend' : 'Demo data'}</span>
        <small style={{ color: 'var(--faint)', fontSize: '0.78rem', marginLeft: 4 }}>{status}</small>
      </div>

      {/* messages */}
      <div className="chat-messages">
        {messages.map((m, i) => (
          <div key={i} className={`chat-turn ${m.role}`}>
            {m.role === 'assistant' && <div className="bot-avatar"><BrandMark size={17} /></div>}
            <div className="chat-bubble">{m.content}</div>
          </div>
        ))}

        {messages.length === 0 && !loading && (
          <div className="chat-empty">
            <div className="bot-avatar"><BrandMark size={17} /></div>
            <div>
              <div className="chat-empty-title">Start a conversation</div>
              <div className="chat-empty-sub">
                {useRealAgent
                  ? 'Ask MIRA anything — it builds durable memory as you go.'
                  : 'Demo mode. Flip “real backend” on to talk to the live agent.'}
              </div>
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
      <div className="chat-composer">
        <button className="composer-add" title="Attach">
          <Plus size={16} />
        </button>
        <input
          className="composer-input"
          placeholder="Reply to MIRA…"
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && !e.shiftKey && send()}
        />
        <button className="composer-send" onClick={send} disabled={loading || !input.trim()}>
          <Send size={16} />
        </button>
      </div>
      <div className="chat-disclaimer">MIRA can make mistakes. Verify important details.</div>
    </div>
  );
}
