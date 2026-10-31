"""Verify safe configuration and the shared inference input contracts."""
import unittest
from backend.config import Settings, ConfigurationError
from backend.agent.llm_interface import Message, ToolDefinition

class ConfigurationTests(unittest.TestCase):
    def test_defaults_and_missing_credentials(self):
        """Verify LIVE defaults and clear failure when required Azure settings are absent."""
        settings = Settings.from_env({})
        self.assertEqual(settings.mode, "live")
        self.assertEqual(len(settings.missing_credentials), 3)
        with self.assertRaises(ConfigurationError):
            settings.require_live()

    def test_configuration_repr_hides_secrets(self):
        """Confirm configuration representations omit the API key and endpoint."""
        settings = Settings.from_env({
            "AZURE_GROK_CHAT_URL": "https://resource.example/openai/v1/chat/completions",
            "AZURE_GROK_DEPLOYMENT": "deployment",
            "AZURE_GROK_API_KEY": "sentinel-secret",
        })
        settings.require_live()
        self.assertNotIn("sentinel-secret", repr(settings))
        self.assertNotIn("resource.example", repr(settings))

    def test_invalid_modes_and_timeouts(self):
        """Reject unimplemented inference modes and invalid request timeouts."""
        for env in ({"LLM_MODE": "demo"}, {"LLM_MODE": "invalid"},
                    *({"LLM_TIMEOUT_SECONDS": value} for value in ("0", "-1", "nan", "inf", "abc", "121"))):
            with self.subTest(env=env), self.assertRaises(ConfigurationError):
                Settings.from_env(env)

    def test_unsafe_urls(self):
        """Reject non-HTTPS endpoints and URLs containing embedded credentials or queries."""
        for url in ("http://example.com/chat/completions",
                    "https://key@example.com/chat/completions",
                    "https://example.com/chat/completions?key=secret",
                    "https://example.com/not-completions"):
            with self.subTest(url=url), self.assertRaises(ConfigurationError):
                Settings.from_env({"AZURE_GROK_CHAT_URL": url})

    def test_message_and_tool_contracts(self):
        """Validate message-role relationships and object-shaped tool definitions."""
        Message(role="tool", content="{}", tool_call_id="call-1")
        with self.assertRaises(ValueError):
            Message(role="tool", content="{}")
        with self.assertRaises(ValueError):
            Message(role="user", content="hello", tool_call_id="call-1")
        with self.assertRaises(ValueError):
            ToolDefinition(name="bad name", description="x", parameters={"type": "object"})
        with self.assertRaises(ValueError):
            ToolDefinition(name="valid", description="x", parameters={"type": "array"})
