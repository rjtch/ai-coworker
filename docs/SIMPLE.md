# AI Coworker — Simple Guide

Self-hosted **chat** with a local LLM (Ollama or vLLM). Optional PDF/image attachments and editable prompts.  
Everything runs on **your** machines/cluster. No cloud AI APIs.

Architecture, API, MCP scaffold, security: **[TECHNICAL.md](./TECHNICAL.md)**  
Coding agents: **[AGENTS.md](../AGENTS.md)**

---

## What it does

You send a message (optional PDF / PNG / JPEG). FastAPI runs a one-node LangGraph (`chat`) against your OpenAI-compatible server and streams the reply. Threads can persist in Postgres.

MCP GitHub/CI URLs can be set in `.env`, but the chat agent does **not** call those tools yet.

---

## How it fits together

```
You → API (FastAPI)
        → LangGraph (chat node)
        → Self-hosted LLM (Ollama or vLLM)
        → Optional MCP config (not bound to the model yet)
```

- **LangGraph** = orchestration and memory between turns  
- **MCP** = future tools (repos, CI/CD) — not the LLM  
- **LLM** = only your local/cluster OpenAI-compatible server  

---

## Requirements

- Docker + Docker Compose **or** Python 3.12 + [uv](https://docs.astral.sh/uv/)
- Enough RAM/GPU for the model you choose  
  - Small/dev: Ollama + a smaller model  
  - Prod/GPU: vLLM

---

## Run with Docker (recommended)

```bash
cp .env.example .env
docker compose up --build

# pull the model once
docker compose exec ollama ollama pull qwen2.5-coder:3b
```

| Service | URL |
|---------|-----|
| API | http://localhost:8000 |
| Ollama | http://localhost:11434 |
| Postgres | localhost:5432 |

Health check:

```bash
curl http://localhost:8000/health
```

---

## Run without Docker

1. Start Ollama (or vLLM) and pull a model.  
2. Copy env and point at the server:

```bash
cp .env.example .env
# LLM_BASE_URL=http://127.0.0.1:11434/v1
# LLM_MODEL=qwen2.5-coder:3b

uv sync --extra dev
uv run uvicorn ai_coworker.api.main:app --host 0.0.0.0 --port 8000 --app-dir src
```

---

## Important settings (`.env`)

| Variable | Meaning | Example |
|----------|---------|---------|
| `LLM_BASE_URL` | Your inference server | `http://ollama:11434/v1` |
| `LLM_MODEL` | Model name as served | `qwen2.5-coder:3b` |
| `LLM_API_KEY` | Ignored by most local servers | `not-needed` |
| `DATABASE_URL` | Empty = memory only; set for durable chats | Postgres URL |
| `REQUIRE_DEPLOY_APPROVAL` | Pause before deploy | `true` |
| `MCP_GITHUB_URL` | Optional GitHub MCP | (empty = no tools) |
| `MCP_CI_URL` | Optional CI/CD MCP | (empty = no tools) |

---

## API usage

### Chat

```bash
curl -s http://localhost:8000/chat \
  -H 'content-type: application/json' \
  -d '{"message":"Explain how deploy works"}'
```

Response includes `thread_id`, `last_agent`, and `reply`.  
Send the same `thread_id` again to continue the conversation.

### Stream (SSE)

```bash
curl -N http://localhost:8000/chat/stream \
  -H 'content-type: application/json' \
  -d '{"message":"Add a health endpoint"}'
```

WebSocket `/ws/chat` is what the UI uses (supports cancel).

---

## Self-hosted LLM options

| Mode | When | Base URL |
|------|------|----------|
| **Ollama** | Laptop / small cluster | `http://…:11434/v1` |
| **vLLM** | GPU cluster / production | `http://…:8000/v1` |

GPU Compose profile:

```bash
LLM_BASE_URL=http://vllm:8000/v1 \
LLM_MODEL=Qwen/Qwen2.5-Coder-14B-Instruct \
docker compose --profile vllm up --build vllm api postgres
```

Kubernetes starter manifests: `deploy/k8s/ai-coworker.yaml`.

Any server that speaks **OpenAI `/v1/chat/completions`** works (Ollama, vLLM, TGI, llama.cpp, LocalAI, …).

---

## MCP tools (optional)

Chat currently has **no** MCP allowlist. Env `MCP_GITHUB_URL` / `MCP_CI_URL` is scaffolding for a future tool loop.

---

## Project layout

```
src/ai_coworker/
  agents/     chat node
  api/        HTTP + WebSocket
  mcp/        tool allowlists (unused by chat)
  graph.py    LangGraph workflow
  llm.py      self-hosted client only
compose.yml
deploy/k8s/
docs/SIMPLE.md    ← this file
docs/TECHNICAL.md
AGENTS.md
```

---

## Tests

```bash
uv run pytest
```

---

## Safety notes

1. Chat HTTP has no auth — do not expose write/shell tools without a runtime gate.  
2. Keep inference and secrets inside your cluster/VPC.  
3. Treat uploaded PDFs as untrusted text.

---

## Next steps

1. Pull a model and hit `/chat`.  
2. Turn on Postgres (`DATABASE_URL`) for durable threads.  
3. Use vLLM + K8s for production GPU serving.  
4. Bind MCP tools in a bounded agent loop when you want real repo actions.
