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
        mock_openai.return_value.responses.parse.return_value = mock_response

    def _mock_gemini(self, mock_genai, content="RAW GEMINI JSON"):
        # google-genai SDK: genai.Client(...).models.generate_content(...).text
        mock_response = MagicMock()
        mock_response.text = content
        candidate = MagicMock()
        candidate.finish_reason.name = "STOP"  # finished cleanly
        mock_response.candidates = [candidate]
        mock_genai.Client.return_value.models.generate_content.return_value = (
            mock_response
        )

    # --- /models ----------------------------------------------------------
    def test_models_returns_registry(self):
        response = self.client.get("/models")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIn("models", data)
        pairs = {(m["provider"], m["model"]) for m in data["models"]}
        self.assertIn(("openai", "gpt-4o"), pairs)
        self.assertIn(("gemini", "gemini-3.5-flash"), pairs)

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
        self.assertEqual(response.status_code, 502)
        # Three attempts total: one initial call plus two retries.
        self.assertEqual(mock_service.generate.call_count, 3)
        # The error surfaces the actual validation problem so the failure is
        # diagnosable instead of generic.
        self.assertIn("problem", response.get_json()["error"]["message"])
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


if __name__ == "__main__":
    unittest.main()
