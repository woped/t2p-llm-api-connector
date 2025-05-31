import unittest
from config import settings
from app import run_openai

from config.settings import FEW_SHOT_TEMPLATES

class Test_T2P_Service(unittest.TestCase):
    def setUp(self):
        self.api_key = settings.API_KEY
        self.system_prompt = settings.SYSTEM_PROMPT

    def build_prompt(self, user_input):
        prompt = ""
        for example in FEW_SHOT_TEMPLATES:
            prompt += f"Description:\n{example['description']}\n\n"
            prompt += f"BPMN:\n{example['bpmn']}\n\n"
        prompt += f"Description:\n{user_input}\n\nBPMN:\n"
        return prompt

    def test_xml_process(self):
        sentence = (
            "A customer places an order. Then an employee checks the availability. "
            "If the items are available, the order is shipped. Otherwise, the customer is informed."
        )
        prompt = self.build_prompt(sentence)
        result = run_openai(self.api_key, self.system_prompt, prompt)
        self.assertIn("order", result.lower())
        self.assertIn("availability", result.lower())
        print("AI Response:", result)

    def test_linear_process(self):
        sentence = (
            "The customer fills out the form, then a clerk checks the information, "
            "and finally the application is approved."
        )
        prompt = self.build_prompt(sentence)
        result = run_openai(self.api_key, self.system_prompt, prompt)
        self.assertIn("form", result.lower())
        self.assertIn("check", result.lower())
        self.assertIn("approve", result.lower())
        print("AI Response:", result)

    def test_conditional_process(self):
        sentence = (
            "If the customer has a valid license, the product is activated. "
            "Otherwise, an error message is displayed."
        )
        prompt = self.build_prompt(sentence)
        result = run_openai(self.api_key, self.system_prompt, prompt)
        self.assertIn("license", result.lower())
        self.assertIn("product", result.lower())
        self.assertIn("error", result.lower())
        print("AI Response:", result)

    def test_parallel_process(self):
        sentence = (
            "While the printer creates the labels, the package is packed. "
            "Afterwards, both are shipped together."
        )
        prompt = self.build_prompt(sentence)
        result = run_openai(self.api_key, self.system_prompt, prompt)
        self.assertIn("label", result.lower())
        self.assertIn("package", result.lower())
        self.assertIn("ship", result.lower())
        print("AI Response:", result)

    def test_complex_loan_application_process(self):
        sentence = (
            "A customer submits a loan application online. "
            "First, a clerk checks the customer's creditworthiness. "
            "If the credit is sufficient, additional documents are requested. "
            "Once they are submitted, a loan manager approves the application. "
            "If the credit is insufficient, the application is rejected and the customer is informed."
        )
        prompt = self.build_prompt(sentence)
        result = run_openai(self.api_key, self.system_prompt, prompt)
        result_lower = result.lower()

        # Activities
        self.assertIn("loan application", result_lower)
        self.assertIn("credit", result_lower)
        self.assertIn("request", result_lower)
        self.assertIn("submitted", result_lower)
        self.assertIn("approved", result_lower)
        self.assertIn("rejected", result_lower)
        self.assertIn("informed", result_lower)

        # Roles/Organizational units
        self.assertIn("clerk", result_lower)
        self.assertIn("loan manager", result_lower)

        # Structure checks
        self.assertIn("start", result_lower)
        self.assertIn("end", result_lower)
        self.assertNotIn("error", result_lower)
        self.assertNotIn("invalid", result_lower)

        print("AI Response:", result)

if __name__ == '__main__':
    unittest.main()
