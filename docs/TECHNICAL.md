# AI Coworker — Technical Documentation

**Version:** 0.1.0 (chat host)  
**Audience:** engineers extending, operating, or reviewing this system  
**Companions:** [SIMPLE.md](./SIMPLE.md) (operators), [AGENTS.md](../AGENTS.md) (coding agents)

This document describes the **running** system: a self-hosted chat host (FastAPI + LangGraph + OpenAI-compatible inference). It is not a multi-agent coding or deploy platform.

Older drafts described a supervisor plus code / review / deploy specialists and a LangGraph `interrupt()` deploy gate. Those modules are **not** in `src/ai_coworker/`. The frontend still has leftover deploy-approval UI.

---

## 1. Design goals

| Goal | Implication in this repo |
|------|--------------------------|
| No cloud LLM dependency | All inference goes through `LLM_BASE_URL` (OpenAI-compatible). See §6. |
| Explicit orchestration | LangGraph `StateGraph` with typed state. Today that graph has **one** node. See §3. |
| Tools as a separate plane | MCP config exists; tools are **not** bound into the chat loop. See §7. |
| Durable conversations | Optional Postgres checkpointer keyed by `thread_id`. See §8. |
| Editable prompts | Catalog in `prompts/manifest.yaml` + JSON at `PROMPTS_PERSIST_PATH`. See §9. |

---

## 2. High-level architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  Clients (browser / curl)                                       │
└────────────────────────────┬────────────────────────────────────┘
                             │ HTTP JSON / SSE / WebSocket
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  FastAPI  (`src/ai_coworker/api/main.py`)                        │
│  - /health, /chat, /chat/stream, /ws/chat, /prompts              │
│  - lifespan: prompt store → checkpointer → compile graph         │
└────────────────────────────┬────────────────────────────────────┘
                             │ ainvoke / astream_events
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  LangGraph  (`graph.py`)                                         │
│                                                                 │
│   START → chat → END                                            │
└───────────────┬─────────────────────────────────────────────────┘
                │
                ▼
┌───────────────────────────┐   ┌─────────────────────────────────┐
│  Self-hosted LLM          │   │  MCP (scaffold only)            │
│  ChatOpenAI(base_url=…)   │   │  load_tools_for_role("chat")    │
│  Ollama / vLLM / TGI …    │   │  allowlist empty; tools unused  │
└───────────────────────────┘   └─────────────────────────────────┘
                │
                ▼
┌───────────────────────────┐
│  Checkpointer             │
│  MemorySaver | Postgres   │
└───────────────────────────┘
```

### 2.1 Component responsibilities

| Package / module | Responsibility |
|------------------|----------------|
| `api/main.py` | Transport: validation, thread IDs, SSE, WebSocket cancel |
| `api/prompts.py` | Prompt catalog CRUD (optional `PROMPTS_ADMIN_TOKEN`) |
| `graph.py` | Topology (`chat` only) + checkpointer binding |
| `state.py` | Shared typed state (`CoworkerState`) |
| `agents/chat.py` | System prompt + 8-turn window + one `ainvoke` |
| `llm.py` | Single factory for OpenAI-compatible self-hosted clients |
| `attachments.py` | PDF text extract, image_url blocks, size/mime limits |
| `mcp/client.py` | HTTP MCP server config + role allowlists |
| `config.py` | Environment-backed settings (`pydantic-settings`) |
| `prompts/` | Manifest defaults + persisted JSON store |

LangGraph is the **orchestration runtime** (streaming, persistence). LangChain supplies the chat model abstraction. There is **no** ReAct / tool node yet [[1]](#references) [[4]](#references).

---

## 3. Control flow

`build_graph()` compiles:

```
START → chat → END
```

`run_chat`:

1. Takes human/AI messages (skips leftover `[routed →` strings).
2. Keeps the last **8** turns.
3. Prepends `system_message("chat.system")` from the prompt store.
4. Calls `vision_llm` if `LLM_VISION_MODEL` is set and differs from `LLM_MODEL`; otherwise `llm`.
5. Discards the `tools` argument (`_ = tools`).
6. Returns a new `AIMessage`, `last_agent="chat"`, and a 500-char `thread_summary`.

A single user turn is one LLM round-trip. Extending to a coding assistant means a **bounded tool loop** (recursion limit), not extra specialist files by default.

---

## 4. State model

`state.py` — `TypedDict` consumed by `StateGraph(CoworkerState)`.

| Field | Type | Semantics |
|-------|------|-----------|
| `messages` | `Annotated[list, add_messages]` | Transcript; reducer **appends** [[8]](#references) |
| `thread_summary` | `str` | Truncated last reply (chat) |
| `last_agent` | `str` | Last node (`"chat"`) |
| `error` | `str \| None` | Reserved |

Follow-up turns send only the new `HumanMessage` with the same `thread_id`. New threads seed `initial_state()`.

---

## 5. HTTP / WebSocket API

| Method | Path | Behavior |
|--------|------|----------|
| `GET` | `/health` | Liveness |
| `POST` | `/chat` | Sync `ainvoke`; `{thread_id, last_agent, reply}` |
| `POST` | `/chat/stream` | SSE: `thread`, `token`, `node_end`, `done` |
| `WS` | `/ws/chat` | Primary UI transport: `chat` / `ping` / `cancel` |
| `GET/PUT/POST/DELETE` | `/prompts…` | Prompt catalog; mutating routes gated if token set |

There is **no** `/threads/{id}/approve-deploy` in the API. CORS allows localhost `3000`, `3080`, `5173`. Chat endpoints have **no auth**.

Streaming uses `astream_events` v2. Token events require the inference server to stream.

---

## 6. Self-hosted inference

`llm.py` builds `ChatOpenAI` with:

- `base_url=LLM_BASE_URL` (trailing slash stripped)
- `model=LLM_MODEL` (Compose default `openbmb/minicpm-v4.6`)
- `api_key=LLM_API_KEY` (often dummy for local servers)
- `extra_body.options.num_ctx` from `LLM_NUM_CTX` (Ollama context; default 16384)
- `streaming=True`

Compatibility target: OpenAI `/v1/chat/completions` [[11]](#references) [[12]](#references).

| Runtime | Typical base URL |
|---------|------------------|
| Ollama | `http://host:11434/v1` |
| vLLM | `http://host:8000/v1` |

Set `LLM_TIMEOUT_SECONDS` high enough for cold starts (Compose API default 240s). Structured output / tool calling must be validated on **your** weights before you add an agent loop.

---

## 7. MCP tool plane

[MCP](https://modelcontextprotocol.io) is the intended tool boundary [[2]](#references). Config comes from env (`MCP_GITHUB_URL`, `MCP_CI_URL`) via `langchain-mcp-adapters` [[15]](#references).

| Role | Allowed MCP server keys |
|------|-------------------------|
| `chat` | ∅ |

`load_tools_for_role("chat")` therefore returns `[]`. Even if you expand the allowlist, **chat still ignores tools** until `run_chat` binds them.

When wiring tools: keep allowlists; use separate credentials for read vs write; do not give review-like roles CI deploy tools [[18]](#references).

---

## 8. Persistence and threads

`open_checkpointer()`:

- No `DATABASE_URL` → `MemorySaver` (lost on restart)
- With `DATABASE_URL` → `AsyncPostgresSaver`, `setup()` on enter [[10]](#references)

FastAPI lifespan keeps the Postgres context open for the process.

| API behavior | Effect |
|--------------|--------|
| Omit `thread_id` | New UUID; seed `initial_state()` + first message |
| Pass `thread_id` | Load checkpoint; append message |

---

## 9. Prompts and attachments

- Defaults: inline `text` in `src/ai_coworker/prompts/manifest.yaml`.
- Runtime catalog: JSON at `PROMPTS_PERSIST_PATH` (Compose: `/data/prompts.json`).
- Load via `system_message("chat.system")`. Do not hardcode long system prompts in agents.
- Mutating `/prompts` requires `PROMPTS_ADMIN_TOKEN` when that env is set.

Attachments (`attachments.py`): PDF (text extract, truncated to `CHAT_MAX_PDF_CHARS`), PNG/JPEG as `image_url`. Limits: count, bytes, mime. Treat PDF text as **untrusted**.

---

## 10. Security

```
[User] --HTTP--> [API] --prompts--> [LLM in VPC]
                   |--state---> [Postgres]
                   |--(future tools)--> [MCP] --creds--> [GitHub / CI / fs]
```

- Chat is unauthenticated. Do not attach shell/write tools without HITL and allowlisted roots.
- MCP tokens are high privilege; keep them in secrets, not images.
- Runtime gates (LangGraph `interrupt()`) beat “ask the model to wait” for destructive actions [[7]](#references).
- Pin/scan container images in production.

---

## 11. Observability and deploy

LangSmith env vars default **off**. Prefer structured logs (`thread_id`, node name) and OpenTelemetry around FastAPI + HTTPX [[19]](#references).

| Artifact | Purpose |
|----------|---------|
| `Dockerfile` | API via `uv sync` |
| `compose.yml` | Ollama + API + Postgres + web |
| `deploy/k8s/ai-coworker.yaml` | Example API + vLLM |

Compose API defaults to `LLM_BASE_URL=http://ollama:11434/v1`.

---

## 12. Extension roadmap

Ordered by leverage:

1. Bound tool loop (prebuilt ReAct or tool node + recursion limit) [[16]](#references).
2. Filesystem MCP on explicit roots (read/search first).
3. HITL before write/shell (`interrupt()` + checkpointer).
4. Inject `AGENTS.md` / skills into the host prompt; do not dump the machine into context.
5. Eval suite on the local model (tool calls, injection).
6. Authn on the API before multi-tenant or public exposure.

---

## 13. Module map

```
src/ai_coworker/
├── api/main.py          # HTTP + SSE + WebSocket
├── api/prompts.py       # prompt catalog API
├── agents/chat.py       # single node
├── mcp/client.py        # HTTP MCP + allowlists
├── graph.py             # StateGraph + checkpointer CM
├── state.py             # CoworkerState
├── llm.py               # self-hosted ChatOpenAI
├── attachments.py       # PDF / images
├── config.py            # Settings
└── prompts/             # manifest + store
```

---

## References

1. LangGraph overview — https://docs.langchain.com/oss/python/langgraph/overview  
2. Model Context Protocol — https://modelcontextprotocol.io/docs  
3. vLLM OpenAI-compatible server — https://docs.vllm.ai/en/latest/serving/openai_compatible_server.html  
4. LangChain overview — https://docs.langchain.com/oss/python/langchain/overview  
7. LangGraph interrupts — https://docs.langchain.com/oss/python/langgraph/interrupts  
8. Graph API / `add_messages` — https://docs.langchain.com/oss/python/langgraph/graph-api  
10. Checkpointers — https://docs.langchain.com/oss/python/langgraph/checkpointers  
11. Ollama OpenAI compatibility — https://github.com/ollama/ollama/blob/main/docs/openai.md  
12. vLLM docs — https://docs.vllm.ai/  
15. langchain-mcp-adapters — https://github.com/langchain-ai/langchain-mcp-adapters  
16. LangChain agents — https://docs.langchain.com/oss/python/langchain/agents  
18. OWASP LLM Top 10 — https://owasp.org/www-project-top-10-for-large-language-model-applications/  
19. OpenTelemetry Python — https://opentelemetry.io/docs/languages/python/  
20. FastAPI lifespan — https://fastapi.tiangolo.com/advanced/events/  

AGENTS.md convention — https://agents.md/

---

## Document history

| Date | Change |
|------|--------|
| 2026-07-25 | Initial technical documentation for v0.1.0 (supervisor + specialists draft). |
| 2026-09-20 | Rewrite to match the shipped chat-only graph, API, prompts, and MCP scaffold. |
