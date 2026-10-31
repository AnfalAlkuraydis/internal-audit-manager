"""Small provider-independent boundary; no business operations are executed here."""
from typing import Any, Literal, Protocol
from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

class StrictModel(BaseModel):
    """Reject unexpected fields and prevent reassignment of validated attributes."""
    model_config = ConfigDict(extra="forbid", frozen=True)

class ToolCall(StrictModel):
    """A model-requested function call, not permission to execute that function."""
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    arguments: dict[str, JsonValue]

class Message(StrictModel):
    """Represent a conversation entry or a result linked to a prior tool call."""
    role: Literal["system", "user", "assistant", "tool"]
    content: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None

    @model_validator(mode="after")
    def valid_message(self) -> "Message":
        """Enforce which roles may request tools or supply tool results."""
        if self.role == "tool" and (not self.tool_call_id or self.content is None):
            raise ValueError("Tool messages require content and tool_call_id.")
        if self.role != "tool" and self.tool_call_id is not None:
            raise ValueError("Only tool messages can contain tool_call_id.")
        if self.tool_calls and self.role != "assistant":
            raise ValueError("Only assistant messages can contain tool calls.")
        if self.content is None and not self.tool_calls:
            raise ValueError("A message requires content or tool calls.")
        return self

class ToolDefinition(StrictModel):
    """Describe an available function and its JSON object argument schema."""
    name: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    description: str = Field(min_length=1)
    parameters: dict[str, Any]

    @model_validator(mode="after")
    def object_schema(self) -> "ToolDefinition":
        """Require object-shaped parameters at the shared interface boundary."""
        if self.parameters.get("type") != "object":
            raise ValueError("Tool parameters must describe an object.")
        return self

class Usage(StrictModel):
    """Provider token counts; None means unknown rather than zero."""
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)

class InferenceResult(StrictModel):
    """Return the parsed assistant response with usage, latency and execution mode."""
    message: Message
    usage: Usage
    finish_reason: str
    latency_ms: float = Field(ge=0)
    mode: Literal["live"] = "live"

class InferenceError(RuntimeError):
    """Safe error metadata; provider bodies, headers and prompts are excluded."""
    def __init__(self, code: str, *, retryable: bool = False, retry_after_seconds: float | None = None):
        """Expose only a safe error code and whether a later retry may help."""
        self.code = code
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds
        super().__init__(code)

class LLM(Protocol):
    """The provider-independent inference contract used by future orchestration."""
    async def complete(self, messages: list[Message],
                       tools: list[ToolDefinition]) -> InferenceResult:
        """Return the next assistant response without executing requested business tools."""
        ...
