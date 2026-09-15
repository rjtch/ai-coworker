import { useEffect, useMemo, useRef, useState, useEffectEvent } from "react";
import {
  ChatSocket,
  approveDeploy as approveDeployHttp,
  checkHealth,
  sendChat,
  streamChatSse,
} from "./api";
import PromptsPanel from "./PromptsPanel";
import type { ChatAttachment, ChatMessage } from "./types";
import { ACCEPTED_FILE_TYPES, fileToAttachment, uid } from "./types";

const SUGGESTIONS = [
  "Summarize the attached PDF",
  "What do you see in this screenshot?",
  "Extract the key points from this document",
  "Explain this diagram in plain language",
];

type Transport = "websocket" | "sse" | "http";
type View = "chat" | "prompts";

export default function App() {
  const [view, setView] = useState<View>("chat");
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: uid(),
      role: "system",
      content:
        "Chat with MiniCPM-V locally. Attach PDF, PNG, or JPEG — text and images are read by the same model.",
    },
  ]);
  const [input, setInput] = useState("");
  const [threadId, setThreadId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [online, setOnline] = useState<boolean | null>(null);
  const [activeNode, setActiveNode] = useState<string | null>(null);
  const [pendingDeploy, setPendingDeploy] = useState(false);
  const [interruptNote, setInterruptNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [transport, setTransport] = useState<Transport>("websocket");
  const [pendingAttachments, setPendingAttachments] = useState<ChatAttachment[]>([]);
  const bottomRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const socketRef = useRef<ChatSocket | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const assistantIdRef = useRef<string | null>(null);
  const doneResolver = useRef<(() => void) | null>(null);

  const onHealth = useEffectEvent(async () => {
    setOnline(await checkHealth());
  });

  useEffect(() => {
    void onHealth();
    const t = window.setInterval(() => void onHealth(), 15000);
    const socket = new ChatSocket();
    socketRef.current = socket;
    void socket.connect().catch(() => {
      /* fall back per-request */
    });
    return () => {
      window.clearInterval(t);
      socket.close();
      socketRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (view === "chat") {
      bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages, pendingDeploy, busy, view]);

  const statusLabel = useMemo(() => {
    if (online === null) return "Checking…";
    if (!online) return "API offline";
    if (busy && activeNode) return `Running · ${activeNode}`;
    if (busy) return "Working…";
    if (pendingDeploy) return "Awaiting deploy approval";
    return `Ready · ${transport}`;
  }, [online, busy, activeNode, pendingDeploy, transport]);

  function wireSocketHandlers(assistantId: string) {
    const socket = socketRef.current!;
    socket.setHandlers({
      onThread: (id) => setThreadId(id),
      onToken: (token) => {
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantId
              ? { ...m, content: m.content + token, streaming: true }
              : m,
          ),
        );
      },
      onNodeEnd: (node) => setActiveNode(node),
      onDone: ({ thread_id, interrupted, values, reply, interrupt_payload }) => {
        setThreadId(thread_id);
        const agent = (values.last_agent as string) || null;
        const intent = (values.intent as string) || null;
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantId
              ? {
                  ...m,
                  agent,
                  intent,
                  streaming: false,
                  content:
                    m.content ||
                    reply ||
                    (interrupted
                      ? "Deploy paused — approval required."
                      : "(no reply)"),
                }
              : m,
          ),
        );
        if (interrupted) {
          setPendingDeploy(true);
          const note =
            typeof interrupt_payload?.message === "string"
              ? interrupt_payload.message
              : "Approve to continue the deploy agent.";
          setInterruptNote(note);
        }
        setBusy(false);
        setActiveNode(null);
        doneResolver.current?.();
        doneResolver.current = null;
      },
      onError: (message) => {
        setError(message);
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantId
              ? { ...m, content: `Error: ${message}`, streaming: false }
              : m,
          ),
        );
        setBusy(false);
        setActiveNode(null);
        doneResolver.current?.();
        doneResolver.current = null;
      },
      onCancelled: () => {
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantId
              ? {
                  ...m,
                  content: m.content || "(cancelled)",
                  streaming: false,
                }
              : m,
          ),
        );
        setBusy(false);
        setActiveNode(null);
        doneResolver.current?.();
        doneResolver.current = null;
      },
    });
  }

  async function handleFiles(fileList: FileList | null) {
    if (!fileList?.length) return;
    setError(null);
    try {
      const next: ChatAttachment[] = [];
      for (const file of Array.from(fileList)) {
        next.push(await fileToAttachment(file));
      }
      setPendingAttachments((prev) => [...prev, ...next].slice(0, 5));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not read file");
    } finally {
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }

  function removeAttachment(index: number) {
    setPendingAttachments((prev) => prev.filter((_, i) => i !== index));
  }

  async function handleSend(text?: string) {
    const message = (text ?? input).trim();
    const attachments = pendingAttachments;
    if ((!message && attachments.length === 0) || busy) return;

    setError(null);
    setInput("");
    setPendingAttachments([]);
    setPendingDeploy(false);
    setInterruptNote(null);
    setBusy(true);
    setActiveNode("chat");

    const attachmentNote =
      attachments.length > 0
        ? `\n${attachments.map((a) => `[file: ${a.name}]`).join(" ")}`
        : "";
    const userMsg: ChatMessage = {
      id: uid(),
      role: "user",
      content: message + attachmentNote,
      attachments,
    };
    const assistantId = uid();
    assistantIdRef.current = assistantId;
    setMessages((prev) => [
      ...prev,
      userMsg,
      { id: assistantId, role: "assistant", content: "", streaming: true },
    ]);

    try {
      if (transport === "http") {
        const res = await sendChat(message, threadId, attachments);
        setThreadId(res.thread_id);
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantId
              ? {
                  ...m,
                  content: res.reply,
                  agent: res.last_agent,
                  streaming: false,
                }
              : m,
          ),
        );
        setBusy(false);
        setActiveNode(null);
        return;
      }

      if (transport === "sse") {
        const controller = new AbortController();
        abortRef.current = controller;
        await streamChatSse(
          message,
          threadId,
          {
            onThread: (id) => setThreadId(id),
            onToken: (token) => {
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === assistantId
                    ? { ...m, content: m.content + token, streaming: true }
                    : m,
                ),
              );
            },
            onNodeEnd: (node) => setActiveNode(node),
            onDone: ({ thread_id, interrupted, values, interrupt_payload }) => {
              setThreadId(thread_id);
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === assistantId
                    ? {
                        ...m,
                        agent: (values.last_agent as string) || null,
                        intent: (values.intent as string) || null,
                        streaming: false,
                        content:
                          m.content ||
                          (interrupted
                            ? "Deploy paused — approval required."
                            : "(no reply)"),
                      }
                    : m,
                ),
              );
              if (interrupted) {
                setPendingDeploy(true);
                setInterruptNote(
                  typeof interrupt_payload?.message === "string"
                    ? interrupt_payload.message
                    : "Approve to continue the deploy agent.",
                );
              }
            },
          },
          controller.signal,
          attachments,
        );
        setBusy(false);
        setActiveNode(null);
        return;
      }

      const socket = socketRef.current ?? new ChatSocket();
      socketRef.current = socket;
      wireSocketHandlers(assistantId);
      await new Promise<void>((resolve, reject) => {
        doneResolver.current = resolve;
        void socket.chat(message, threadId, attachments).catch(reject);
      });
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Request failed";
      if (transport === "websocket") {
        try {
          setTransport("sse");
          setError(`WebSocket failed (${msg}); using SSE`);
          const controller = new AbortController();
          abortRef.current = controller;
          await streamChatSse(
            message,
            threadId,
            {
              onThread: (id) => setThreadId(id),
              onToken: (token) => {
                setMessages((prev) =>
                  prev.map((m) =>
                    m.id === assistantId
                      ? { ...m, content: m.content + token, streaming: true }
                      : m,
                  ),
                );
              },
              onNodeEnd: (node) => setActiveNode(node),
              onDone: ({ thread_id, interrupted, values }) => {
                setThreadId(thread_id);
                setMessages((prev) =>
                  prev.map((m) =>
                    m.id === assistantId
                      ? {
                          ...m,
                          agent: (values.last_agent as string) || null,
                          intent: (values.intent as string) || null,
                          streaming: false,
                          content: m.content || "(no reply)",
                        }
                      : m,
                  ),
                );
                if (interrupted) {
                  setPendingDeploy(true);
                  setInterruptNote("Approve to continue the deploy agent.");
                }
              },
            },
            controller.signal,
            attachments,
          );
          setBusy(false);
          setActiveNode(null);
          return;
        } catch (sseErr) {
          const smsg =
            sseErr instanceof Error ? sseErr.message : "SSE also failed";
          setError(smsg);
        }
      } else {
        setError(msg);
      }
      setMessages((prev) =>
        prev.map((m) =>
          m.id === assistantId
            ? { ...m, content: `Error: ${msg}`, streaming: false }
            : m,
        ),
      );
      setBusy(false);
      setActiveNode(null);
    } finally {
      abortRef.current = null;
    }
  }

  async function handleApprove(approved: boolean) {
    if (!threadId || busy) return;
    setBusy(true);
    setError(null);
    const assistantId = uid();
    setMessages((prev) => [
      ...prev,
      {
        id: assistantId,
        role: "assistant",
        content: "",
        streaming: true,
        agent: "deploy",
      },
    ]);

    try {
      if (transport === "websocket" && socketRef.current) {
        wireSocketHandlers(assistantId);
        await new Promise<void>((resolve, reject) => {
          doneResolver.current = resolve;
          void socketRef.current!
            .approveDeploy(threadId, approved)
            .catch(reject);
        });
        setPendingDeploy(false);
        setInterruptNote(null);
        return;
      }
      const res = await approveDeployHttp(threadId, approved);
      setPendingDeploy(false);
      setInterruptNote(null);
      setMessages((prev) =>
        prev.map((m) =>
          m.id === assistantId
            ? {
                ...m,
                content: res.reply,
                agent: res.last_agent,
                streaming: false,
              }
            : m,
        ),
      );
      setBusy(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Approval failed");
      setBusy(false);
    }
  }

  function handleCancel() {
    socketRef.current?.cancel();
    abortRef.current?.abort();
    setBusy(false);
    setActiveNode(null);
  }

  function newThread() {
    handleCancel();
    setThreadId(null);
    setPendingDeploy(false);
    setInterruptNote(null);
    setError(null);
    setMessages([
      {
        id: uid(),
        role: "system",
        content: "New thread started.",
      },
    ]);
  }

  if (view === "prompts") {
    return (
      <div className="shell shell-wide">
        <div className="atmosphere" aria-hidden />
        <PromptsPanel onBack={() => setView("chat")} />
      </div>
    );
  }

  return (
    <div className="shell">
      <div className="atmosphere" aria-hidden />
      <header className="top">
        <div className="brand-block">
          <p className="brand">AI Coworker</p>
          <p className="tagline">Chat · Code · Review · Deploy</p>
        </div>
        <div className="top-actions">
          <span className={`pill ${online ? "ok" : "bad"}`}>{statusLabel}</span>
          <nav className="view-tabs" aria-label="Views">
            <button type="button" className="view-tab active" disabled>
              Chat
            </button>
            <button
              type="button"
              className="view-tab"
              onClick={() => setView("prompts")}
            >
              Prompts
            </button>
          </nav>
          <label className="toggle">
            Transport
            <select
              value={transport}
              disabled={busy}
              onChange={(e) => setTransport(e.target.value as Transport)}
            >
              <option value="websocket">WebSocket</option>
              <option value="sse">SSE</option>
              <option value="http">HTTP</option>
            </select>
          </label>
          {busy ? (
            <button type="button" className="danger" onClick={handleCancel}>
              Stop
            </button>
          ) : null}
          <button
            type="button"
            className="ghost"
            onClick={newThread}
            disabled={busy}
          >
            New thread
          </button>
        </div>
      </header>

      <main className="stage">
        <section className="transcript" aria-live="polite">
          {messages.map((m) => (
            <article key={m.id} className={`bubble ${m.role}`}>
              <div className="meta">
                <span>
                  {m.role === "user"
                    ? "You"
                    : m.role === "system"
                      ? "System"
                      : m.agent || "Coworker"}
                </span>
                {m.intent ? <span className="intent">{m.intent}</span> : null}
                {m.streaming ? <span className="intent live">live</span> : null}
              </div>
              <div className="body">
                {m.content || (m.streaming ? "…" : "")}
                {m.attachments?.length ? (
                  <ul className="attachment-list">
                    {m.attachments.map((a) => (
                      <li key={`${m.id}-${a.name}`}>{a.name}</li>
                    ))}
                  </ul>
                ) : null}
              </div>
            </article>
          ))}
          <div ref={bottomRef} />
        </section>

        {pendingDeploy ? (
          <div className="gate" role="alertdialog" aria-label="Deploy approval">
            <div>
              <p className="gate-title">Deploy approval required</p>
              <p className="gate-copy">{interruptNote}</p>
            </div>
            <div className="gate-actions">
              <button
                type="button"
                className="danger"
                disabled={busy}
                onClick={() => void handleApprove(false)}
              >
                Reject
              </button>
              <button
                type="button"
                className="primary"
                disabled={busy}
                onClick={() => void handleApprove(true)}
              >
                Approve deploy
              </button>
            </div>
          </div>
        ) : null}

        {error ? <p className="error">{error}</p> : null}

        {!busy && messages.length < 3 ? (
          <div className="suggestions">
            {SUGGESTIONS.map((s) => (
              <button key={s} type="button" onClick={() => void handleSend(s)}>
                {s}
              </button>
            ))}
          </div>
        ) : null}

        <form
          className="composer"
          onSubmit={(e) => {
            e.preventDefault();
            void handleSend();
          }}
        >
          {pendingAttachments.length > 0 ? (
            <ul className="attachment-chips" aria-label="Attachments">
              {pendingAttachments.map((a, index) => (
                <li key={`${a.name}-${index}`}>
                  <span>{a.name}</span>
                  <button
                    type="button"
                    className="ghost"
                    aria-label={`Remove ${a.name}`}
                    onClick={() => removeAttachment(index)}
                  >
                    ×
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
          <div className="composer-row">
            <input
              ref={fileInputRef}
              type="file"
              accept={ACCEPTED_FILE_TYPES}
              multiple
              hidden
              onChange={(e) => void handleFiles(e.target.files)}
            />
            <button
              type="button"
              className="ghost attach-btn"
              disabled={busy || online === false}
              onClick={() => fileInputRef.current?.click()}
              title="Attach PDF, PNG, or JPEG"
            >
              Attach
            </button>
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Ask anything, or attach a PDF/image…"
              rows={2}
              disabled={busy || online === false}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  void handleSend();
                }
              }}
            />
            <button
              type="submit"
              className="primary"
              disabled={
                busy ||
                (!input.trim() && pendingAttachments.length === 0) ||
                online === false
              }
            >
              Send
            </button>
          </div>
        </form>
        {threadId ? <p className="thread">thread {threadId}</p> : null}
      </main>
    </div>
  );
}
