import json
import os
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Import app first to avoid config/app circular import when tests are executed
# directly with unittest module paths.
from app import create_app  # noqa: F401
from config import get_config
from app.services.llm_service import LLMService


RUN_LLM_TESTS = os.getenv("RUN_LLM_TESTS", "false").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}


@unittest.skipUnless(
    RUN_LLM_TESTS,
    "LLM tests are disabled by default. Set RUN_LLM_TESTS=true for local runs.",
)
class TestMockedProcesses(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        config_instance = get_config()()
        cls.system_prompt = config_instance.SYSTEM_PROMPT
        cls.openai_api_key = config_instance.OPENAI_API_KEY
        cls.gemini_api_key = config_instance.GEMINI_API_KEY
        cls.process_files = sorted(Path("tests/process_texts").glob("*.txt"))

    def setUp(self):
        self.service = LLMService()

    def _few_shot_step_payloads(self):
        return [
            {
                "process_context": (
                    "Customer requests handling flow with start, task execution, and end."
                )
            },
            {"events": [{"id": "startEvent1", "type": "startEvent", "name": "Start"}]},
            {"tasks": [{"id": "task1", "type": "userTask", "name": "Handle request"}]},
            {"gateways": []},
            {"events": [{"id": "endEvent1", "type": "endEvent", "name": "End"}]},
            {
                "flows": [
                    {
                        "id": "flow1",
                        "type": "sequenceFlow",
                        "source": "startEvent1",
                        "target": "task1",
                    },
                    {
                        "id": "flow2",
                        "type": "sequenceFlow",
                        "source": "task1",
                        "target": "endEvent1",
                    },
                ]
            },
            {
                "events": [
                    {"id": "startEvent1", "type": "startEvent", "name": "Start"},
                    {"id": "endEvent1", "type": "endEvent", "name": "End"},
                ],
                "tasks": [{"id": "task1", "type": "userTask", "name": "Handle request"}],
                "gateways": [],
                "flows": [
                    {
                        "id": "flow1",
                        "type": "sequenceFlow",
                        "source": "startEvent1",
                        "target": "task1",
                    },
                    {
                        "id": "flow2",
                        "type": "sequenceFlow",
                        "source": "task1",
                        "target": "endEvent1",
                    },
                ],
            },
        ]

    @patch("app.services.llm_service.ModelValidator.validate_model", return_value=[])
    @patch("app.services.llm_service.OpenAI")
    def test_openai_few_shot_with_mocked_api(self, mock_openai, _mock_validate):
        for process_file in self.process_files:
            step_payloads = self._few_shot_step_payloads()
            mock_openai.return_value.chat.completions.create.side_effect = [
                MagicMock(choices=[MagicMock(message=MagicMock(content=json.dumps(payload)))])
                for payload in step_payloads
            ]

            result = self.service.call_openai(
                api_key=self.openai_api_key,
                system_prompt=self.system_prompt,
                user_text=process_file.read_text(encoding="utf-8"),
                prompting_strategy="few_shot",
                model="gpt-5-mini",
            )
            parsed = json.loads(result)
            self.assertIn("events", parsed)
            self.assertIn("tasks", parsed)
            self.assertIn("flows", parsed)

        mock_openai.assert_called_with(api_key=self.openai_api_key)

    @patch("app.services.llm_service.OpenAI")
    def test_openai_zero_shot_with_mocked_api(self, mock_openai):
        mock_openai.return_value.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content='{"result": "ok"}'))]
        )

        for process_file in self.process_files:
            result = self.service.call_openai(
                api_key=self.openai_api_key,
                system_prompt=self.system_prompt,
                user_text=process_file.read_text(encoding="utf-8"),
                prompting_strategy="zero_shot",
                model="gpt-5-mini",
            )
            self.assertTrue(result)

        mock_openai.assert_called_with(api_key=self.openai_api_key)

    @patch("app.services.llm_service.ModelValidator.validate_model", return_value=[])
    @patch("app.services.llm_service.genai")
    def test_gemini_few_shot_with_mocked_api(self, mock_genai, _mock_validate):
        mock_model = MagicMock()
        mock_genai.GenerativeModel.return_value = mock_model

        for process_file in self.process_files:
            step_payloads = self._few_shot_step_payloads()
            mock_model.generate_content.side_effect = [
                MagicMock(text=json.dumps(payload)) for payload in step_payloads
            ]

            result = self.service.call_gemini(
                api_key=self.gemini_api_key,
                system_prompt=self.system_prompt,
                user_text=process_file.read_text(encoding="utf-8"),
                prompting_strategy="few_shot",
                model="gemini-2.0-flash",
            )
            parsed = json.loads(result)
            self.assertIn("events", parsed)
            self.assertIn("tasks", parsed)
            self.assertIn("flows", parsed)

        mock_genai.configure.assert_called_with(api_key=self.gemini_api_key)

    @patch("app.services.llm_service.genai")
    def test_gemini_zero_shot_with_mocked_api(self, mock_genai):
        mock_model = MagicMock()
        mock_model.generate_content.return_value = MagicMock(text='{"result": "ok"}')
        mock_genai.GenerativeModel.return_value = mock_model

        for process_file in self.process_files:
            result = self.service.call_gemini(
                api_key=self.gemini_api_key,
                system_prompt=self.system_prompt,
                user_text=process_file.read_text(encoding="utf-8"),
                prompting_strategy="zero_shot",
                model="gemini-2.0-flash",
            )
            self.assertTrue(result)

        mock_genai.configure.assert_called_with(api_key=self.gemini_api_key)


if __name__ == "__main__":
    unittest.main()
