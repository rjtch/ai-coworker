# AI Coworker — Simple Guide

Multi-agent assistant for **chat**, **code**, **review**, and **deploy**.  
Everything runs on **your** machines/cluster. No cloud AI APIs.

Deep technical docs (architecture, HITL, MCP, security, references): **[TECHNICAL.md](./TECHNICAL.md)**

---

## What it does

| Agent | Purpose |
|-------|---------|
| **Chat** | Answer questions, plan work |
| **Code** | Implement changes / suggest diffs |
| **Review** | Check quality and security (read-only) |
| **Deploy** | Plan/run deploy — **needs your approval** |

A **supervisor** reads your message and routes it to the right agent.

---

## How it fits together

```
You → API (FastAPI)
        → LangGraph (supervisor + agents)
        → Self-hosted LLM (Ollama or vLLM)
        → Optional MCP tools (GitHub, CI)
```

- **LangGraph** = orchestration and memory between steps  
- **MCP** = tools (repos, CI/CD) — not the LLM  
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

Response includes `thread_id`, `intent`, `last_agent`, and `reply`.  
Send the same `thread_id` again to continue the conversation.

### Stream (SSE)

```bash
curl -N http://localhost:8000/chat/stream \
  -H 'content-type: application/json' \
  -d '{"message":"Add a health endpoint"}'
```

### Approve a deploy

If deploy is waiting for approval (`interrupted: true`):

```bash
curl -s http://localhost:8000/threads/THREAD_ID/approve-deploy \
  -H 'content-type: application/json' \
  -d '{"approved":true}'
```

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

Agents get only the tools they need:

| Agent | Allowed MCP |
|-------|-------------|
| chat | none |
| code | github |
| review | github |
| deploy | ci + github |

Set `MCP_*` URLs in `.env` when those servers exist in your network.

---

## Project layout

```
src/ai_coworker/
  agents/     supervisor, chat, code, review, deploy
  api/        HTTP API
  mcp/        tool allowlists
  graph.py    LangGraph workflow
  llm.py      self-hosted client only
docker-compose.yml
deploy/k8s/
docs/SIMPLE.md   ← this file
```

---

## Tests

```bash
uv run pytest
```

---

## Safety notes

1. Deploy never proceeds without approval when `REQUIRE_DEPLOY_APPROVAL=true`.  
2. Review agent must not get deploy/CI write tools.  
3. Keep inference and secrets inside your cluster/VPC.  

---

## Next steps

1. Pull a model and hit `/chat`.  
2. Add GitHub MCP when you want real PRs.  
3. Use vLLM + K8s for production GPU serving.  
4. Turn on Postgres (`DATABASE_URL`) for durable threads.
