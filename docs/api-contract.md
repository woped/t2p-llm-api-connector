# LLM API Connector — Internal API

Internal HTTP API consumed by t2p-2.0. The machine-readable form of this
contract is [`docs/openapi.yaml`](openapi.yaml); this document is authoritative
where the two disagree.

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
  "user_text":          string  (required)
  "provider":           string  (required)
  "model":              string  (required)
  "prompting_strategy": string  (optional, "few_shot" | "zero_shot"; default "few_shot")
}
Response 200: { "raw_response": string }
Response 400: { "error": { "code": string, "message": string } }
Response 401: { "error": { "code": string, "message": string } }
Response 422: { "error": { "code": string, "message": string, "details": [string] } }
Response 429: { "error": { "code": string, "message": string } }
Response 502: { "error": { "code": string, "message": string } }
Response 500: { "error": { "code": string, "message": string } }
```

The provider API key is supplied in the `Authorization` header. The connector builds the
prompt, dispatches the call to the selected `provider`/`model`, validates the generated
model against its own validators, and returns the raw provider response. If validation
fails, the connector retries (up to 3 attempts total, raising the temperature on retries);
if every attempt still fails validation it returns `422 model_unprocessable`. This is a
client-actionable condition (the provider answered, but the description could not be turned
into a sound workflow net — rephrase or simplify), not an upstream failure, hence 4xx not
5xx. The `message` is a friendly, user-facing summary; the `details` array carries the last
attempt's concrete validation problems for diagnostics (these are repair-oriented and meant
for logs/developers, not for direct display to end users).

## Error reference

Every error response uses the body `{ "error": { "code", "message", "details"? } }`.
`code` is the stable identifier to branch on; `message` is human-readable; `details`
(array of strings) appears only where noted. t2p-2.0 relays the 4xx rows verbatim
(status + body) and maps the 5xx rows to its own `upstream_error`/`internal_error`.

| HTTP | `code` | Meaning | How to fix |
|------|--------|---------|------------|
| 400 | `invalid_request` | Body is not JSON, or a required field (`user_text` / `provider` / `model`) is missing or empty. | Send a JSON body with all three required fields populated. |
| 400 | `invalid_provider` | The `provider`/`model` pair is not in the registry. | Pick a pair returned by `GET /models`. |
| 401 | `unauthorized` | `Authorization` header missing or not a well-formed `Bearer <key>`. | Send `Authorization: Bearer <api_key>`. |
| 422 | `model_unprocessable` | The provider answered, but no attempt (3 total) produced a valid workflow net. `details` lists the concrete validation problems. | Rephrase or simplify the description — avoid splits/joins without a clear gateway, more than one ending, or "cancel at any point". Not retryable unchanged. |
| 429 | `upstream_error` | The provider rate-limited the call; `message` carries the provider's text. | Back off and retry. |
| 502 | `upstream_error` | The provider failed or returned an unusable/incomplete response; `message` carries the provider's text. | Transient upstream failure — retry later. |
| 500 | `internal_error` | Unexpected connector fault. | Not caller-fixable; inspect connector logs / report. |

`GET /models` returns `200`, or `500 internal_error` on an unexpected failure.

## `GET /models`

```
Response 200: {
  "models": [{
    "provider": string,
    "model": string,
    "supports_temperature": boolean,
    "pricing": { "input": number, "output": number, "cached_input"?: number }
  }]
}
```

`pricing` is USD per 1,000,000 tokens. `cached_input` appears only for models
that offer a reduced cached-input rate. `supports_temperature` is `false` for
reasoning models (GPT-5.x / o-series) that reject the `temperature` parameter.
