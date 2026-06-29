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
Response 429: { "error": { "code": string, "message": string } }
Response 502: { "error": { "code": string, "message": string } }
Response 500: { "error": { "code": string, "message": string } }
```

The provider API key is supplied in the `Authorization` header. The connector builds the
prompt, dispatches the call to the selected `provider`/`model`, validates the generated
model against its own validators, and returns the raw provider response. If validation
fails, the connector retries (up to 3 attempts total, raising the temperature on retries);
if every attempt fails validation it returns `502 upstream_error` with a generic message
(`"Could not generate a valid model. Please try again."`).

Error codes: `invalid_request`, `invalid_provider` (400); `unauthorized` (401);
`upstream_error` (429 retryable / 502 bad gateway). For a 502 the `message` carries the
provider's own error text when the provider failed, or the generic
validation-exhaustion message above when all attempts produced invalid models.
`internal_error` (500). A missing or malformed `Authorization` header returns
`401 unauthorized`; a non-JSON body or a missing/empty required field returns
`400 invalid_request`.

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
