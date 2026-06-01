import unittest
from unittest.mock import patch

from app.utils.prompt_builder import PromptBuilder


class TestPromptBuilder(unittest.TestCase):
    def test_unsupported_strategy_raises(self):
        # The strategy is caller-supplied (forwarded from /generate's
        # 'prompting_strategie' field), so an unknown value must be rejected
        # rather than silently producing an empty/garbage prompt.
        with self.assertRaises(ValueError):
            PromptBuilder().build_prompt("bogus_strategy", "describe a process")

    def test_zero_shot_embeds_user_input(self):
        prompt = PromptBuilder().build_prompt("zero_shot", "ship the order")
        self.assertIn("ship the order", prompt)

    def test_few_shot_embeds_user_input(self):
        prompt = PromptBuilder().build_prompt("few_shot", "ship the order")
        self.assertIn("ship the order", prompt)

    def test_template_load_failure_degrades_gracefully(self):
        # If the few-shot template file is missing or unreadable, the builder
        # must not crash on construction: it falls back to no examples and can
        # still build a (user-input-only) few-shot prompt.
        with patch("builtins.open", side_effect=OSError("missing file")):
            builder = PromptBuilder()

        self.assertEqual(builder.few_shot_templates, [])
        prompt = builder.build_prompt("few_shot", "ship the order")
        self.assertIn("ship the order", prompt)


if __name__ == "__main__":
    unittest.main()
