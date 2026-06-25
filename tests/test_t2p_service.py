import unittest
from unittest.mock import patch, MagicMock
import json
import os
import config
from app.services.llm_service import LLMService
from app.utils.prompt_builder import STRICT_JSON_REMINDER
from app.services.model_validator import ModelValidator


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
class TestT2PService(unittest.TestCase):
    def setUp(self):
        config_instance = config.get_config()()
        self.api_key = "test-api-key"  # Static test API key
        self.system_prompt = config_instance.SYSTEM_PROMPT
        self.strategies = ["few_shot", "zero_shot"]
        self.llm_service = LLMService()
        self.model_validator = ModelValidator()

    def create_mock_response(self, sentence, expected_keywords, strategy):
        """Create a realistic mock response that contains the expected keywords."""
        if strategy == "few_shot":
            mock_response = f"""
            Start Event: Customer initiates process with {sentence.split()[0] if sentence.split() else "request"}

            Tasks/Activities:
            """
        else:
            mock_response = f"BPMN Model for: {sentence}\n\nElements:\n"

        # Add expected keywords to the mock response
        for keyword in expected_keywords:
            mock_response += f"- Process step involving {keyword}\n"

        mock_response += "\nEnd Event: Process completed successfully"
        return mock_response

    @patch("app.services.llm_service.OpenAI")
    def run_test_case(self, sentence, expected_keywords, mock_openai):
        for strategy in self.strategies:
            with self.subTest(strategy=strategy):
                # Setup mock
                mock_response = self.create_mock_response(
                    sentence, expected_keywords, strategy
                )
                mock_choice = MagicMock()
                mock_choice.message.content = mock_response

                mock_completion = MagicMock()
                mock_completion.choices = [mock_choice]

                mock_openai.return_value.chat.completions.create.return_value = (
                    mock_completion
                )

                # Run test
                result = self.llm_service.call_openai(
                    self.api_key, self.system_prompt, sentence, strategy
                )
                result_lower = result.lower()

                for keyword in expected_keywords:
                    self.assertTrue(
                        keyword.lower() in result_lower,
                        msg=f"Keyword '{keyword}' not found in response:\n{result}",
                    )

                print(f"[OpenAI | {strategy}] AI Response:\n{result}\n")

    def test_linear_process(self):
        sentence = (
            "The customer fills out the form, then a clerk checks the information, "
            "and finally the application is approved."
        )
        expected_keywords = ["form", "check", "approve"]
        self.run_test_case(sentence, expected_keywords)

    def test_conditional_process(self):
        sentence = (
            "If the customer has a valid license, the product is activated. "
            "Otherwise, an error message is displayed."
        )
        expected_keywords = ["license", "product", "error"]
        self.run_test_case(sentence, expected_keywords)

    def test_parallel_process(self):
        sentence = "While the printer creates the labels, the package is packed. Afterwards, both are shipped together."
        expected_keywords = ["label", "package", "ship"]
        self.run_test_case(sentence, expected_keywords)

    def test_complex_loan_application_process(self):
        sentence = (
            "A customer submits a loan application online. "
            "First, a clerk checks the customer's creditworthiness. "
            "If the credit is sufficient, additional documents are requested. "
            "Once they are submitted, a loan manager approves the application. "
            "If the credit is insufficient, the application is rejected and the customer is informed."
        )
        expected_keywords = ["loan", "credit", "approve", "reject", "inform"]
        self.run_test_case(sentence, expected_keywords)

    def test_generate_unknown_provider_raises(self):
        # generate() is the provider-agnostic entry point; a provider with no
        # dispatch mapping must raise rather than fail obscurely later. This
        # guard protects internal/direct callers that bypass the route's
        # registry validation.
        with self.assertRaises(ValueError):
            self.llm_service.generate(
                api_key=self.api_key,
                provider="bogus",
                model="whatever",
                user_text="x",
                system_prompt=self.system_prompt,
            )

    @patch("app.services.llm_service.OpenAI")
    def test_few_shot_openai_runs_multi_call_orchestration(self, mock_openai):
        responses = [
            {"events": [{"id": "startEvent1", "type": "startEvent", "name": "start"}]},
            {"tasks": [{"id": "task1", "type": "userTask", "name": "inspect bike"}]},
            {"gateways": []},
            {"events": [{"id": "endEvent1", "type": "endEvent", "name": "end"}]},
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
                    {"id": "startEvent1", "type": "startEvent", "name": "start"},
                    {"id": "endEvent1", "type": "endEvent", "name": "end"},
                ],
                "tasks": [
                    {"id": "task1", "type": "userTask", "name": "inspect bike"}
                ],
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

        mock_openai.return_value.chat.completions.create.side_effect = [
            MagicMock(choices=[MagicMock(message=MagicMock(content=json.dumps(r)))])
            for r in responses
        ]

        result = self.llm_service.call_openai(
            self.api_key,
            self.system_prompt,
            "A mechanic inspects a bike and then completes the repair.",
            "few_shot",
        )

        parsed = json.loads(result)
        self.assertIn("events", parsed)
        self.assertIn("tasks", parsed)
        self.assertIn("flows", parsed)
        self.assertGreaterEqual(
            mock_openai.return_value.chat.completions.create.call_count, 6
        )
        first_call_messages = (
            mock_openai.return_value.chat.completions.create.call_args_list[0].kwargs[
                "messages"
            ]
        )
        self.assertIn(STRICT_JSON_REMINDER, first_call_messages[1]["content"])

    @patch("app.services.llm_service.OpenAI")
    def test_few_shot_retries_when_step_returns_non_json(self, mock_openai):
        responses = [
            {"events": [{"id": "startEvent1", "type": "startEvent", "name": "start"}]},
            {"tasks": [{"id": "task1", "type": "userTask", "name": "inspect bike"}]},
            {"gateways": []},
            {"events": [{"id": "endEvent1", "type": "endEvent", "name": "end"}]},
            "I cannot comply with that format.",
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
                    {"id": "startEvent1", "type": "startEvent", "name": "start"},
                    {"id": "endEvent1", "type": "endEvent", "name": "end"},
                ],
                "tasks": [
                    {"id": "task1", "type": "userTask", "name": "inspect bike"}
                ],
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

        side_effect = []
        for item in responses:
            if isinstance(item, str):
                content = item
            else:
                content = json.dumps(item)
            side_effect.append(
                MagicMock(choices=[MagicMock(message=MagicMock(content=content))])
            )

        mock_openai.return_value.chat.completions.create.side_effect = side_effect

        result = self.llm_service.call_openai(
            self.api_key,
            self.system_prompt,
            "A mechanic inspects a bike and then completes the repair.",
            "few_shot",
        )

        parsed = json.loads(result)
        self.assertIn("flows", parsed)
        self.assertGreaterEqual(
            mock_openai.return_value.chat.completions.create.call_count, 7
        )

    def test_validator_rejects_fake_split_gateway_and_missing_loop(self):
        model = {
            "events": [
                {"id": "startEvent1", "type": "startEvent", "name": "start"},
                {"id": "endEvent1", "type": "endEvent", "name": "end"},
            ],
            "tasks": [
                {"id": "task1", "type": "userTask", "name": "test bike"},
                {"id": "task2", "type": "userTask", "name": "correct defect"},
            ],
            "gateways": [
                {
                    "id": "gateway1",
                    "type": "exclusiveGateway",
                    "name": "defect remains?",
                    "role": "split",
                    "branch_count": 2,
                    "branch_cues": ["defect remains", "passes test"],
                    "paired_gateway_id": "",
                }
            ],
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
                    "target": "gateway1",
                },
                {
                    "id": "flow3",
                    "type": "sequenceFlow",
                    "source": "gateway1",
                    "target": "endEvent1",
                },
            ],
        }

        issues = self.model_validator.validate_model(
            model,
            "If a defect remains, the bike returns for correction and is retested until it passes.",
        )

        self.assertTrue(any("fewer than 2 outgoing flows" in issue for issue in issues))
        self.assertTrue(any("no backward/loop flow detected" in issue for issue in issues))

    def test_validator_does_not_treat_pickup_return_as_loop(self):
        model = {
            "events": [
                {"id": "startEvent1", "type": "startEvent", "name": "start"},
                {"id": "endEvent1", "type": "endEvent", "name": "end"},
            ],
            "tasks": [
                {"id": "task1", "type": "userTask", "name": "take deposit"},
                {"id": "task2", "type": "userTask", "name": "repair bike"},
                {"id": "task3", "type": "userTask", "name": "pickup and pay"},
            ],
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
                    "target": "task2",
                },
                {
                    "id": "flow3",
                    "type": "sequenceFlow",
                    "source": "task2",
                    "target": "task3",
                },
                {
                    "id": "flow4",
                    "type": "sequenceFlow",
                    "source": "task3",
                    "target": "endEvent1",
                },
            ],
        }

        issues = self.model_validator.validate_model(
            model,
            "Customers return on the advised date to pay and pick up the repaired bike.",
        )

        self.assertFalse(
            any("Loop language found" in issue for issue in issues),
            msg=f"Unexpected loop issue(s): {issues}",
        )


if __name__ == "__main__":
    unittest.main()
