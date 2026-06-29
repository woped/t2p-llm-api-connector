import time
import unittest
from unittest.mock import patch, MagicMock

from app import create_app
from config import TestingConfig


class TestV2Api(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestingConfig)
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()

    def tearDown(self):
        self.app_context.pop()

    # --- helpers ----------------------------------------------------------
    def _mock_openai(self, mock_openai, content="RAW BPMN JSON"):
        # Responses API: client.responses.parse(...).output_text
        mock_response = MagicMock()
        mock_response.output_text = content
        mock_response.status = "completed"  # not truncated/incomplete
        # Realistic token usage so the cost-estimation path runs on real ints.
        mock_response.usage.input_tokens = 100
        mock_response.usage.output_tokens = 200
        mock_response.usage.total_tokens = 300
        mock_response.usage.input_tokens_details.cached_tokens = 0
        mock_openai.return_value.responses.parse.return_value = mock_response

    def _mock_gemini(self, mock_genai, content="RAW GEMINI JSON"):
        # google-genai SDK: genai.Client(...).models.generate_content(...).text
        mock_response = MagicMock()
        mock_response.text = content
        candidate = MagicMock()
        candidate.finish_reason.name = "STOP"  # finished cleanly
        mock_response.candidates = [candidate]
        # Realistic token usage so the cost-estimation path runs on real ints.
        mock_response.usage_metadata.prompt_token_count = 100
        mock_response.usage_metadata.candidates_token_count = 200
        mock_response.usage_metadata.thoughts_token_count = 0
        mock_response.usage_metadata.total_token_count = 300
        mock_response.usage_metadata.cached_content_token_count = 0
        mock_genai.Client.return_value.models.generate_content.return_value = (
            mock_response
        )

    # --- /models ----------------------------------------------------------
    def test_models_returns_registry(self):
        response = self.client.get("/models")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIn("models", data)
        by_pair = {(m["provider"], m["model"]): m for m in data["models"]}
        self.assertIn(("openai", "gpt-4o"), by_pair)
        self.assertIn(("gemini", "gemini-3.5-flash"), by_pair)

        # Each model advertises its full registry metadata: parameter support
        # and pricing (USD per 1M tokens), so a client need not look it up.
        mini = by_pair[("openai", "gpt-5.4-mini")]
        self.assertFalse(mini["supports_temperature"])
        self.assertEqual(
            mini["pricing"], {"input": 0.75, "cached_input": 0.075, "output": 4.50}
        )
        # Gemini models accept temperature and have no cached-input rate.
        flash = by_pair[("gemini", "gemini-3.5-flash")]
        self.assertTrue(flash["supports_temperature"])
        self.assertNotIn("cached_input", flash["pricing"])

    # --- correlation id ---------------------------------------------------
    def test_response_echoes_request_id_header(self):
        # Every response carries an X-Request-ID, minted when none is supplied.
        response = self.client.get("/models")
        self.assertTrue(response.headers.get("X-Request-ID"))

    def test_honours_inbound_request_id(self):
        # A forwarded X-Request-ID (from t2p-2.0) is honoured and echoed back, so
        # both services log the request under the same id.
        response = self.client.get("/models", headers={"X-Request-ID": "forwarded-id"})
        self.assertEqual(response.headers.get("X-Request-ID"), "forwarded-id")

    def test_error_body_carries_matching_request_id(self):
        # An error body's request_id matches the X-Request-ID header (here a 401
        # from the missing Authorization header).
        response = self.client.post(
            "/generate", json={"user_text": "x"}, headers={"X-Request-ID": "trace-9"}
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()["error"]["request_id"], "trace-9")
        self.assertEqual(response.headers.get("X-Request-ID"), "trace-9")

    # --- cost estimation --------------------------------------------------
    def test_estimate_cost_uses_registry_pricing(self):
        from app.services import model_registry

        # gpt-5.4-mini: input $0.75/1M, output $4.50/1M.
        cost = model_registry.estimate_cost(
            "openai", "gpt-5.4-mini", 1_000_000, 1_000_000
        )
        self.assertAlmostEqual(cost, 0.75 + 4.50)

    def test_estimate_cost_discounts_cached_input(self):
        from app.services import model_registry

        # 1M prompt tokens all cached -> billed at the cached rate ($0.075/1M),
        # not the standard input rate.
        cost = model_registry.estimate_cost(
            "openai", "gpt-5.4-mini", 1_000_000, 0, cached_tokens=1_000_000
        )
        self.assertAlmostEqual(cost, 0.075)

    def test_estimate_cost_none_for_non_integer_or_unknown(self):
        from app.services import model_registry

        # No usable counts -> no cost (avoids printing a bogus figure).
        self.assertIsNone(
            model_registry.estimate_cost("openai", "gpt-5.4-mini", None, 10)
        )
        # Unpriced/unknown model -> no cost.
        self.assertIsNone(model_registry.estimate_cost("openai", "bogus", 10, 10))

    # --- /generate success ------------------------------------------------
    @patch("app.services.llm_service.OpenAI")
    def test_generate_openai_success(self, mock_openai):
        self._mock_openai(mock_openai)
        response = self.client.post(
            "/generate",
            headers={"Authorization": "Bearer secret-token"},
            json={
                "user_text": "describe a process",
                "provider": "openai",
                "model": "gpt-4o",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"raw_response": "RAW BPMN JSON"})
        # The API key is taken from the header, never the body.
        mock_openai.assert_called_once_with(api_key="secret-token")

    @patch("app.services.llm_service.genai")
    def test_generate_gemini_success(self, mock_genai):
        self._mock_gemini(mock_genai)
        response = self.client.post(
            "/generate",
            headers={"Authorization": "Bearer secret-token"},
            json={
                "user_text": "describe a process",
                "provider": "gemini",
                "model": "gemini-3.5-flash",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"raw_response": "RAW GEMINI JSON"})

    # --- /generate retry-on-validation -----------------------------------
    @patch("app.validation.VALIDATORS", [lambda model: ["problem"]])
    @patch("app.api.routes._llm_service")
    def test_generate_retries_then_errors_when_validation_fails(self, mock_service):
        mock_service.generate.return_value = '{"events": [], "tasks": []}'
        response = self.client.post(
            "/generate",
            headers={"Authorization": "Bearer secret-token"},
            json={"user_text": "x", "provider": "openai", "model": "gpt-4o"},
        )
        # Unprocessable input (the provider answered but no attempt was valid),
        # not an upstream failure -> 422, not 502.
        self.assertEqual(response.status_code, 422)
        # Three attempts total: one initial call plus two retries.
        self.assertEqual(mock_service.generate.call_count, 3)
        error = response.get_json()["error"]
        self.assertEqual(error["code"], "model_unprocessable")
        # The user-facing message stays friendly; the concrete validation
        # problems ride along in ``details`` so the failure is diagnosable.
        self.assertIn("problem", error["details"])
        # The first attempt runs blind; each retry is fed the previous attempt's
        # problems so the model can correct them.
        feedbacks = [
            call.kwargs.get("feedback") for call in mock_service.generate.call_args_list
        ]
        self.assertEqual(feedbacks, [None, "problem", "problem"])

    @patch("app.validation.VALIDATORS", [lambda model: ["problem"]])
    @patch("app.api.routes._llm_service")
    def test_generate_escalates_temperature_on_retry(self, mock_service):
        # The first attempt must be deterministic (temperature 0); regenerations
        # must use a non-zero temperature, otherwise the identical prompt would
        # reproduce the identical invalid output and the retries are wasted.
        from app.api.routes import _RETRY_TEMPERATURE

        mock_service.generate.return_value = '{"events": [], "tasks": []}'
        self.client.post(
            "/generate",
            headers={"Authorization": "Bearer secret-token"},
            json={"user_text": "x", "provider": "openai", "model": "gpt-4o"},
        )
        temperatures = [
            call.kwargs["temperature"] for call in mock_service.generate.call_args_list
        ]
        self.assertEqual(temperatures, [0.0, _RETRY_TEMPERATURE, _RETRY_TEMPERATURE])

    @patch("app.validation.VALIDATORS", [])
    @patch("app.api.routes._llm_service")
    def test_generate_does_not_retry_when_valid(self, mock_service):
        mock_service.generate.return_value = '{"events": [], "tasks": []}'
        response = self.client.post(
            "/generate",
            headers={"Authorization": "Bearer secret-token"},
            json={"user_text": "x", "provider": "openai", "model": "gpt-4o"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(mock_service.generate.call_count, 1)

    # --- /generate validation --------------------------------------------
    def test_generate_missing_bearer_is_401(self):
        response = self.client.post(
            "/generate",
            json={"user_text": "x", "provider": "openai", "model": "gpt-4o"},
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()["error"]["code"], "unauthorized")

    def test_generate_missing_field_is_400(self):
        response = self.client.post(
            "/generate",
            headers={"Authorization": "Bearer secret-token"},
            json={"provider": "openai", "model": "gpt-4o"},  # no user_text
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"]["code"], "invalid_request")

    def test_generate_invalid_provider_is_400(self):
        response = self.client.post(
            "/generate",
            headers={"Authorization": "Bearer secret-token"},
            json={"user_text": "x", "provider": "bogus", "model": "gpt-4o"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"]["code"], "invalid_provider")

    # --- /generate upstream failure --------------------------------------
    @patch("app.services.llm_service.OpenAI")
    def test_generate_provider_error_is_502_upstream(self, mock_openai):
        # A provider error with no recognisable status maps to 502, and the
        # real upstream error text is passed through as the message.
        mock_openai.return_value.responses.parse.side_effect = RuntimeError("boom")
        response = self.client.post(
            "/generate",
            headers={"Authorization": "Bearer secret-token"},
            json={"user_text": "x", "provider": "openai", "model": "gpt-4o"},
        )
        self.assertEqual(response.status_code, 502)
        error = response.get_json()["error"]
        self.assertEqual(error["code"], "upstream_error")
        self.assertEqual(error["message"], "boom")

    @patch("app.services.llm_service.genai")
    def test_generate_gemini_provider_error_is_502_upstream(self, mock_genai):
        # The Gemini provider must map a provider-side failure to the same
        # upstream_error 502 as OpenAI does (the OpenAI path is covered above;
        # this closes the second-provider asymmetry).
        mock_genai.Client.return_value.models.generate_content.side_effect = (
            RuntimeError("boom")
        )
        response = self.client.post(
            "/generate",
            headers={"Authorization": "Bearer secret-token"},
            json={
                "user_text": "x",
                "provider": "gemini",
                "model": "gemini-3.5-flash",
            },
        )
        self.assertEqual(response.status_code, 502)
        error = response.get_json()["error"]
        self.assertEqual(error["code"], "upstream_error")
        self.assertEqual(error["message"], "boom")

    @patch("app.services.llm_service.OpenAI")
    def test_generate_rate_limit_is_passed_through_as_429(self, mock_openai):
        # A 429 from the provider is retryable, so the connector mirrors it
        # instead of collapsing it to 502.
        exc = RuntimeError("rate limited")
        exc.status_code = 429
        mock_openai.return_value.responses.parse.side_effect = exc
        response = self.client.post(
            "/generate",
            headers={"Authorization": "Bearer secret-token"},
            json={"user_text": "x", "provider": "openai", "model": "gpt-4o"},
        )
        self.assertEqual(response.status_code, 429)
        error = response.get_json()["error"]
        self.assertEqual(error["code"], "upstream_error")
        self.assertEqual(error["message"], "rate limited")

    # --- /generate truncation / abnormal finish --------------------------
    @patch("app.services.llm_service.OpenAI")
    def test_generate_openai_incomplete_is_502(self, mock_openai):
        # A response truncated at max_output_tokens comes back as "incomplete"
        # with partial output; it must surface as an upstream error, not be
        # passed through as if it were a valid model.
        mock_response = MagicMock()
        mock_response.status = "incomplete"
        mock_response.incomplete_details.reason = "max_output_tokens"
        mock_response.output_text = '{"events": [{"id": "startEv'  # partial JSON
        mock_openai.return_value.responses.parse.return_value = mock_response
        response = self.client.post(
            "/generate",
            headers={"Authorization": "Bearer secret-token"},
            json={"user_text": "x", "provider": "openai", "model": "gpt-4o"},
        )
        self.assertEqual(response.status_code, 502)
        error = response.get_json()["error"]
        self.assertEqual(error["code"], "upstream_error")
        self.assertIn("max_output_tokens", error["message"])

    @patch("app.services.llm_service.genai")
    def test_generate_gemini_max_tokens_is_502(self, mock_genai):
        # Gemini truncation surfaces as finish_reason=MAX_TOKENS; reading .text
        # would yield broken JSON, so it must fail as an upstream error.
        mock_response = MagicMock()
        mock_response.text = '{"events": [{"id": "startEv'  # partial JSON
        candidate = MagicMock()
        candidate.finish_reason.name = "MAX_TOKENS"
        mock_response.candidates = [candidate]
        mock_genai.Client.return_value.models.generate_content.return_value = (
            mock_response
        )
        response = self.client.post(
            "/generate",
            headers={"Authorization": "Bearer secret-token"},
            json={"user_text": "x", "provider": "gemini", "model": "gemini-3.5-flash"},
        )
        self.assertEqual(response.status_code, 502)
        error = response.get_json()["error"]
        self.assertEqual(error["code"], "upstream_error")
        self.assertIn("MAX_TOKENS", error["message"])

    # --- /generate malformed body ----------------------------------------
    def test_generate_non_json_body_is_400(self):
        # A valid bearer token but a body that is not JSON must be rejected as
        # invalid_request, distinct from the missing-field case.
        response = self.client.post(
            "/generate",
            headers={
                "Authorization": "Bearer secret-token",
                "Content-Type": "text/plain",
            },
            data="this is not json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"]["code"], "invalid_request")

    # --- internal async submit/poll --------------------------------------
    def _poll_until_terminal(self, job_id, timeout=5.0):
        """Poll the status endpoint until the background worker finishes."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            resp = self.client.get(f"/internal/jobs/{job_id}")
            self.assertEqual(resp.status_code, 200)
            payload = resp.get_json()
            if payload["status"] in ("succeeded", "failed"):
                return payload
            time.sleep(0.02)
        self.fail(f"job {job_id} did not reach a terminal state within {timeout}s")

    @patch("app.validation.VALIDATORS", [])
    @patch("app.api.routes._llm_service")
    def test_async_submit_then_poll_returns_result(self, mock_service):
        # This is the path t2p-2.0 normally drives: submit returns a job id
        # immediately (202), the generation runs in a background worker, and
        # polling eventually yields the same body the sync endpoint would have.
        mock_service.generate.return_value = '{"events": [], "tasks": []}'

        submit = self.client.post(
            "/internal/jobs/generate",
            headers={"Authorization": "Bearer secret-token"},
            json={"user_text": "x", "provider": "openai", "model": "gpt-4o"},
        )
        self.assertEqual(submit.status_code, 202)
        body = submit.get_json()
        self.assertTrue(body["job_id"])
        self.assertEqual(body["status"], "queued")
        self.assertEqual(body["status_url"], f"/internal/jobs/{body['job_id']}")

        payload = self._poll_until_terminal(body["job_id"])
        self.assertEqual(payload["status"], "succeeded")
        # The async result preserves the sync contract: {"raw_response": <model>}.
        self.assertEqual(
            payload["result"], {"raw_response": '{"events": [], "tasks": []}'}
        )

    @patch("app.api.routes._llm_service")
    def test_async_submit_rejects_invalid_request_synchronously(self, mock_service):
        # Pre-generation validation runs on the submit request itself, so a
        # malformed request gets an immediate 4xx instead of a queued job that
        # only fails later on poll. No generation is attempted.
        response = self.client.post(
            "/internal/jobs/generate",
            headers={"Authorization": "Bearer secret-token"},
            json={"provider": "openai", "model": "gpt-4o"},  # no user_text
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"]["code"], "invalid_request")
        mock_service.generate.assert_not_called()

    def test_async_poll_unknown_job_is_404(self):
        # An unknown (or expired) job id is reported as not_found, never a 200
        # with an empty body that a poller could misread as "still running".
        response = self.client.get("/internal/jobs/does-not-exist")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.get_json()["error"]["code"], "not_found")


if __name__ == "__main__":
    unittest.main()
