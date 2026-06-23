import unittest
from unittest.mock import patch, MagicMock

from app import create_app
from config import TestingConfig
from app.api import routes as api_routes


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
    def test_models_returns_registry(self):
        response = self.client.get("/models")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIn("models", data)
        pairs = {(m["provider"], m["model"]) for m in data["models"]}
        self.assertIn(("openai", "gpt-4o"), pairs)
        self.assertIn(("gemini", "gemini-1.5-pro"), pairs)

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
        self.assertEqual(mock_generate.call_args.kwargs["prompting_strategy"], "zero_shot")

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
