"""Azure Chat Completions adapter. No automatic retries or business decisions."""
import json
import time
import httpx
from pydantic import ValidationError
from backend.config import Settings
from backend.agent.llm_interface import (
    InferenceError, InferenceResult, Message, ToolCall, ToolDefinition, Usage,
)

def reject_constant(value: str) -> None:
    """Reject NaN and Infinity when decoding model-supplied JSON arguments."""
    raise ValueError("Non-finite JSON is invalid.")

class AzureGrok:
    """Translate the shared inference contract into Azure Chat Completions requests."""
    def __init__(self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None):
        """Require Azure settings and optionally accept a transport for isolated tests."""
        settings.require_live()
        self.settings = settings
        self.transport = transport

    async def complete(self, messages: list[Message],
                       tools: list[ToolDefinition]) -> InferenceResult:
        """Send one request and parse text/tool calls, usage and elapsed time.

        Raise InferenceError for provider failures or malformed responses. Calls are
        not retried and requested tools are not executed here. Business tools must
        still validate their complete argument schemas and permissions.
        """
        if not messages:
            raise ValueError("At least one message is required.")
        names = {tool.name for tool in tools}
        if len(names) != len(tools):
            raise ValueError("Tool names must be unique.")
        wire_messages = []
        # Azure expects tool arguments as JSON text; shared types use parsed dictionaries.
        for message in messages:
            item = {"role": message.role, "content": message.content}
            if message.tool_call_id:
                item["tool_call_id"] = message.tool_call_id
            if message.tool_calls:
                item["tool_calls"] = [
                    {"id": call.id, "type": "function", "function": {
                        "name": call.name, "arguments": json.dumps(call.arguments, allow_nan=False)}}
                    for call in message.tool_calls]
            wire_messages.append(item)
        payload = {"model": self.settings.deployment, "messages": wire_messages}
        if tools:
            payload["tools"] = [{"type": "function", "function": tool.model_dump()} for tool in tools]
            payload["tool_choice"] = "auto"
        started = time.perf_counter()
        try:
            # Redirects and proxy environment settings are disabled to limit accidental key forwarding.
            async with httpx.AsyncClient(
                timeout=self.settings.timeout_seconds, transport=self.transport,
                follow_redirects=False, trust_env=False,
            ) as client:
                response = await client.post(
                    self.settings.chat_url, json=payload,
                    headers={"api-key": self.settings.api_key},
                )
        except httpx.TimeoutException:
            # Suppress provider exception details because URLs/headers may contain secrets.
            raise InferenceError("provider_timeout", retryable=True) from None
        except httpx.RequestError:
            raise InferenceError("provider_connection_error", retryable=True) from None
        if response.status_code != 200:
            retry_after = None
            try:
                # Only a bounded duration is retained; never log provider headers or bodies.
                seconds = float(response.headers.get("Retry-After", ""))
                if 0 <= seconds <= 120:
                    retry_after = max(1, seconds)
            except ValueError:
                pass
            raise InferenceError(
                f"provider_http_{response.status_code}",
                retryable=response.status_code == 429 or response.status_code >= 500,
                retry_after_seconds=retry_after,
            )
        try:
            body = response.json()
            choice = body["choices"][0]
            finish = choice["finish_reason"]
            if finish not in {"stop", "tool_calls"}:
                raise InferenceError("incomplete_provider_response")
            raw = choice["message"]
            if raw["role"] != "assistant":
                raise ValueError("Expected assistant response.")
            calls = []
            for entry in raw.get("tool_calls") or []:
                if entry["type"] != "function" or entry["function"]["name"] not in names:
                    raise ValueError("Unexpected tool.")
                arguments = json.loads(entry["function"]["arguments"], parse_constant=reject_constant)
                if not isinstance(arguments, dict):
                    raise ValueError("Tool arguments must be an object.")
                calls.append(ToolCall(id=entry["id"], name=entry["function"]["name"], arguments=arguments))
            if len({call.id for call in calls}) != len(calls):
                raise ValueError("Duplicate tool-call IDs.")
            if (finish == "tool_calls") != bool(calls):
                raise ValueError("Inconsistent finish reason.")
            usage = body.get("usage")
            if usage is None:
                # Missing counts remain unknown through Usage defaults, not fabricated zeroes.
                usage = {}
            if not isinstance(usage, dict):
                raise ValueError("Usage must be an object.")
            return InferenceResult(
                message=Message(role="assistant", content=raw.get("content"), tool_calls=tuple(calls)),
                usage=Usage(input_tokens=usage.get("prompt_tokens"),
                            output_tokens=usage.get("completion_tokens"),
                            total_tokens=usage.get("total_tokens")),
                finish_reason=finish, latency_ms=(time.perf_counter() - started) * 1000,
            )
        except (KeyError, IndexError, TypeError, ValueError, ValidationError):
            # Keep malformed provider bodies out of application errors and saved test logs.
            raise InferenceError("invalid_provider_response") from None
