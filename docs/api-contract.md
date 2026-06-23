# LLM API Connector — Internal API

Internal HTTP API consumed by t2p-2.0. The machine-readable form of this
contract is the generated OpenAPI spec at `/openapi.json` (Flasgger). A
compatibility alias `/openapi.yaml` serves the same specification in YAML format.

This connector is **internal — called solely by t2p-2.0** — and is the
**authoritative validator** for the generate contract. It owns all request
validation: the bearer token (and raw-key extraction from it), JSON-body shape,
required-field presence, and provider/model validation against the registry.
t2p-2.0 does not duplicate these guards; it forwards requests and relays the
responses below (including 4xx) unchanged.

## Endpoints

| Method | Path |
|--------|------|
| POST | `/generate` |
| GET  | `/models`   |
| GET  | `/metrics`  |
| GET  | `/_/_/echo` |

## `POST /generate`

```
Header: Authorization: Bearer <api_key>
Body: {
  "user_text": string  (required)
  "provider":  string  (required)
  "model":     string  (required)
  "prompting_strategy": string  (optional: "zero_shot" | "few_shot", default: "zero_shot")
}
Response 200: { "raw_response": string }
Response 400: { "error": { "code": string, "message": string } }
Response 401: { "error": { "code": string, "message": string } }
Response 500: { "error": { "code": string, "message": string } }
```

The provider API key is supplied in the `Authorization` header. The connector builds the
prompt, dispatches the call to the selected `provider`/`model`, and returns the raw
provider response.

Error codes: `invalid_request`, `invalid_provider` (400); `unauthorized` (401);
`upstream_error`, `internal_error` (500). A missing or malformed `Authorization`
header returns `401 unauthorized`; a non-JSON body or a missing/empty required
field returns `400 invalid_request`.

## `GET /models`

```
Response 200: { "models": [{ "provider": string, "model": string }] }
```
