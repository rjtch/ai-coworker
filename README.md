# AI Coworker

Multi-agent coworker for **chat**, **code**, **review**, and **deploy**.

Runs **entirely on your infra**: LangGraph + MCP + FastAPI talk to a **self-hosted** OpenAI-compatible LLM (Ollama locally, **vLLM** in cluster). No OpenAI/Anthropic cloud APIs.

## Architecture

```
POST /chat  →  supervisor  →  chat | code | review | deploy_gate → deploy
                                  ↑
                     MCP tools (least privilege per role)
                                  ↑
              LLM_BASE_URL → Ollama / vLLM / TGI (in-cluster)
```

| Role | Job | MCP allowlist |
|------|-----|---------------|
| chat | Q&A / planning | none |
| code | implement / PR | github |
| review | quality / security | github (read) |
| deploy | CI/CD (HITL) | ci + github |

Deploy pauses on `interrupt()` until `POST /threads/{id}/approve-deploy`.

## Quick start (Docker / Podman)

```bash
podman compose up -d --build
```

- **UI:** http://localhost:3080  
- **API:** http://localhost:8000  

The compose stack builds the React UI, API, Postgres, Ollama, and pulls the model automatically.

### Frontend only (dev)

```bash
# API already on :8000
cd frontend && npm install && npm run dev
# → http://localhost:3000 (proxies /api → :8000)
```


### GPU cluster inference (vLLM)

```bash
# requires NVIDIA Container Toolkit
LLM_BASE_URL=http://vllm:8000/v1 \
LLM_MODEL=Qwen/Qwen2.5-Coder-14B-Instruct \
docker compose --profile vllm up --build vllm api postgres
```

### Local uv (point at an already-running server)

```bash
uv sync --extra dev
# LLM_BASE_URL=http://127.0.0.1:11434/v1  LLM_MODEL=qwen2.5-coder:3b
uv run uvicorn ai_coworker.api.main:app --host 0.0.0.0 --port 8000 --app-dir src
```

Kubernetes example manifests: `deploy/k8s/ai-coworker.yaml` (API + vLLM Service).

## Chat

```bash
curl -s localhost:8000/chat -H 'content-type: application/json' \
  -d '{"message":"Explain our deploy pipeline"}' | jq
```

### Approve deploy (after interrupt)

```bash
curl -s localhost:8000/threads/$THREAD_ID/approve-deploy \
  -H 'content-type: application/json' \
  -d '{"approved":true}' | jq
```

### Stream (SSE)

```bash
curl -N localhost:8000/chat/stream -H 'content-type: application/json' \
  -d '{"message":"Add a health check endpoint"}'
```

## Self-hosted LLM contract

The app only needs an OpenAI-compatible `/v1/chat/completions` server:

| Env | Example |
|-----|---------|
| `LLM_BASE_URL` | `http://ollama:11434/v1` or `http://vllm:8000/v1` |
| `LLM_MODEL` | model name as served (`qwen2.5-coder:3b`, HF id for vLLM) |
| `LLM_API_KEY` | any string if the server ignores auth |

Works with Ollama, vLLM, TGI, llama.cpp server, LocalAI, etc.

## MCP

Set remote MCP HTTP endpoints in `.env` (can also be in-cluster Services):

- `MCP_GITHUB_URL` / `MCP_GITHUB_TOKEN`
- `MCP_CI_URL` / `MCP_CI_TOKEN`

## State

Leave `DATABASE_URL` empty for in-memory checkpoints. Compose/K8s: use the bundled Postgres for durable threads.

## Tests

```bash
uv run pytest
```

## Docs

| Doc | Audience |
|-----|----------|
| **[docs/SIMPLE.md](docs/SIMPLE.md)** | Quick start & operator basics |
| **[docs/TECHNICAL.md](docs/TECHNICAL.md)** | Deep architecture, control flow, security, references |

## Layout

```
src/ai_coworker/
  agents/     # graph nodes (logic only)
  prompts/    # Markdown + manifest.yaml ← edit prompts here
  api/ mcp/ graph.py …
frontend/
docs/
```

Prompt conventions: [`src/ai_coworker/prompts/README.md`](src/ai_coworker/prompts/README.md).
