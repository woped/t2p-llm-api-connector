import unittest
from config import settings
from app import run_openai 

class Test_T2P_Service(unittest.TestCase):
    def setUp(self):
        self.api_key = settings.API_KEY
        self.system_prompt = settings.SYSTEM_PROMPT

    # Testet, ob typische Prozessschritte in einem bedingten Ablauf korrekt enthalten sind
    def test_xml_process(self):
        sentence = "Ein Kunde gibt eine Bestellung auf. Danach prüft ein Mitarbeiter die Verfügbarkeit. Wenn die Artikel verfügbar sind, wird die Bestellung versendet. Andernfalls wird der Kunde informiert."
        result = run_openai(self.api_key, self.system_prompt, sentence)
        self.assertIn("Bestellung", result)
        self.assertIn("Verfügbarkeit", result)

    # Testet die Abbildung einer einfachen linearen Folge (3 Schritte)
    def test_linear_process(self):
        sentence = "Der Kunde füllt das Formular aus, dann prüft ein Sachbearbeiter die Angaben, anschließend wird der Antrag genehmigt."
        result = run_openai(self.api_key, self.system_prompt, sentence)
        self.assertIn("Formular", result)
        self.assertIn("Sachbearbeiter", result)

    # Testet die Umsetzung einer Wenn-Dann-Logik mit Alternativpfad
    def test_conditional_process(self):
        sentence = "Wenn der Kunde eine gültige Lizenz hat, wird das Produkt freigeschaltet. Andernfalls wird eine Fehlermeldung angezeigt."
        result = run_openai(self.api_key, self.system_prompt, sentence)
        self.assertIn("Lizenz", result)
        self.assertIn("Produkt", result)
        self.assertIn("Fehlermeldung", result)

    # Testet die Parallelisierung zweier Abläufe und deren Synchronisation
    def test_parallel_process(self):
        sentence = "Während der Drucker die Etiketten erstellt, wird das Paket verpackt. Danach werden beide zusammen versendet."
        result = run_openai(self.api_key, self.system_prompt, sentence)
        self.assertIn("Etiketten", result)
        self.assertIn("Paket", result)
        self.assertIn("Versenden", result)

if __name__ == '__main__':
    unittest.main()
