# LLM API connector — internal API contract (refactor)

Status: **proposed** — interface frozen for the `feature/api-refactor` work. Code does
not implement this yet. This file is the source of truth both sides build against.

This API is internal: t2p-2.0 is the only consumer. There are no other callers, so the
old endpoints are deleted outright and both sides adapt — no versioning, no compat window.

## Endpoint map

| Method | Path | State |
|--------|------|-------|
| GET  | `/metrics`     | unchanged |
| GET  | `/_/_/echo`    | unchanged |
| POST | `/call_openai` | **removed** |
| POST | `/call_gemini` | **removed** |
| POST | `/generate`    | **new** |
| GET  | `/models`      | **new** |

## `POST /generate`

```
Body: {
  "api_key":   string  (required)
  "user_text": string  (required)
  "provider":  string  (required)
  "model":     string  (required)
}
Response 200: { "raw_response": string }
Response 400: { "error": { "code": string, "message": string } }
Response 500: { "error": { "code": string, "message": string } }
```

## `GET /models`

```
Response 200: { "models": [{ "provider": string, "model": string, "default": bool }] }
```
