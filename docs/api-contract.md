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
Header: Authorization: Bearer <api_key>   (the user's provider key, forwarded by t2p-2.0)
Body: {
  "user_text": string  (required)
  "provider":  string  (required)
  "model":     string  (required)
}
Response 200: { "raw_response": string }
Response 400: { "error": { "code": string, "message": string } }
Response 500: { "error": { "code": string, "message": string } }
```

The provider key travels in the `Authorization` header, never the body, so it is not
logged alongside the payload (this removes the manual `api_key` stripping the old logging
needed). Error codes: `invalid_request` / `invalid_provider` (400), `upstream_error` /
`internal_error` (500). Auth presence/format is validated upstream by t2p-2.0
(`401 unauthorized`); a missing/malformed header here is treated as `invalid_request`.

## `GET /models`

```
Response 200: { "models": [{ "provider": string, "model": string, "default": bool }] }
```
