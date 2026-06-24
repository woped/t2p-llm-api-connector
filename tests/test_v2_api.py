import unittest
from unittest.mock import MagicMock, patch

from app import create_app
from app.api import routes as api_routes
from config import TestingConfig


class TestV2Api(unittest.TestCase):
    @patch("app.model_registry.refresh_model_cache")
    def setUp(self, mock_refresh_model_cache):
        self.app = create_app(TestingConfig)
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()

    def tearDown(self):
        self.app_context.pop()

    # --- helpers ----------------------------------------------------------
    def _mock_openai(self, mock_openai, content="RAW BPMN JSON"):
        mock_choice = MagicMock()
        mock_choice.message.content = content
        mock_completion = MagicMock()
        mock_completion.choices = [mock_choice]
        mock_openai.return_value.chat.completions.create.return_value = mock_completion

    def _mock_gemini(self, mock_genai, content="RAW GEMINI JSON"):
        mock_response = MagicMock()
        mock_response.text = content
        mock_model = MagicMock()
        mock_model.generate_content.return_value = mock_response
        mock_genai.GenerativeModel.return_value = mock_model

    # --- /models ----------------------------------------------------------
    @patch("app.api.routes.model_registry.get_cached_models")
    @patch("app.api.routes.model_registry.refresh_model_cache")
    def test_models_returns_registry(
        self, mock_refresh_model_cache, mock_get_cached_models
    ):
        mock_get_cached_models.return_value = [
            {"provider": "openai", "model": "gpt-4o"},
            {"provider": "gemini", "model": "gemini-1.5-pro"},
        ]
        response = self.client.get("/models")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIn("models", data)
        pairs = {(m["provider"], m["model"]) for m in data["models"]}
        self.assertIn(("openai", "gpt-4o"), pairs)
        self.assertIn(("gemini", "gemini-1.5-pro"), pairs)
        mock_refresh_model_cache.assert_called_once_with(provider=None)
        mock_get_cached_models.assert_called_once_with(provider=None)

    # --- /health/providers -----------------------------------------------
    @patch("app.api.routes.model_registry.provider_connectivity")
    def test_provider_health_all_reachable_is_200(self, mock_provider_connectivity):
        mock_provider_connectivity.return_value = [
            {
                "provider": "openai",
                "url": "https://api.openai.com/v1/models",
                "reachable": True,
                "http_status": 401,
                "error": None,
            },
            {
                "provider": "gemini",
                "url": "https://generativelanguage.googleapis.com/v1beta/models",
                "reachable": True,
                "http_status": 403,
                "error": None,
            },
        ]

        response = self.client.get("/health/providers")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["all_reachable"])
        self.assertEqual(len(payload["providers"]), 2)
        mock_provider_connectivity.assert_called_once_with(
            provider=None, timeout_seconds=5
        )

    @patch("app.api.routes.model_registry.provider_connectivity")
    def test_provider_health_unreachable_is_503(self, mock_provider_connectivity):
        mock_provider_connectivity.return_value = [
            {
                "provider": "openai",
                "url": "https://api.openai.com/v1/models",
                "reachable": True,
                "http_status": 401,
                "error": None,
            },
            {
                "provider": "gemini",
                "url": "https://generativelanguage.googleapis.com/v1beta/models",
                "reachable": False,
                "http_status": None,
                "error": "timed out",
            },
        ]

        response = self.client.get("/health/providers")
        self.assertEqual(response.status_code, 503)
        payload = response.get_json()
        self.assertFalse(payload["all_reachable"])

    @patch("app.api.routes.model_registry.provider_connectivity")
    def test_provider_health_invalid_provider_is_400(self, mock_provider_connectivity):
        mock_provider_connectivity.side_effect = ValueError(
            "Unsupported provider: bogus"
        )

        response = self.client.get("/health/providers?provider=bogus")
        self.assertEqual(response.status_code, 400)
        body = response.get_json()
        self.assertEqual(body["error"]["code"], "invalid_request")

    # --- /health/ready ---------------------------------------------------
    @patch("app.api.routes.model_registry.provider_connectivity")
    def test_readiness_health_all_reachable_is_200(self, mock_provider_connectivity):
        mock_provider_connectivity.return_value = [
            {
                "provider": "openai",
                "url": "https://api.openai.com/v1/models",
                "reachable": True,
                "http_status": 401,
                "error": None,
            },
            {
                "provider": "gemini",
                "url": "https://generativelanguage.googleapis.com/v1beta/models",
                "reachable": True,
                "http_status": 403,
                "error": None,
            },
        ]

        response = self.client.get("/health/ready")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ready"])
        self.assertEqual(sorted(payload["checked_providers"]), ["gemini", "openai"])
        mock_provider_connectivity.assert_called_once_with(
            provider=None, timeout_seconds=3
        )

    @patch("app.api.routes.model_registry.provider_connectivity")
    def test_readiness_health_unreachable_is_503(self, mock_provider_connectivity):
        mock_provider_connectivity.return_value = [
            {
                "provider": "openai",
                "url": "https://api.openai.com/v1/models",
                "reachable": True,
                "http_status": 401,
                "error": None,
            },
            {
                "provider": "gemini",
                "url": "https://generativelanguage.googleapis.com/v1beta/models",
                "reachable": False,
                "http_status": None,
                "error": "timed out",
            },
        ]

        response = self.client.get("/health/ready")
        self.assertEqual(response.status_code, 503)
        payload = response.get_json()
        self.assertFalse(payload["ready"])

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

    @patch.object(api_routes._llm_service, "generate", return_value="RAW BPMN JSON")
    def test_generate_accepts_new_openai_model_for_supported_provider(
        self, mock_generate
    ):
        response = self.client.post(
            "/generate",
            headers={"Authorization": "Bearer secret-token"},
            json={
                "user_text": "describe a process",
                "provider": "openai",
                "model": "gpt-5-mini",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"raw_response": "RAW BPMN JSON"})
        self.assertEqual(mock_generate.call_args.kwargs["model"], "gpt-5-mini")

    @patch("app.services.llm_service.genai")
    def test_generate_gemini_success(self, mock_genai):
        self._mock_gemini(mock_genai)
        response = self.client.post(
            "/generate",
            headers={"Authorization": "Bearer secret-token"},
            json={
                "user_text": "describe a process",
                "provider": "gemini",
                "model": "gemini-1.5-pro",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"raw_response": "RAW GEMINI JSON"})

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
    def test_generate_provider_error_is_500_upstream(self, mock_openai):
        mock_openai.return_value.chat.completions.create.side_effect = RuntimeError(
            "boom"
        )
        response = self.client.post(
            "/generate",
            headers={"Authorization": "Bearer secret-token"},
            json={"user_text": "x", "provider": "openai", "model": "gpt-4o"},
        )
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.get_json()["error"]["code"], "upstream_error")

    @patch("app.services.llm_service.genai")
    def test_generate_gemini_provider_error_is_500_upstream(self, mock_genai):
        # The Gemini provider must map a provider-side failure to the same
        # upstream_error 500 as OpenAI does (the OpenAI path is covered above;
        # this closes the second-provider asymmetry).
        mock_genai.GenerativeModel.return_value.generate_content.side_effect = (
            RuntimeError("boom")
        )
        response = self.client.post(
            "/generate",
            headers={"Authorization": "Bearer secret-token"},
            json={
                "user_text": "x",
                "provider": "gemini",
                "model": "gemini-1.5-pro",
            },
        )
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.get_json()["error"]["code"], "upstream_error")

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

    @patch.object(api_routes._llm_service, "generate", return_value="RAW BPMN JSON")
    def test_generate_defaults_to_zero_shot_strategy(self, mock_generate):
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
        self.assertEqual(
            mock_generate.call_args.kwargs["prompting_strategy"], "zero_shot"
        )

    def test_generate_invalid_prompting_strategy_is_400(self):
        response = self.client.post(
            "/generate",
            headers={"Authorization": "Bearer secret-token"},
            json={
                "user_text": "describe a process",
                "provider": "openai",
                "model": "gpt-4o",
                "prompting_strategy": "invalid",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"]["code"], "invalid_request")


if __name__ == "__main__":
    unittest.main()
