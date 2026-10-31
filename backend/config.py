"""Configuration is read explicitly; importing modules does not load secrets."""
import math
import os
from dataclasses import dataclass, field
from urllib.parse import urlsplit
from collections.abc import Mapping

class ConfigurationError(ValueError):
    """Report an invalid or incomplete setting without including secret values."""
    pass

@dataclass(frozen=True)
class Settings:
    """Hold validated runtime settings; hide the API key and endpoint from repr output."""
    mode: str = "live"
    chat_url: str = field(default="", repr=False)
    deployment: str = ""
    api_key: str = field(default="", repr=False)
    timeout_seconds: float = 30.0

    def __post_init__(self):
        """Validate settings even when callers construct them directly in Python."""
        if self.mode != "live":
            raise ConfigurationError("LLM_MODE must be live; other modes are not implemented.")
        if not math.isfinite(self.timeout_seconds) or not 0 < self.timeout_seconds <= 120:
            raise ConfigurationError("LLM_TIMEOUT_SECONDS must be between 0 and 120.")
        if self.chat_url:
            try:
                parsed = urlsplit(self.chat_url)
                valid = (parsed.scheme == "https" and parsed.hostname and not parsed.username
                         and not parsed.password and not parsed.fragment and not parsed.query
                         and parsed.path.endswith("/chat/completions"))
                _ = parsed.port
            except ValueError:
                valid = False
            if not valid:
                raise ConfigurationError("AZURE_GROK_CHAT_URL must be an HTTPS chat/completions URL without credentials, query, or fragment.")

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        """Read environment values, default to LIVE, and convert the request timeout."""
        values = os.environ if env is None else env
        mode = values.get("LLM_MODE", "live").strip()
        if mode != "live":
            raise ConfigurationError("LLM_MODE must be live; other modes are not implemented.")
        try:
            timeout = float(values.get("LLM_TIMEOUT_SECONDS", "30"))
        except ValueError:
            raise ConfigurationError("LLM_TIMEOUT_SECONDS must be a number.") from None
        if not math.isfinite(timeout) or not 0 < timeout <= 120:
            raise ConfigurationError("LLM_TIMEOUT_SECONDS must be between 0 and 120.")
        result = cls(mode, values.get("AZURE_GROK_CHAT_URL", "").strip(),
                     values.get("AZURE_GROK_DEPLOYMENT", "").strip(),
                     values.get("AZURE_GROK_API_KEY", "").strip(), timeout)
        return result

    @property
    def missing_credentials(self) -> list[str]:
        """Return names of absent Azure settings, never their values."""
        return [name for name, value in (
            ("AZURE_GROK_CHAT_URL", self.chat_url),
            ("AZURE_GROK_DEPLOYMENT", self.deployment),
            ("AZURE_GROK_API_KEY", self.api_key)) if not value]

    def require_live(self) -> None:
        """Fail before inference if any required Azure configuration is missing."""
        if self.missing_credentials:
            raise ConfigurationError("Missing configuration: " + ", ".join(self.missing_credentials))
