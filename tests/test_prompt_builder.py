import unittest
from unittest.mock import patch

from app.utils.prompt_builder import PromptBuilder


class TestPromptBuilder(unittest.TestCase):
    def test_unsupported_strategy_raises(self):
        # The strategy is caller-supplied (forwarded from /generate's
        # 'prompting_strategy' field), so an unknown value must be rejected
        # rather than silently producing an empty/garbage prompt.
        with self.assertRaises(ValueError):
            PromptBuilder().build_prompt("bogus_strategy", "describe a process")

    def test_zero_shot_embeds_user_input(self):
        prompt = PromptBuilder().build_prompt("zero_shot", "ship the order")
        self.assertIn("ship the order", prompt)
        self.assertIn("Please generate a BPMN model", prompt)

    def test_few_shot_embeds_user_input(self):
        prompt = PromptBuilder().build_prompt("few_shot", "ship the order")
        self.assertIn("ship the order", prompt)
        self.assertIn("stepwise few-shot method", prompt.lower())

    def test_prompt_pack_load_failure_degrades_gracefully(self):
        # If all prompt-pack files are unreadable, the builder must not crash
        # and few_shot falls back to a zero-shot style prompt.
        with patch("pathlib.Path.read_text", side_effect=OSError("missing file")):
            builder = PromptBuilder()

        self.assertTrue(builder.few_shot_prompt_pack)
        self.assertTrue(all(v == "" for v in builder.few_shot_prompt_pack.values()))
        prompt = builder.build_prompt("few_shot", "ship the order")
        self.assertIn("ship the order", prompt)
        self.assertIn("Please generate a BPMN model", prompt)

    def test_zero_shot_template_load_failure_degrades_gracefully(self):
        with patch("pathlib.Path.read_text", side_effect=OSError("missing file")):
            builder = PromptBuilder()

        self.assertEqual(builder.zero_shot_prompt_template, "")
        prompt = builder.build_prompt("zero_shot", "ship the order")
        self.assertIn("ship the order", prompt)
        self.assertIn("Please generate a BPMN model", prompt)


if __name__ == "__main__":
    unittest.main()
