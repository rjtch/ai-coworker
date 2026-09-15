export type ChatResponse = {
  thread_id: string;
  last_agent: string | null;
  reply: string;
};

export type ChatAttachment = {
  name: string;
  mime_type: string;
  data: string;
};

export type ChatPayload = {
  message: string;
  thread_id?: string | null;
  attachments?: ChatAttachment[];
};

export type StreamHandlers = {
  onReady?: () => void;
  onThread: (threadId: string) => void;
  onToken: (text: string) => void;
  onNodeEnd: (node: string) => void;
  onDone: (payload: {
    thread_id: string;
    interrupted: boolean;
    values: Record<string, unknown>;
    reply?: string;
    interrupt_payload?: Record<string, unknown> | null;
  }) => void;
  onError?: (message: string) => void;
  onCancelled?: () => void;
};

export type PromptRecord = {
  id: string;
  text: string;
  source: "catalog";
  role: string;
  description: string;
  variables: string[];
  updated_at: string | null;
};

export type PromptListResponse = {
  catalog_version: number;
  prompts: PromptRecord[];
};

const API_BASE = import.meta.env.VITE_API_BASE ?? "/api";
const PROMPTS_TOKEN_KEY = "ai-coworker.prompts-token";

export function getPromptsAdminToken(): string {
  return localStorage.getItem(PROMPTS_TOKEN_KEY) ?? "";
}

export function setPromptsAdminToken(token: string): void {
  if (token.trim()) localStorage.setItem(PROMPTS_TOKEN_KEY, token.trim());
  else localStorage.removeItem(PROMPTS_TOKEN_KEY);
}

function promptHeaders(extra?: HeadersInit): HeadersInit {
  const token = getPromptsAdminToken();
  return {
    "content-type": "application/json",
    ...(token ? { "X-Prompts-Token": token } : {}),
    ...extra,
  };
}

function encodePromptId(id: string): string {
  return id.split(".").map(encodeURIComponent).join(".");
}

export async function listPrompts(): Promise<PromptListResponse> {
  const res = await fetch(`${API_BASE}/prompts`);
  if (!res.ok) throw new Error((await res.text()) || `List failed (${res.status})`);
  return res.json() as Promise<PromptListResponse>;
}

export async function updatePrompt(id: string, text: string): Promise<PromptRecord> {
  const res = await fetch(`${API_BASE}/prompts/${encodePromptId(id)}`, {
    method: "PUT",
    headers: promptHeaders(),
    body: JSON.stringify({ text }),
  });
  if (!res.ok) throw new Error((await res.text()) || `Update failed (${res.status})`);
  return res.json() as Promise<PromptRecord>;
}

export async function resetPrompt(id: string): Promise<PromptRecord> {
  const res = await fetch(`${API_BASE}/prompts/${encodePromptId(id)}/reset`, {
    method: "POST",
    headers: promptHeaders(),
  });
  if (!res.ok) throw new Error((await res.text()) || `Reset failed (${res.status})`);
  return res.json() as Promise<PromptRecord>;
}

export async function deletePrompt(id: string): Promise<void> {
  const res = await fetch(`${API_BASE}/prompts/${encodePromptId(id)}`, {
    method: "DELETE",
    headers: promptHeaders(),
  });
  if (!res.ok) throw new Error((await res.text()) || `Delete failed (${res.status})`);
}

export async function reloadPrompts(): Promise<void> {
  const res = await fetch(`${API_BASE}/prompts/reload`, {
    method: "POST",
    headers: promptHeaders(),
  });
  if (!res.ok) throw new Error((await res.text()) || `Reload failed (${res.status})`);
}

function wsUrl(path: string): string {
  const base = API_BASE.startsWith("http")
    ? API_BASE
    : `${window.location.protocol}//${window.location.host}${API_BASE}`;
  const u = new URL(base);
  u.protocol = u.protocol === "https:" ? "wss:" : "ws:";
  u.pathname = `${u.pathname.replace(/\/$/, "")}${path}`;
  return u.toString();
}

export async function checkHealth(): Promise<boolean> {
  try {
    const res = await fetch(`${API_BASE}/health`);
    if (!res.ok) return false;
    const data = (await res.json()) as { status?: string };
    return data.status === "ok";
  } catch {
    return false;
  }
}

export async function sendChat(
  message: string,
  threadId: string | null,
  attachments: ChatAttachment[] = [],
): Promise<ChatResponse> {
  const res = await fetch(`${API_BASE}/chat`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ message, thread_id: threadId, attachments }),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `Chat failed (${res.status})`);
  }
  return res.json() as Promise<ChatResponse>;
}

export async function approveDeploy(
  threadId: string,
  approved: boolean,
  note?: string,
): Promise<ChatResponse> {
  const res = await fetch(`${API_BASE}/threads/${threadId}/approve-deploy`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ approved, note: note ?? null }),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `Approve failed (${res.status})`);
  }
  return res.json() as Promise<ChatResponse>;
}

/** Persistent WebSocket session for chat + cancel + deploy approval. */
export class ChatSocket {
  private ws: WebSocket | null = null;
  private handlers: StreamHandlers | null = null;
  private pending = false;
  private openPromise: Promise<void> | null = null;

  get connected(): boolean {
    return this.ws?.readyState === WebSocket.OPEN;
  }

  async connect(): Promise<void> {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) return;
    if (this.openPromise) return this.openPromise;

    this.openPromise = new Promise<void>((resolve, reject) => {
      const socket = new WebSocket(wsUrl("/ws/chat"));
      this.ws = socket;

      const timer = window.setTimeout(() => {
        reject(new Error("WebSocket connect timeout"));
        socket.close();
      }, 10000);

      socket.onopen = () => {
        /* wait for ready frame */
      };

      socket.onerror = () => {
        window.clearTimeout(timer);
        this.openPromise = null;
        reject(new Error("WebSocket connection failed"));
      };

      socket.onclose = () => {
        this.ws = null;
        this.openPromise = null;
        this.pending = false;
      };

      socket.onmessage = (ev) => {
        let data: Record<string, unknown>;
        try {
          data = JSON.parse(String(ev.data)) as Record<string, unknown>;
        } catch {
          return;
        }
        const type = data.type;
        if (type === "ready") {
          window.clearTimeout(timer);
          this.openPromise = null;
          this.handlers?.onReady?.();
          resolve();
          return;
        }
        this.dispatch(data);
      };
    });

    return this.openPromise;
  }

  private dispatch(data: Record<string, unknown>) {
    const h = this.handlers;
    if (!h) return;
    switch (data.type) {
      case "thread":
        h.onThread(String(data.thread_id));
        break;
      case "token":
        h.onToken(String(data.text ?? ""));
        break;
      case "node_end":
        h.onNodeEnd(String(data.node ?? ""));
        break;
      case "done":
        this.pending = false;
        h.onDone({
          thread_id: String(data.thread_id),
          interrupted: Boolean(data.interrupted),
          values: (data.values as Record<string, unknown>) ?? {},
          reply: data.reply != null ? String(data.reply) : undefined,
          interrupt_payload:
            (data.interrupt_payload as Record<string, unknown> | null) ?? null,
        });
        break;
      case "error":
        this.pending = false;
        h.onError?.(String(data.message ?? "Unknown error"));
        break;
      case "cancelled":
        this.pending = false;
        h.onCancelled?.();
        break;
      default:
        break;
    }
  }

  setHandlers(handlers: StreamHandlers) {
    this.handlers = handlers;
  }

  async chat(
    message: string,
    threadId: string | null,
    attachments: ChatAttachment[] = [],
  ): Promise<void> {
    await this.connect();
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      throw new Error("WebSocket not connected");
    }
    if (this.pending) throw new Error("Busy");
    this.pending = true;
    this.ws.send(
      JSON.stringify({
        type: "chat",
        message,
        thread_id: threadId,
        attachments,
      }),
    );
  }

  async approveDeploy(
    threadId: string,
    approved: boolean,
    note?: string,
  ): Promise<void> {
    await this.connect();
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      throw new Error("WebSocket not connected");
    }
    if (this.pending) throw new Error("Busy");
    this.pending = true;
    this.ws.send(
      JSON.stringify({
        type: "approve_deploy",
        thread_id: threadId,
        approved,
        note: note ?? null,
      }),
    );
  }

  cancel() {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type: "cancel" }));
    }
  }

  close() {
    this.cancel();
    this.ws?.close();
    this.ws = null;
    this.handlers = null;
  }
}

/** SSE fallback if WebSocket is unavailable. */
export async function streamChatSse(
  message: string,
  threadId: string | null,
  handlers: StreamHandlers,
  signal?: AbortSignal,
  attachments: ChatAttachment[] = [],
): Promise<void> {
  const res = await fetch(`${API_BASE}/chat/stream`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ message, thread_id: threadId, attachments }),
    signal,
  });
  if (!res.ok || !res.body) {
    const text = await res.text();
    throw new Error(text || `Stream failed (${res.status})`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const chunks = buffer.split("\n\n");
    buffer = chunks.pop() ?? "";

    for (const chunk of chunks) {
      const line = chunk.split("\n").find((l) => l.startsWith("data: "));
      if (!line) continue;
      let event: Record<string, unknown>;
      try {
        event = JSON.parse(line.slice(6)) as Record<string, unknown>;
      } catch {
        continue;
      }
      switch (event.type) {
        case "thread":
          handlers.onThread(String(event.thread_id));
          break;
        case "token":
          handlers.onToken(String(event.text ?? ""));
          break;
        case "node_end":
          handlers.onNodeEnd(String(event.node ?? ""));
          break;
        case "done":
          handlers.onDone({
            thread_id: String(event.thread_id),
            interrupted: Boolean(event.interrupted),
            values: (event.values as Record<string, unknown>) ?? {},
            interrupt_payload:
              (event.interrupt_payload as Record<string, unknown> | null) ?? null,
          });
          break;
        default:
          break;
      }
    }
  }
}
