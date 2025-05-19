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
    
    
    """
    Test using a real test_case JSON input
    """
    def test_xml_process(self):
        
        setence="Ein Kunde gibt eine Bestellung auf. Danach prüft ein Mitarbeiter die Verfügbarkeit. Wenn die Artikel verfügbar sind, wird die Bestellung versendet. Andernfalls wird der Kunde informiert."
        
        response = self.app.post("/call_openai", json={
            "api_key": settings.API_KEY,
            "system_prompt": "Du bist ein Assistent, der aus Textbeschreibungen BPMN-Modelle im XML-Format (BPMN 2.0) erstellt. Gib ausschließlich das XML zurück.",
            "user_text": setence
        })

        self.assertEqual(response.status_code, 200)
        json_data = response.get_json()
        self.assertIn("message", json_data)
        self.assertTrue(len(json_data["message"].strip()) > 0)

        print("LLM Antwort:\n", json_data["message"])
    
    
    """
    Test: Einfache lineare Folge von Schritten
    """
    def test_linear_process(self):
       
        sentence = "Der Kunde füllt das Formular aus, dann prüft ein Sachbearbeiter die Angaben, anschließend wird der Antrag genehmigt."

        response = self.app.post('/call_openai', json={
            'api_key': settings.API_KEY,
            'system_prompt': settings.SYSTEM_PROMPT,
            'user_text': sentence
        })

        result = response.get_json()['message']
        self.assertIn("Formular", result)



    """
    Test: Bedingter Ablauf mit Wenn/Dann/Ansonsten
    """
    def test_conditional_process(self):
        sentence = "Wenn der Kunde eine gültige Lizenz hat, wird das Produkt freigeschaltet. Andernfalls wird eine Fehlermeldung angezeigt."

        response = self.app.post('/call_openai', json={
            'api_key': settings.API_KEY,
            'system_prompt': settings.SYSTEM_PROMPT,
            'user_text': sentence
        })

        result = response.get_json()['message']
        self.assertIn("Lizenz", result)
        self.assertIn("Produkt", result)
        self.assertIn("Fehlermeldung", result)

    """
    Test: Zwei Prozesse laufen gleichzeitig, synchronisieren danach
    """
    def test_parallel_process(self):
        sentence = "Während der Drucker die Etiketten erstellt, wird das Paket verpackt. Danach werden beide zusammen versendet."

        response = self.app.post('/call_openai', json={
            'api_key': settings.API_KEY,
            'system_prompt': settings.SYSTEM_PROMPT,
            'user_text': sentence
        })

        result = response.get_json()['message']
        self.assertIn("Etiketten", result)
        self.assertIn("Paket", result)


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    logging.getLogger("test_call_openai").setLevel(logging.DEBUG)
    unittest.main()