"""Exercise adapter request/response handling with mocked HTTP; no paid inference."""
import json
import unittest
import httpx
from fastapi.testclient import TestClient
from backend.app import create_app
from backend.config import Settings
from backend.agent.azure_grok import AzureGrok
from backend.agent.llm_interface import InferenceError, Message, ToolDefinition

TOOL = ToolDefinition(name="compatibility_echo", description="Return a supplied value.",
                      parameters={"type": "object", "properties": {"value": {"type": "string"}},
                                  "required": ["value"], "additionalProperties": False})

def response(calls=None, content=None, finish="tool_calls"):
    """Build an Azure-shaped response fixture for adapter tests."""
    return {"choices": [{"message": {"role": "assistant", "content": content,
                                     "tool_calls": calls}, "finish_reason": finish}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}

def call(arguments='{"value":"phase1"}', name="compatibility_echo"):
    """Build a model function-call fixture without contacting Azure."""
    return {"id": "call-1", "type": "function", "function": {"name": name, "arguments": arguments}}

class AdapterTests(unittest.IsolatedAsyncioTestCase):
    def adapter(self, handler):
        """Create an adapter with synthetic settings and a mocked HTTP transport."""
        return AzureGrok(Settings(chat_url="https://resource.example/openai/v1/chat/completions",
                                  deployment="actual-deployment", api_key="sentinel-secret"),
                         transport=httpx.MockTransport(handler))

    async def test_tool_round_trip_and_usage(self):
        """Verify tool-call serialization, returned tool results and reported token usage."""
        requests = []
        def handler(request):
            """Check serialized requests and return the next mocked round-trip response."""
            data = json.loads(request.content)
            requests.append(data)
            self.assertEqual(request.headers["api-key"], "sentinel-secret")
            self.assertEqual(data["model"], "actual-deployment")
            if len(requests) == 1:
                self.assertEqual(data["tools"][0]["function"]["name"], TOOL.name)
                return httpx.Response(200, json=response([call()]))
            self.assertEqual(data["messages"][-1]["tool_call_id"], "call-1")
            self.assertEqual(data["messages"][-2]["tool_calls"][0]["function"]["arguments"],
                             '{"value": "phase1"}')
            return httpx.Response(200, json=response(content="confirmed", finish="stop"))
        adapter = self.adapter(handler)
        messages = [Message(role="user", content="Use the tool.")]
        first = await adapter.complete(messages, [TOOL])
        self.assertEqual(first.message.tool_calls[0].arguments, {"value": "phase1"})
        second = await adapter.complete(messages + [first.message, Message(
            role="tool", tool_call_id="call-1", content='{"value":"phase1"}')], [])
        self.assertEqual(second.message.content, "confirmed")
        self.assertEqual(second.usage.total_tokens, 15)
        self.assertGreaterEqual(second.latency_ms, 0)

    async def test_http_errors_are_safe_and_not_retried(self):
        """Verify provider errors expose safe codes and do not trigger automatic retries."""
        for status in (401, 403, 429, 500, 302):
            seen = []
            def handler(request):
                """Count attempted requests and return the chosen HTTP error or redirect."""
                seen.append(request)
                return httpx.Response(status, text="sentinel-secret", headers={"Location": "https://elsewhere.example"})
            with self.subTest(status=status), self.assertRaises(InferenceError) as caught:
                await self.adapter(handler).complete([Message(role="user", content="hello")], [])
            self.assertEqual(caught.exception.code, f"provider_http_{status}")
            self.assertNotIn("sentinel-secret", str(caught.exception))
            self.assertEqual(caught.exception.retryable, status in (429, 500))
            self.assertEqual(len(seen), 1)

    async def test_transport_failures(self):
        """Verify timeout and connection failures become safe, retryable errors."""
        for exception, code in ((httpx.ReadTimeout, "provider_timeout"),
                                (httpx.ConnectError, "provider_connection_error")):
            def handler(request):
                """Raise a controlled transport failure to test the safe error boundary."""
                raise exception("sentinel-secret", request=request)
            with self.subTest(code=code), self.assertRaises(InferenceError) as caught:
                await self.adapter(handler).complete([Message(role="user", content="x")], [])
            self.assertEqual(caught.exception.code, code)
            self.assertTrue(caught.exception.retryable)

    async def test_malformed_and_unknown_tool_responses(self):
        """Reject malformed JSON, duplicate calls, unknown tools and incomplete responses."""
        cases = [{}, response([call("not-json")]), response([call("[]")]),
                 response([call(name="unavailable")]), response([call('{"value":NaN}')]),
                 response([call(), call()]), response(content="partial", finish="length"),
                 response(None, None, "stop")]
        for body in cases:
            with self.subTest(body=body), self.assertRaises(InferenceError):
                await self.adapter(lambda request: httpx.Response(200, json=body)).complete(
                    [Message(role="user", content="x")], [TOOL])

    async def test_invalid_usage_shape_is_a_safe_error(self):
        """Reject non-object usage metadata through the safe provider-error boundary."""
        body = response(content="ok", finish="stop")
        body["usage"] = ["sentinel-sensitive-provider-content"]
        with self.assertRaises(InferenceError) as caught:
            await self.adapter(lambda request: httpx.Response(200, json=body)).complete(
                [Message(role="user", content="x")], [])
        self.assertEqual(caught.exception.code, "invalid_provider_response")

    async def test_missing_usage_is_unknown(self):
        """Keep absent token counts unknown instead of claiming zero usage."""
        body = response(content="ok", finish="stop")
        body.pop("usage")
        result = await self.adapter(lambda request: httpx.Response(200, json=body)).complete(
            [Message(role="user", content="x")], [])
        self.assertIsNone(result.usage.total_tokens)

    async def test_invalid_requests_do_not_send(self):
        """Reject empty conversations and duplicate tool names before network access."""
        def handler(request):
            """Fail immediately if invalid input reaches the HTTP transport."""
            self.fail("Invalid request reached transport.")
        for messages, tools in (([], []), ([Message(role="user", content="x")], [TOOL, TOOL])):
            with self.assertRaises(ValueError):
                await self.adapter(handler).complete(messages, tools)

class AppTests(unittest.TestCase):
    def test_health_without_credentials_is_honest(self):
        """Confirm the health response does not claim configured or verified inference."""
        with TestClient(create_app(Settings.from_env({}))) as client:
            result = client.get("/health")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json(), {
            "status": "ok", "phase": 4, "llm_mode": "live",
            "live_configured": False, "live_verified": False})
