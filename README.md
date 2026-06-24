# llm-api-connector

HTTP connector service that proxies process-description text to LLM providers (OpenAI, Google Gemini) and returns the raw model response. Consumed by the t2p-2.0 backend.

## Prerequisites

1. Create a virtual environment:
    ```bash
    python -m venv .venv
    ```

2. Activate the virtual environment:
    - **Windows:**
      ```bash
      .venv\Scripts\activate
      ```
    - **macOS/Linux:**
      ```bash
      source .venv/bin/activate
      ```

3. Install the requirements:
    ```bash
    pip install -r requirements/dev.txt
    ```

After cloning this repository, it's essential to [set up git hooks](https://github.com/woped/woped-git-hooks/blob/main/README.md#activating-git-hooks-after-cloning-a-repository) to ensure project standards.

## Running the Application Locally

A `.flaskenv` file in the project root already sets `FLASK_APP` and the environment, so activating the venv and running `flask run` is enough:

```bash
flask run
```

The application will be accessible at http://localhost:5000.  
The interactive API documentation (Swagger UI) is available at http://localhost:5000/docs/.
The generated OpenAPI specification is available at http://localhost:5000/openapi.json.

> **Note:** `FLASK_ENV` is still used by this project's `config.py` to select the active configuration class (`development` / `production` / `testing`). It is separate from Flask's own debug flag and is already pre-configured in `.flaskenv` for local development — no manual export is needed.

## Calling the API

All requests to `/generate` require the provider API key as a Bearer token in the `Authorization` header — it is never part of the request body:

```
Authorization: Bearer <your-provider-api-key>
```

Example request body for `POST /generate`:
```json
{
  "user_text": "A customer submits an order. A clerk checks the inventory ...",
  "provider": "openai",
  "model": "gpt-4o",
  "prompting_strategy": "few_shot"
}
```

For supported providers, the connector accepts any submitted model name and forwards it to
the provider. Newly released provider models therefore do not require a code change in the
connector.

`prompting_strategy` is optional. Supported values are `zero_shot` and `few_shot`.
If omitted, `zero_shot` is used by default.

Use `GET /models` to retrieve the list of provider/model pairs discovered from the backing
providers. If you pass `Authorization: Bearer <api_key>`, the connector can use that key for
discovery; otherwise it uses configured environment keys when available. See `/openapi.json`
or the Swagger UI at `/docs/` for the full API contract.

## Provider Host Configuration

By default, providers are called via their public endpoints. For production gateways,
reverse proxies, or internal egress setups, you can override provider hosts via environment
variables:

- `OPENAI_BASE_URL` (alias: `OPENAI_HOST`)
- `GEMINI_API_ENDPOINT` (alias: `GEMINI_HOST`)

Example:

```bash
docker run -p 5000:5000 \
  -e OPENAI_BASE_URL=https://api.openai.com/v1 \
  -e GEMINI_API_ENDPOINT=generativelanguage.googleapis.com \
  -e OPENAI_API_KEY=... \
  -e GEMINI_API_KEY=... \
  llm-api-connector
```

## Running the Application with Docker

To build the docker image, navigate to the root directory of the project and run the following command:
```bash
docker build -t llm-api-connector .
```

To run the application in docker, run the following command:
```bash
docker run -p 5000:5000 llm-api-connector
```
The application will be accessible at http://localhost:5000.

## Testing

Run the following commands from the **project root** (not the `tests` folder — the test suite needs to resolve the `app` package):

```bash
coverage run -m unittest discover -s tests
```
You can then view the coverage report by running:
```bash
coverage report
```
if you want to see the coverage in html format, run:
```bash
coverage html
```
and open the htmlcov/index.html file in your browser.
