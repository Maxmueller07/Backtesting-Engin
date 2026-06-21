import os
import unittest
from unittest.mock import patch

import ai_rule_builder


class AiRuleBuilderProviderTest(unittest.TestCase):
    def test_openai_provider_uses_openai_key(self):
        env = {
            "RULE_BUILDER_PROVIDER": "openai",
            "OPENAI_API_KEY": "openai-test-key",
            "RULE_BUILDER_MODEL": "gpt-test",
        }

        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(ai_rule_builder._normalized_provider(), "openai")
            self.assertEqual(ai_rule_builder._provider_api_key(), "openai-test-key")
            self.assertEqual(ai_rule_builder._provider_model(), "gpt-test")
            self.assertTrue(ai_rule_builder._has_llm_key())

    def test_gemini_provider_uses_google_key(self):
        env = {
            "RULE_BUILDER_PROVIDER": "gemini",
            "GOOGLE_API_KEY": "gemini-test-key",
            "RULE_BUILDER_MODEL": "gemini-test",
        }

        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(ai_rule_builder._normalized_provider(), "gemini")
            self.assertEqual(ai_rule_builder._provider_api_key(), "gemini-test-key")
            self.assertEqual(ai_rule_builder._provider_model(), "gemini-test")
            self.assertTrue(ai_rule_builder._has_llm_key())

    def test_gemini_provider_can_use_rule_builder_key(self):
        env = {
            "RULE_BUILDER_PROVIDER": "google",
            "RULE_BUILDER_API_KEY": "shared-rule-builder-key",
        }

        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(ai_rule_builder._normalized_provider(), "gemini")
            self.assertEqual(ai_rule_builder._provider_api_key(), "shared-rule-builder-key")
            self.assertTrue(ai_rule_builder._has_llm_key())

    def test_missing_gemini_key_message_mentions_google_key(self):
        with patch.dict(os.environ, {"RULE_BUILDER_PROVIDER": "gemini"}, clear=True):
            self.assertFalse(ai_rule_builder._has_llm_key())
            self.assertIn("GOOGLE_API_KEY", ai_rule_builder._missing_key_message())

    def test_parse_json_response_accepts_gemini_content_blocks(self):
        response = [
            {
                "type": "text",
                "text": '{"id":"rule_test","name":"Test"}',
            }
        ]

        payload = ai_rule_builder._parse_json_response(response)

        self.assertEqual(payload["id"], "rule_test")
        self.assertEqual(payload["name"], "Test")

    def test_parse_json_response_accepts_markdown_wrapped_content_blocks(self):
        response = [
            {
                "type": "text",
                "text": '```json\n{"id":"rule_test","name":"Test"}\n```',
            }
        ]

        payload = ai_rule_builder._parse_json_response(response)

        self.assertEqual(payload["id"], "rule_test")
        self.assertEqual(payload["name"], "Test")


if __name__ == "__main__":
    unittest.main()
