import unittest
from config import config
from app import run_openai

class TestT2PService(unittest.TestCase):
    def setUp(self):
        self.api_key = config.get_config().API_KEY
        self.system_prompt = config.get_config().SYSTEM_PROMPT
        self.strategies = ['few_shot', 'zero_shot']
        self.llm_runner = run_openai

    def run_test_case(self, sentence, expected_keywords):
        for strategy in self.strategies:
            with self.subTest(strategy=strategy):
                result = self.llm_runner(
                    self.api_key,
                    self.system_prompt,
                    sentence,
                    strategy
                )
                result_lower = result.lower()

                for keyword in expected_keywords:
                    self.assertTrue(
                        keyword.lower() in result_lower,
                        msg=f"Keyword '{keyword}' not found in response:\n{result}"
                    )

                print(f"[OpenAI | {strategy}] AI Response:\n{result}\n")

    def test_linear_process(self):
        sentence = "The customer fills out the form, then a clerk checks the information, and finally the application is approved."
        expected_keywords = ["form", "check", "approve"]
        self.run_test_case(sentence, expected_keywords)

    def test_conditional_process(self):
        sentence = "If the customer has a valid license, the product is activated. Otherwise, an error message is displayed."
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
        expected_keywords = [
            "loan", "credit", "approve", "reject", "inform"
        ]
        self.run_test_case(sentence, expected_keywords)


if __name__ == '__main__':
    unittest.main()
