# LLM API Connector — Internal API

Internal HTTP API consumed by t2p-2.0. The machine-readable form of this
contract is [`docs/openapi.yaml`](openapi.yaml); this document is authoritative
where the two disagree.

## Endpoints

| Method | Path |
|--------|------|
| POST | `/generate` |
| GET  | `/models`   |
| POST | `/call_openai` |
| POST | `/call_gemini` |
| GET  | `/metrics`  |
| GET  | `/_/_/echo` |

## `POST /generate`

```
Header: Authorization: Bearer <api_key>
Body: {
  "user_text": string  (required)
  "provider":  string  (required)
  "model":     string  (required)
}
Response 200: { "raw_response": string }
Response 400: { "error": { "code": string, "message": string } }
Response 500: { "error": { "code": string, "message": string } }
```

The provider API key is supplied in the `Authorization` header. The connector builds the
prompt, dispatches the call to the selected `provider`/`model`, and returns the raw
provider response containing the BPMN structure JSON. The provider-specific
`/call_openai` and `/call_gemini` operations remain available for existing
internal callers.

Error codes: `invalid_request`, `invalid_provider` (400); `upstream_error`,
`internal_error` (500). A missing or malformed `Authorization` header returns
`400 invalid_request`.

## `GET /models`

```
Response 200: { "models": [{ "provider": string, "model": string, "default": bool }] }
```
