import unittest
from app import create_app
from config import TestingConfig
import logging


class Test_App(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestingConfig)
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()

    def tearDown(self):
        self.app_context.pop()

    def test_echo_endpoint(self):
        response = self.client.get("/_/_/echo")
        data = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertIn("success", data)
        self.assertTrue(data["success"])


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    unittest.main()
