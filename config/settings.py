# config/settings.py
import json
import os

API_KEY = "API-Key"  # Dein API-Key

def load_test_case(filename):
    path = os.path.join(os.path.dirname(__file__), filename)
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)
