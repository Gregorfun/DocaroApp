import unittest

from core.llm_assist import build_ollama_prompt, parse_llm_suggestion


class LLMAssistTests(unittest.TestCase):
    def test_parse_valid_json(self):
        payload = """
        {
          "supplier": "Muster GmbH",
          "supplier_confidence": 0.91,
          "doc_type": "RECHNUNG",
          "doc_type_confidence": 0.88,
          "date_iso": "2026-02-27",
          "date_confidence": 0.90,
          "doc_number": "RE-12345",
          "doc_number_confidence": 0.87
        }
        """
        suggestion = parse_llm_suggestion(payload)
        self.assertEqual(suggestion.error, "")
        self.assertEqual(suggestion.supplier, "Muster GmbH")
        self.assertEqual(suggestion.doc_type, "RECHNUNG")
        self.assertEqual(suggestion.date_iso, "2026-02-27")
        self.assertEqual(suggestion.doc_number, "RE-12345")
        self.assertGreaterEqual(suggestion.supplier_confidence, 0.9)

    def test_parse_code_block_json(self):
        payload = """```json
        {"supplier":"A GmbH","supplier_confidence":0.8}
        ```"""
        suggestion = parse_llm_suggestion(payload)
        self.assertEqual(suggestion.error, "")
        self.assertEqual(suggestion.supplier, "A GmbH")

    def test_parse_invalid_json_returns_error(self):
        suggestion = parse_llm_suggestion("kein json")
        self.assertNotEqual(suggestion.error, "")

    def test_prompt_contains_current_values(self):
        prompt = build_ollama_prompt(
            text="Dokumenttext",
            current_supplier="Unbekannt",
            current_doc_type="SONSTIGES",
            current_date="",
            current_doc_number="ohneNr_abc",
        )
        self.assertIn("Dokumenttext", prompt)
        self.assertIn("SONSTIGES", prompt)


if __name__ == "__main__":
    unittest.main()
