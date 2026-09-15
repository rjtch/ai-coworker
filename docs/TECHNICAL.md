# AI Coworker — Technical Documentation

**Version:** 0.1.0  
**Audience:** engineers extending, operating, or reviewing this system  
**Companion quickstart:** [SIMPLE.md](./SIMPLE.md)

This document describes the architecture, control flow, persistence model, tool boundary, and deployment assumptions of **AI Coworker**: a self-hosted multi-agent system for chat, code, review, and deploy workflows.

---

## 1. Design goals

| Goal | Implication in this repo |
|------|--------------------------|
| No cloud LLM dependency | All inference goes through `LLM_BASE_URL` (OpenAI-compatible). See §6. |
| Explicit orchestration | LangGraph `StateGraph` with typed state, not an opaque agent loop. See §3–§4. |
| Human gate on risky actions | Deploy path uses LangGraph `interrupt()` + resume via `Command`. See §5. |
| Tools as a separate plane | MCP servers supply tools; agents never embed vendor SDKs for GitHub/CI. See §7. |
| Least privilege | Per-role MCP allowlists. Review cannot reach CI deploy tools. See §7.2. |
| Durable conversations | Optional Postgres checkpointer keyed by `thread_id`. See §5–§8. |

These choices follow the common 2025–2026 production pattern of **graph orchestration + standardized tools + self-hosted inference** [[1]](#references) [[2]](#references) [[3]](#references).

---

## 2. High-level architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  Clients (curl / UI / internal services)                        │
└────────────────────────────┬────────────────────────────────────┘
                             │ HTTP (JSON / SSE)
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  FastAPI  (`src/ai_coworker/api/main.py`)                        │
│  - /chat, /chat/stream, /threads/{id}/approve-deploy, /health    │
│  - lifespan: open checkpointer → compile graph                  │
└────────────────────────────┬────────────────────────────────────┘
                             │ ainvoke / astream_events / Command
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  LangGraph compiled graph  (`graph.py`)                          │
│                                                                 │
│   START → supervisor ─┬→ chat ──────────────→ END               │
│                       ├→ code ──────────────→ END               │
│                       ├→ review ────────────→ END               │
│                       └→ deploy_gate ─→ deploy → END            │
│                            │                                    │
│                            └─ interrupt() if approval required  │
└───────────────┬─────────────────────────────┬───────────────────┘
                │                             │
                ▼                             ▼
┌───────────────────────────┐   ┌─────────────────────────────────┐
│  Self-hosted LLM          │   │  MCP (optional)                 │
│  ChatOpenAI(base_url=…)   │   │  MultiServerMCPClient           │
│  Ollama / vLLM / TGI …    │   │  github, ci (HTTP transport)    │
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
| `api/main.py` | Transport: request validation, thread IDs, SSE, resume API |
| `graph.py` | Topology, HITL gate, checkpointer binding |
| `state.py` | Shared typed state schema |
| `agents/*` | Node logic (prompts + structured outputs + light tool loops) |
| `llm.py` | Single factory for OpenAI-compatible self-hosted clients |
| `mcp/client.py` | Server discovery config + role allowlists |
| `config.py` | Environment-backed settings (`pydantic-settings`) |

LangGraph is used as the **orchestration runtime** (durable execution, streaming, interrupts, persistence), while LangChain chat models/tools provide the **model and tool abstractions** [[1]](#references) [[4]](#references).

---

## 3. Multi-agent pattern: supervisor + specialists

This system uses the **supervisor (router) pattern**: one node classifies intent; specialist nodes do the work. Industry guides recommend starting with a small number of specialists (here: four) and splitting only when trust boundaries or audiences diverge [[5]](#references) [[6]](#references).

### 3.1 Routing

`agents/supervisor.py` uses structured output (`RouteDecision`) so routing is typed (`chat | code | review | deploy`) rather than free-text parsing. The latest human message is the primary routing signal.

Conditional edges in `graph.py` map `state["intent"]` to the specialist node. Invalid/missing intent falls back to `chat`.

### 3.2 Why not a single ReAct agent?

A single tool-using agent can work for demos, but production deploy/review systems need:

- **Separate tool permissions** (review ≠ deploy)
- **Deterministic gates** (approval interrupt) independent of model cooperativeness
- **Clear audit surface** (which node ran, with which state)

Graph edges encode those invariants; prompts alone do not [[1]](#references) [[7]](#references).

---

## 4. State model

Defined in `state.py` as a `TypedDict` consumed by `StateGraph(CoworkerState)`.

| Field | Type | Semantics |
|-------|------|-----------|
| `messages` | `Annotated[list, add_messages]` | Conversation transcript; reducer **appends** rather than overwrites [[8]](#references) |
| `intent` | `Intent \| None` | Latest routed specialty |
| `thread_summary` | `str` | Short summary (chat) |
| `code_diff` | `str` | Diff sketch or extracted ```diff``` for review |
| `review_verdict` | `ReviewVerdict` | `pass \| fail \| needs_changes \| pending` |
| `review_notes` | `str` | Structured review findings |
| `deploy_approved` | `bool` | Set by HITL gate or config bypass |
| `deploy_status` | `str` | e.g. `awaiting_approval`, `planned`, `executed` |
| `last_agent` | `str` | Last node that produced a user-visible update |
| `error` | `str \| None` | Reserved for failure plumbing |

### 4.1 Message reducer

`add_messages` is LangGraph’s standard channel for chat history: each node returns only new messages; the runtime merges them into the checkpointed list [[8]](#references). The API therefore sends **only the new `HumanMessage`** on follow-up turns (same `thread_id`), not a full reset of state—except when creating a new thread, where `initial_state()` seeds defaults.

### 4.2 Cross-node data flow (today)

```
code → writes code_diff
review → reads code_diff, writes review_verdict / review_notes
deploy → reads review_notes, requires deploy_approved
```

There is **no automatic** `code → review → deploy` pipeline yet; each user turn is routed independently. Extending to a multi-hop pipeline would add edges (or a subgraph) after `code` / `review` rather than ending at `END`. That is an intentional MVP boundary.

---

## 5. Human-in-the-loop (deploy gate)

### 5.1 Mechanism

When `REQUIRE_DEPLOY_APPROVAL=true` (default), `deploy_gate_node` calls:

```python
decision = interrupt({
    "type": "deploy_approval",
    "message": "...",
    "review_verdict": ...,
    "review_notes": ...,
})
```

LangGraph persists state via the checkpointer and pauses until the client resumes with `Command(resume=...)` [[7]](#references) [[9]](#references).

Resume path (API):

```http
POST /threads/{thread_id}/approve-deploy
{"approved": true, "note": "optional"}
```

Implementation:

```python
await graph.ainvoke(Command(resume={"approved": body.approved, "note": body.note}), config)
```

### 5.2 Operational requirements

Per LangGraph docs, interrupts require [[7]](#references) [[10]](#references):

1. A **checkpointer** (MemorySaver is enough for single-process demo; use Postgres in production).
2. A stable **`thread_id`** in `config["configurable"]`.
3. A **JSON-serializable** interrupt payload.

**Important:** on resume, LangGraph re-enters the interrupted node from the start; idempotent gate logic must tolerate re-execution [[9]](#references). Our gate short-circuits if `deploy_approved` is already true.

### 5.3 Why interrupt instead of “ask the model to wait”?

Model-mediated approval is bypassable (jailbreaks, confused deputies). A runtime interrupt is an **enforcement point** outside the LLM’s control [[7]](#references).

---

## 6. Self-hosted inference

### 6.1 Client contract

`llm.py` builds a single `ChatOpenAI` instance with:

- `base_url=LLM_BASE_URL` (trailing slash stripped)
- `model=LLM_MODEL`
- `api_key=LLM_API_KEY` (often a dummy string for local servers)

There is **no** Anthropic/OpenAI cloud provider path. Compatibility target is the OpenAI Chat Completions API shape (`/v1/chat/completions`), which Ollama, vLLM, TGI, llama.cpp server, and LocalAI expose [[11]](#references) [[12]](#references) [[13]](#references).

| Runtime | Typical base URL | Notes |
|---------|------------------|-------|
| Ollama | `http://host:11434/v1` | Strong local DX; OpenAI-compatible endpoint [[11]](#references) |
| vLLM | `http://host:8000/v1` | Production GPU serving; OpenAI-compatible server entrypoint [[12]](#references) |
| TGI | OpenAI-compatible routes when enabled | HF text-generation-inference [[13]](#references) |

### 6.2 Model selection guidance

- Prefer **instruction / coder** checkpoints for code+review (e.g. Qwen2.5-Coder family as defaults in Compose/K8s).
- Structured outputs (`with_structured_output`) and tool calling quality vary by model; validate routing and review JSON on your target weights before production.
- Set `LLM_TIMEOUT_SECONDS` high enough for cold starts and long generations (Compose default 180s for API container).

### 6.3 Cluster topology

Recommended split:

| Workload | Scaling axis |
|----------|--------------|
| `ai-coworker` API | CPU / horizontal replicas (stateless w.r.t. LLM; state in Postgres) |
| vLLM / Ollama | GPU / memory; usually fewer replicas, sticky model load |
| Postgres | StatefulSet / managed DB for checkpoints |

Example manifests live under `deploy/k8s/ai-coworker.yaml`.

---

## 7. MCP tool plane

### 7.1 Role of MCP

[Model Context Protocol (MCP)](https://modelcontextprotocol.io) standardizes how hosts discover and invoke tools/resources over a documented transport [[2]](#references) [[14]](#references). This project uses **Streamable HTTP** remote servers configured via env (`MCP_GITHUB_URL`, `MCP_CI_URL`) and loads tools through `langchain-mcp-adapters`’s `MultiServerMCPClient` [[15]](#references).

Agents reason; MCP servers **do**. Updating a GitHub or CI integration should ideally be a server deploy, not an agent code change [[2]](#references).

### 7.2 Least-privilege allowlists

From `mcp/client.py`:

| Role | Allowed MCP server keys |
|------|-------------------------|
| `chat` | ∅ |
| `code` | `github` |
| `review` | `github` |
| `deploy` | `ci`, `github` |

**Security note:** both `code` and `review` currently share the same GitHub server URL/token. For stronger isolation, run **two MCP frontends** (or scoped tokens): read/comment for review, write/PR for code. The allowlist is necessary but not sufficient if one token can do everything.

### 7.3 Loading lifecycle

Tools are loaded once per process inside `build_graph()`. That is simple and fast, but:

- New MCP tools require process restart (or a future refresh hook).
- Failed imports / empty config yield `[]` tools; specialists degrade to “plan-only” behavior.

### 7.4 Current tool-loop depth

`agents/code.py` performs at most **one** tool-call round-trip. Production systems often use LangGraph prebuilt ReAct agents or explicit tool nodes with cycle limits [[4]](#references) [[16]](#references). Treat the current loop as a scaffold.

---

## 8. Persistence and threads

### 8.1 Checkpointer selection

`open_checkpointer()`:

- No `DATABASE_URL` → `MemorySaver` (process-local; lost on restart; OK for demos) [[10]](#references)
- With `DATABASE_URL` → `AsyncPostgresSaver.from_conn_string(...)` as an async context manager, `setup()` on enter [[10]](#references) [[17]](#references)

FastAPI lifespan keeps the Postgres context open for the process lifetime so connections remain valid.

### 8.2 Thread semantics

| API behavior | Effect |
|--------------|--------|
| Omit `thread_id` | New UUID; seed `initial_state()` + first message |
| Pass `thread_id` | Load checkpoint; append message only |
| Approve deploy | Must use the **same** `thread_id` that interrupted |

Without a durable checkpointer, interrupt/resume across process restarts will fail [[7]](#references).

---

## 9. HTTP API (technical contract)

| Method | Path | Behavior |
|--------|------|----------|
| `GET` | `/health` | Liveness/readiness probe target |
| `POST` | `/chat` | Sync invoke; returns final reply or interrupt payload |
| `POST` | `/chat/stream` | SSE: `thread`, `token`, `node_end`, `done` events via `astream_events` v2 |
| `POST` | `/threads/{thread_id}/approve-deploy` | `Command(resume=…)` continuation |

### 9.1 Chat response fields

- `intent` / `last_agent` — routing observability  
- `interrupted` + `interrupt_payload` — HITL pause (from `__interrupt__` on invoke result) [[7]](#references)  
- `reply` — latest AI message text  

### 9.2 Streaming caveats

`astream_events` surfaces model tokens when the underlying chat model streams. Self-hosted backends must support streaming for token events to appear; otherwise you still get node lifecycle / done events.

---

## 10. Security model

### 10.1 Trust boundaries

```
[User] --HTTP--> [API] --tools--> [MCP servers] --creds--> [GitHub / CI]
                   |--prompts--> [LLM in VPC]
                   |--state---> [Postgres]
```

- Treat MCP tokens as **high privilege secrets** (Kubernetes Secrets / sealed secrets).
- Network-isolate inference and MCP from the public internet.
- Keep `REQUIRE_DEPLOY_APPROVAL=true` in any environment that can mutate production.

### 10.2 Prompt injection

Any agent that reads untrusted repo content or PR text can be steered. Mitigations aligned with industry practice [[18]](#references):

- Hard tool allowlists (already present)
- Separate credentials per role (recommended next step)
- Prefer structured review outputs; never let review call deploy tools
- Runtime interrupt for deploy (already present)

### 10.3 Supply chain

Pin images (`ollama/ollama`, `vllm/vllm-openai`, `postgres`) in production; scan and mirror into a private registry. Do not bake API keys into images.

---

## 11. Observability

LangSmith env vars remain optional and **default off** (compatible with air-gapped deployments). For self-hosted observability, prefer:

- Structured logs with `thread_id`, `run`/node names, `intent`
- OpenTelemetry around FastAPI + HTTPX to the LLM/MCP endpoints [[19]](#references)
- Metrics: request latency, interrupt count, LLM error rate, token/time per node

LangGraph’s node-level execution model maps cleanly onto trace spans (one span per node) [[1]](#references).

---

## 12. Deployment artifacts

| Artifact | Purpose |
|----------|---------|
| `Dockerfile` | API image via `uv sync` |
| `docker-compose.yml` | Ollama + API + Postgres; `vllm` profile for GPU |
| `deploy/k8s/ai-coworker.yaml` | Namespace, ConfigMap, API Deployment/Service, example vLLM |

**Compose networking:** API defaults to `LLM_BASE_URL=http://ollama:11434/v1` so containers resolve each other by service name.

**vLLM profile:** requires NVIDIA Container Toolkit; model id comes from `VLLM_MODEL` / `LLM_MODEL` [[12]](#references).

---

## 13. Extension roadmap (engineering)

Ordered by leverage:

1. **Multi-hop pipeline** — optional edge `code → review` and `review(pass) → deploy_gate`.
2. **Full tool agent** — replace single-round tool loop with prebuilt ReAct / tool node + recursion limit [[16]](#references).
3. **Split GitHub MCP credentials** — read vs write tokens.
4. **Eval suite** — fixed prompts for routing accuracy and review verdict stability on your local model.
5. **Authn/z on API** — mTLS or internal IdP; thread ACLs if multi-tenant.
6. **Rate limits / concurrency** — protect GPU inference from stampedes.

---

## 14. Module map

```
src/ai_coworker/
├── api/main.py          # HTTP + SSE + resume
├── agents/
│   ├── supervisor.py    # structured intent routing
│   ├── chat.py
│   ├── code.py          # optional MCP tools (1 round)
│   ├── review.py        # structured ReviewResult
│   └── deploy.py        # respects deploy_approved
├── mcp/client.py        # HTTP MCP + allowlists
├── graph.py             # StateGraph + interrupt + checkpointer CM
├── state.py             # CoworkerState
├── llm.py               # self-hosted ChatOpenAI
└── config.py            # Settings
```

---

## References

1. LangChain — *LangGraph overview* (orchestration runtime: durable execution, streaming, HITL, persistence).  
   https://docs.langchain.com/oss/python/langgraph/overview  

2. Anthropic — *Model Context Protocol* (open standard for tool/context connectivity).  
   https://modelcontextprotocol.io  
   Spec / docs hub: https://modelcontextprotocol.io/docs  

3. vLLM — *OpenAI-compatible server* (self-hosted high-throughput inference).  
   https://docs.vllm.ai/en/latest/serving/openai_compatible_server.html  

4. LangChain — *LangChain overview* (models, tools, agent abstractions used with LangGraph).  
   https://docs.langchain.com/oss/python/langchain/overview  

5. LangChain — *Multi-agent* patterns (supervisor / handoffs; start small).  
   https://docs.langchain.com/oss/python/langchain/multi-agent  

6. FRENXT Labs — *Building production multi-agent systems with LangGraph* (supervisor-worker, typed state, checkpointing).  
   https://www.frenxt.com/research/building-production-multi-agent-systems  

7. LangChain — *Interrupts* (HITL pause/resume, checkpointer + `thread_id` requirements).  
   https://docs.langchain.com/oss/python/langgraph/interrupts  

8. LangChain — *Graph API / state reducers* (`add_messages` channel).  
   https://docs.langchain.com/oss/python/langgraph/graph-api  

9. LangGraph Reference — `interrupt` / `Command` (resume semantics, node re-entry).  
   https://reference.langchain.com/python/langgraph/types/interrupt  

10. LangChain — *Checkpointers* (persistence, `thread_id`, production durable savers).  
   https://docs.langchain.com/oss/python/langgraph/checkpointers  

11. Ollama — *OpenAI compatibility*.  
   https://github.com/ollama/ollama/blob/main/docs/openai.md  

12. vLLM documentation home.  
   https://docs.vllm.ai/  

13. Hugging Face — *Text Generation Inference*.  
   https://huggingface.co/docs/text-generation-inference  

14. MCP specification (protocol revision / transports including Streamable HTTP).  
   https://modelcontextprotocol.io/specification/  

15. LangChain — *MCP adapters* (`langchain-mcp-adapters`, `MultiServerMCPClient`).  
   https://github.com/langchain-ai/langchain-mcp-adapters  

16. LangChain — *Prebuilt agents / tool calling patterns* (ReAct-style loops on LangGraph).  
   https://docs.langchain.com/oss/python/langchain/agents  

17. LangGraph checkpoint Postgres package.  
   https://pypi.org/project/langgraph-checkpoint-postgres/  

18. OWASP — *LLM Top 10* (prompt injection, excessive agency, supply chain).  
   https://owasp.org/www-project-top-10-for-large-language-model-applications/  

19. OpenTelemetry — *Python* (self-hosted tracing alternative to SaaS).  
   https://opentelemetry.io/docs/languages/python/  

20. FastAPI — *Lifespan events* (startup/shutdown resource management used for checkpointer).  
   https://fastapi.tiangolo.com/advanced/events/  

21. PostgreSQL — operational reference for durable checkpoint storage.  
   https://www.postgresql.org/docs/current/  

---

## Document history

| Date | Change |
|------|--------|
| 2026-07-25 | Initial technical documentation for v0.1.0 (self-hosted LangGraph + MCP). |
