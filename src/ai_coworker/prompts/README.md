# Prompts

Prompt templates are stored in a **persisted JSON catalog** (editable from the UI or API). Bundled defaults live inline in `manifest.yaml` and seed the catalog on first boot.

## Conventions

| Practice | How we do it |
|----------|----------------|
| Storage | Persisted JSON at `PROMPTS_PERSIST_PATH` (default `/data/prompts.json`) |
| Defaults | Inline `text` in `manifest.yaml` — seeded once, then catalog is source of truth |
| IDs | Stable dotted names (`chat.system`) |
| Variables | `{brace}` placeholders via LangChain `PromptTemplate` |
| Loading | `ai_coworker.prompts.get_text` / `render` / `system_message` |

## API

```bash
# List prompts
curl -s http://localhost:8000/prompts | jq

# Update (immediate effect on next chat)
curl -s -X PUT http://localhost:8000/prompts/chat.system \
  -H 'content-type: application/json' \
  -d '{"text":"You are a friendly coworker..."}' | jq

# Delete permanently (removed from catalog)
curl -s -X DELETE http://localhost:8000/prompts/chat.system

# Reset one prompt to bundled default
curl -s -X POST http://localhost:8000/prompts/chat.system/reset | jq

# Reset entire catalog to manifest defaults
curl -s -X POST http://localhost:8000/prompts/reload
```

Optional auth: set `PROMPTS_ADMIN_TOKEN` and pass `X-Prompts-Token: <token>` on mutating requests.

## IDs

See `manifest.yaml` for the default catalog.
