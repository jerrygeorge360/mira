import { useState, useRef, useEffect } from 'react';
import { ArrowUp, ChevronDown, FileUp, GitBranch, Network, Paperclip, Plus, Route, Workflow } from 'lucide-react';
import { useApp } from '../context/AppContext';
import BrandMark from './BrandMark';
import LoadingState from './LoadingState';
import AssistantMessage, { type MessageMeta } from './AssistantMessage';
import type { TraceStep } from './ThinkingTrace';
import ComposerMenu, { type MenuRow } from './ComposerMenu';
import { api } from '../api/client';
import { Bubble, BubbleContent } from '@/components/ui/bubble';
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty';
import { InputGroup, InputGroupAddon, InputGroupButton, InputGroupTextarea } from '@/components/ui/input-group';
import { Message, MessageAvatar, MessageContent } from '@/components/ui/message';
import {
  MessageScroller,
  MessageScrollerButton,
  MessageScrollerContent,
  MessageScrollerItem,
  MessageScrollerProvider,
  MessageScrollerViewport,
} from '@/components/ui/message-scroller';
import { Switch } from '@/components/ui/switch';

type Message = {
  role: 'user' | 'assistant';
  content: string;
  /** answered in this session (not loaded from history), so it streams in */
  live?: boolean;
  meta?: MessageMeta;
  /** the agent's stage events for this turn, shown as a thinking trace */
  steps?: TraceStep[];
  startedAt?: number;
  /** send → first answer token */
  thoughtMs?: number;
};

type RoutingStrategy = 'fast' | 'accurate';

const ROUTING: Record<RoutingStrategy, { label: string; desc: string }> = {
  fast: { label: 'Fast', desc: 'Rule-based routing' },
  accurate: { label: 'Accurate', desc: 'LLM routes each question · slower' },
};
const ROUTING_KEY = 'mira.routingStrategy';

function readRouting(): RoutingStrategy {
  try {
    return localStorage.getItem(ROUTING_KEY) === 'accurate' ? 'accurate' : 'fast';
  } catch {
    return 'fast';
  }
}

type Command = MenuRow & { run: () => void };

export default function ChatView() {
  const {
    activeThread,
    setActiveThread,
    useRealAgent,
    setUseRealAgent,
    sessionId,
    setSessionId,
    lastTraceId,
    setLastTraceId,
    setView,
  } = useApp();
  const [routing, setRouting] = useState<RoutingStrategy>(readRouting);
  const [routingOpen, setRoutingOpen] = useState(false);
  const [routingActive, setRoutingActive] = useState<number | null>(null);
  const [menuActive, setMenuActive] = useState<number | null>(0);
  const [menuDismissed, setMenuDismissed] = useState(false);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState('New chat');
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
    return () => {
      streamAbortRef.current?.abort();
    };
  }, []);

  async function send(retry?: { text: string; base: Message[] }) {
    const text = retry ? retry.text : input.trim();
    if (!text || loading) return;
    if (!retry) {
      setInput('');
    }
    const next: Message[] = [...(retry ? retry.base : messages), { role: 'user', content: text }];
    setMessages(next);
    setLoading(true);
    setStatus('Thinking');

    if (useRealAgent) {
      const body = {
        message: text,
        session_id: sessionId ?? undefined,
        routing_strategy: routing,
      };
      const startedAt = Date.now();
      const steps: TraceStep[] = [];
      let thoughtMs: number | undefined;
      const turn = (content: string, extra?: Partial<Message>): Message => ({
        role: 'assistant',
        content,
        steps: [...steps],
        startedAt,
        thoughtMs,
        ...extra,
      });
      try {
        let assistantText = '';
        let meta: MessageMeta | undefined;
        const show = () => setMessages([...next, turn(assistantText, { live: true, meta })]);
        const controller = new AbortController();
        streamAbortRef.current = controller;
        await api.chatStream(
          body,
          (event) => {
            if (event.type === 'stage') {
              steps.push({ stage: event.stage, message: event.message, at: Date.now() });
              setStatus(event.message);
              show();
              return;
            }
            if (event.type === 'answer') {
              if (thoughtMs === undefined) thoughtMs = Date.now() - startedAt;
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
          setMessages([...next, turn('No answer was returned.')]);
        }
      } catch (err) {
        streamAbortRef.current = null;
        const message = (err as Error).message;
        if (!message.includes('API 404')) {
          setMessages([...next, turn(`Error: ${message}`)]);
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

  function chooseRouting(next: RoutingStrategy) {
    setRouting(next);
    setRoutingOpen(false);
    try {
      localStorage.setItem(ROUTING_KEY, next);
    } catch {
      /* private mode: the choice just won't persist */
    }
  }

  // "/" commands run real app actions; the menu opens only while the draft is a lone /word
  const commands: Command[] = [
    {
      key: 'new',
      label: '/new',
      desc: 'Start a new chat',
      icon: <Plus size={14} />,
      run: () => {
        setActiveThread('new');
        setSessionId(null);
      },
    },
    ...(lastTraceId
      ? [{ key: 'trace', label: '/trace', desc: 'Open the last retrieval trace', icon: <Route size={14} />, run: () => setView('Retrieval Trace') }]
      : []),
    { key: 'pipeline', label: '/pipeline', desc: 'What memory did with recent turns', icon: <Workflow size={14} />, run: () => setView('Memory Pipeline') },
    { key: 'graph', label: '/graph', desc: 'Browse the memory graph', icon: <Network size={14} />, run: () => setView('Memory Graph') },
    { key: 'docs', label: '/docs', desc: 'Add or manage documents', icon: <FileUp size={14} />, run: () => setView('Knowledge Bases') },
    ...(useRealAgent
      ? (Object.keys(ROUTING) as RoutingStrategy[]).map((key) => ({
          key,
          label: `/${key}`,
          desc: `Switch to ${ROUTING[key].label.toLowerCase()} memory routing`,
          icon: <GitBranch size={14} />,
          run: () => chooseRouting(key),
        }))
      : []),
  ];
  const slash = /^\/([\w-]*)$/.exec(input);
  const commandQuery = slash ? slash[1].toLowerCase() : null;
  const commandRows = commandQuery === null ? [] : commands.filter((c) => c.key.startsWith(commandQuery));
  const commandMenuOpen = commandQuery !== null && !menuDismissed;

  useEffect(() => {
    setMenuActive(0);
  }, [commandQuery]);

  function runCommand(row: MenuRow) {
    const command = commands.find((c) => c.key === row.key);
    setInput('');
    setMenuDismissed(false);
    command?.run();
    composerRef.current?.focus();
  }

  const routingRows: MenuRow[] = (Object.keys(ROUTING) as RoutingStrategy[]).map((key) => ({
    key,
    label: ROUTING[key].label,
    desc: ROUTING[key].desc,
    selected: routing === key,
  }));

  // close the routing picker on any press outside it
  useEffect(() => {
    if (!routingOpen) return;
    const close = (event: PointerEvent) => {
      if (!(event.target as Element).closest('.composer-routing')) setRoutingOpen(false);
    };
    document.addEventListener('pointerdown', close);
    return () => document.removeEventListener('pointerdown', close);
  }, [routingOpen]);

  function openTrace(traceId: string) {
    setLastTraceId(traceId);
    setView('Retrieval Trace');
  }

  const waiting = loading && messages[messages.length - 1]?.role !== 'assistant';

  return (
    <div className="chat-view">
      {messages.length === 0 && !loading ? (
        <Empty className="chat-empty">
          <EmptyHeader className="items-start">
            <EmptyMedia>
              <BrandMark size={28} />
            </EmptyMedia>
            <EmptyTitle className="text-2xl tracking-tight">What should MIRA remember?</EmptyTitle>
            <EmptyDescription className="text-sm">
              {useRealAgent
                ? 'Ask naturally. MIRA keeps the conversation, memory, and retrieval trace connected.'
                : 'Demo mode is on. Switch to the live agent when you want real memory writes.'}
            </EmptyDescription>
          </EmptyHeader>
        </Empty>
      ) : (
        // the scroller follows the stream only while the reader is at the live edge
        <MessageScrollerProvider autoScroll>
          <MessageScroller className="chat-scroller">
            <MessageScrollerViewport>
              <MessageScrollerContent className="chat-transcript" aria-busy={loading}>
                {messages.map((m, i) => (
                  <MessageScrollerItem key={i} messageId={`turn-${i}`} scrollAnchor={m.role === 'user'}>
                    {m.role === 'user' ? (
                      <Message align="end">
                        <MessageContent>
                          <Bubble align="end" variant="muted">
                            <BubbleContent className="whitespace-pre-wrap">{m.content}</BubbleContent>
                          </Bubble>
                        </MessageContent>
                      </Message>
                    ) : (
                      <Message>
                        <MessageAvatar className="self-start bg-transparent pt-1">
                          <BrandMark size={12} />
                        </MessageAvatar>
                        <MessageContent>
                          <Bubble variant="ghost">
                            <BubbleContent>
                              <AssistantMessage
                                content={m.content}
                                animate={Boolean(m.live)}
                                streaming={loading && i === messages.length - 1}
                                meta={m.meta}
                                steps={m.steps}
                                startedAt={m.startedAt}
                                thoughtMs={m.thoughtMs}
                                onRetry={i === messages.length - 1 && !loading ? () => retry(i) : undefined}
                                onOpenTrace={openTrace}
                              />
                            </BubbleContent>
                          </Bubble>
                        </MessageContent>
                      </Message>
                    )}
                  </MessageScrollerItem>
                ))}

                {waiting && (
                  <MessageScrollerItem messageId="pending">
                    <Message>
                      <MessageAvatar className="self-start bg-transparent pt-1">
                        <BrandMark size={12} />
                      </MessageAvatar>
                      <MessageContent>
                        <Bubble variant="ghost">
                          <BubbleContent>
                            <LoadingState label={status} />
                          </BubbleContent>
                        </Bubble>
                      </MessageContent>
                    </Message>
                  </MessageScrollerItem>
                )}
              </MessageScrollerContent>
            </MessageScrollerViewport>
            <MessageScrollerButton />
          </MessageScroller>
        </MessageScrollerProvider>
      )}

      <div className="chat-dock">
        <div className="chat-dock-strip">
          <label className="chat-dock-toggle">
            <Switch size="sm" checked={useRealAgent} onCheckedChange={setUseRealAgent} />
            {useRealAgent ? 'Live memory' : 'Demo mode'}
          </label>
          <span className="chat-dock-status" role="status">
            {status}
          </span>
        </div>

        <InputGroup className="chat-input">
          {commandMenuOpen && (
            <ComposerMenu
              id="chat-commands"
              label="Commands"
              className="composer-menu-commands"
              rows={commandRows}
              active={commandRows.length ? menuActive : null}
              onActiveChange={setMenuActive}
              onPick={runCommand}
              empty={`No command matches /${commandQuery}`}
              footer="↑↓ to move · Enter to run · Esc to close"
            />
          )}
          <InputGroupTextarea
            ref={composerRef}
            className="chat-input-text"
            placeholder="Message MIRA"
            rows={1}
            value={input}
            role="combobox"
            aria-expanded={commandMenuOpen}
            aria-controls={commandMenuOpen ? 'chat-commands' : undefined}
            aria-activedescendant={
              commandMenuOpen && menuActive !== null && commandRows[menuActive]
                ? `chat-commands-${commandRows[menuActive].key}`
                : undefined
            }
            onChange={(e) => {
              setInput(e.target.value);
              setMenuDismissed(false);
            }}
            onKeyDown={(e) => {
              if (commandMenuOpen && commandRows.length) {
                if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
                  e.preventDefault();
                  const n = commandRows.length;
                  setMenuActive((i) => {
                    const current = i ?? 0;
                    return e.key === 'ArrowDown' ? (current + 1) % n : (current - 1 + n) % n;
                  });
                  return;
                }
                if ((e.key === 'Enter' && !e.shiftKey) || e.key === 'Tab') {
                  e.preventDefault();
                  runCommand(commandRows[menuActive ?? 0] ?? commandRows[0]);
                  return;
                }
              }
              if (e.key === 'Escape' && (commandMenuOpen || routingOpen)) {
                e.preventDefault();
                setMenuDismissed(true);
                setRoutingOpen(false);
                return;
              }
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                send();
              }
            }}
          />
          <InputGroupAddon align="block-end">
            <InputGroupButton
              size="icon-sm"
              onClick={() => setView('Knowledge Bases')}
              title="Add a document"
              aria-label="Add a document"
            >
              <Paperclip />
            </InputGroupButton>
            {useRealAgent && (
              <div className="composer-routing ml-auto">
                {routingOpen && (
                  <ComposerMenu
                    id="chat-routing"
                    label="Memory routing"
                    className="composer-menu-routing"
                    clearOnLeave
                    rows={routingRows}
                    active={routingActive}
                    onActiveChange={setRoutingActive}
                    onPick={(row) => {
                      chooseRouting(row.key as RoutingStrategy);
                      composerRef.current?.focus();
                    }}
                  />
                )}
                <InputGroupButton
                  size="sm"
                  aria-haspopup="listbox"
                  aria-expanded={routingOpen}
                  aria-label={`Memory routing: ${ROUTING[routing].label}`}
                  title="How MIRA decides which memory to search"
                  onClick={() => {
                    setRoutingOpen((o) => !o);
                    setRoutingActive(null);
                  }}
                >
                  {ROUTING[routing].label}
                  <ChevronDown data-icon="inline-end" />
                </InputGroupButton>
              </div>
            )}
            <InputGroupButton
              variant="default"
              size="icon-sm"
              className={useRealAgent ? undefined : 'ml-auto'}
              onClick={() => send()}
              disabled={loading || !input.trim()}
              aria-label="Send message"
            >
              <ArrowUp />
            </InputGroupButton>
          </InputGroupAddon>
        </InputGroup>
        <p className="chat-dock-note">MIRA can make mistakes. Verify important details.</p>
      </div>
    </div>
  );
}
