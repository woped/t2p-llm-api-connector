import unittest
from unittest.mock import patch, MagicMock
from app import create_app
from config import TestingConfig
import logging


class Test_App(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestingConfig)
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()
        
        self.default_payload = {
            'api_key': 'test_api_key',
            'system_prompt': 'Du bist ein BPMN Generator.',
            'user_text': 'Ein Kunde bestellt ein Produkt.'
        }

    def tearDown(self):
        self.app_context.pop()

    def mock_openai_response(self, mock_openai):
        mock_choice = MagicMock()
        mock_choice.message.content = "Test response"

        mock_completion = MagicMock()
        mock_completion.choices = [mock_choice]

        mock_openai.return_value.chat.completions.create.return_value = mock_completion

    def mock_gemini_response(self, mock_genai):
        mock_response = MagicMock()
        mock_response.text = "Test Gemini response"
        
        mock_model = MagicMock()
        mock_model.generate_content.return_value = mock_response
        
        mock_genai.GenerativeModel.return_value = mock_model

    @patch('app.services.llm_service.OpenAI')
    def test_call_openai_few_shot(self, mock_openai):
        self.mock_openai_response(mock_openai)

        payload = {**self.default_payload, 'prompting_strategy': 'few_shot'}
        response = self.client.post('/call_openai', json=payload)
        data = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertIn('message', data)
        self.assertEqual(data['message'], "Test response")

    @patch('app.services.llm_service.OpenAI')
    def test_call_openai_zero_shot(self, mock_openai):
        self.mock_openai_response(mock_openai)

        payload = {**self.default_payload, 'prompting_strategy': 'zero_shot'}
        response = self.client.post('/call_openai', json=payload)
        data = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertIn('message', data)
        self.assertEqual(data['message'], "Test response")

    @patch('app.services.llm_service.genai')
    def test_call_gemini_few_shot(self, mock_genai):
        self.mock_gemini_response(mock_genai)

        payload = {**self.default_payload, 'prompting_strategy': 'few_shot'}
        response = self.client.post('/call_gemini', json=payload)
        data = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertIn('message', data)
        self.assertEqual(data['message'], "Test Gemini response")

    @patch('app.services.llm_service.genai')
    def test_call_gemini_zero_shot(self, mock_genai):
        self.mock_gemini_response(mock_genai)

        payload = {**self.default_payload, 'prompting_strategy': 'zero_shot'}
        response = self.client.post('/call_gemini', json=payload)
        data = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertIn('message', data)
        self.assertEqual(data['message'], "Test Gemini response")

    def test_echo_endpoint(self):
        response = self.client.get('/_/_/echo')
        data = response.get_json()
        
        self.assertEqual(response.status_code, 200)
        self.assertIn('success', data)
        self.assertTrue(data['success'])


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    unittest.main()
