import unittest
from flask import Flask
from flask.testing import FlaskClient
from unittest.mock import patch
from app import app
import logging
from config import settings


class AppTestCase(unittest.TestCase):
    """
    Set up the test client
    """
    def setUp(self):
        self.app = app.test_client()

    """
    Test the call_openai endpoint with a mocked OpenAI client
    """
    def test_call_openai(self):
        with patch('openai.OpenAI') as mock_openai:
            mock_openai.return_value.chat.completions.create.return_value.choices[0].message.content.strip.return_value = "Test response"
            response = self.app.post('/call_openai', json={
                'api_key': 'your_api_key',
                'system_prompt': 'system_prompt',
                'user_text': 'user_text'
            })
            
            log = logging.getLogger("test_call_openai" )
            log.debug("response: %s", response) 
            data = response.get_json()
            self.assertEqual(response.status_code, 200)
            self.assertEqual(data['message'], 'Test response')
    
    
if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    logging.getLogger("test_call_openai").setLevel(logging.DEBUG)
    unittest.main()