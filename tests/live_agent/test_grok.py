"""Opt-in-by-configuration real inference check, not an autonomy evaluation."""
import json
import os
import secrets
import unittest
from backend.config import Settings
from backend.agent.azure_grok import AzureGrok
from backend.agent.llm_interface import Message
from tests.integration.test_adapter import TOOL

class LiveGrokTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_tool_call_round_trip(self):
        """With explicit opt-in, verify actual Grok selects a tool and consumes its result."""
        self.safe_trace = []
        if os.environ.get("AUDIT_RUN_LIVE_TESTS") != "1":
            self.skipTest("Real inference not requested; use scripts.run_tests --live.")
        settings = Settings.from_env()
        if settings.missing_credentials:
            self.skipTest("Missing configuration: " + ", ".join(settings.missing_credentials))
        token = "phase1-" + secrets.token_hex(4)
        adapter = AzureGrok(settings)
        messages = [Message(role="user", content=(
            f"Call compatibility_echo exactly once with value {token}. "
            "After receiving its result, reply with only the returned value."))]
        first = await adapter.complete(messages, [TOOL])
        self.safe_trace.append({
            "event": "compatibility_tool_selection",
            "tool_calls": [call.model_dump() for call in first.message.tool_calls
                           if call.name == TOOL.name and call.arguments == {"value": token}],
            "usage": first.usage.model_dump(), "latency_ms": first.latency_ms,
            "finish_reason": first.finish_reason,
        })
        self.assertEqual(len(first.message.tool_calls), 1)
        selected = first.message.tool_calls[0]
        self.assertEqual(selected.name, TOOL.name)
        self.assertEqual(selected.arguments, {"value": token})
        # Local harmless execution: this is not one of the future audit business tools.
        output = json.dumps({"value": selected.arguments["value"]})
        second = await adapter.complete(messages + [first.message, Message(
            role="tool", tool_call_id=selected.id, content=output)], [])
        self.assertEqual(second.message.content.strip(), token)
        self.assertFalse(second.message.tool_calls)
        self.safe_trace.append({"event": "compatibility_round_trip_completed",
                                "usage": second.usage.model_dump(),
                                "latency_ms": second.latency_ms,
                                "outcome": "Exact echo confirmed"})
