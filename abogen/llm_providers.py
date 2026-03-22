"""Built-in LLM provider presets for quick configuration.

Each preset bundles the endpoint URL, a list of known models, and the
environment variable that typically holds the API key.  The Web UI
uses these presets so users can pick a provider from a dropdown instead
of typing the URL manually.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Sequence, Tuple


@dataclass(frozen=True)
class LLMProviderPreset:
    """A preconfigured cloud or local LLM endpoint."""

    id: str
    name: str
    base_url: str
    api_key_env: str = ""
    api_key_hint: str = ""
    models: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, object]:
        return {
            "id": self.id,
            "name": self.name,
            "base_url": self.base_url,
            "api_key_env": self.api_key_env,
            "api_key_hint": self.api_key_hint,
            "models": list(self.models),
        }


_BUILTIN_PRESETS: Tuple[LLMProviderPreset, ...] = (
    LLMProviderPreset(
        id="minimax",
        name="MiniMax",
        base_url="https://api.minimax.io/v1",
        api_key_env="MINIMAX_API_KEY",
        api_key_hint="Get your key at https://platform.minimax.io",
        models=(
            "MiniMax-M1",
            "MiniMax-Text-01",
            "MiniMax-M2.5",
            "MiniMax-M2.5-highspeed",
            "MiniMax-M2.7",
            "MiniMax-M2.7-highspeed",
        ),
    ),
    LLMProviderPreset(
        id="openai",
        name="OpenAI",
        base_url="https://api.openai.com/v1",
        api_key_env="OPENAI_API_KEY",
        api_key_hint="Get your key at https://platform.openai.com/api-keys",
        models=(
            "gpt-4o",
            "gpt-4o-mini",
            "gpt-4.1",
            "gpt-4.1-mini",
            "gpt-4.1-nano",
        ),
    ),
    LLMProviderPreset(
        id="deepseek",
        name="DeepSeek",
        base_url="https://api.deepseek.com/v1",
        api_key_env="DEEPSEEK_API_KEY",
        api_key_hint="Get your key at https://platform.deepseek.com",
        models=(
            "deepseek-chat",
            "deepseek-reasoner",
        ),
    ),
    LLMProviderPreset(
        id="ollama",
        name="Ollama (local)",
        base_url="http://localhost:11434/v1",
        api_key_env="",
        api_key_hint='Use "ollama" or leave blank',
        models=(),
    ),
)


def get_provider_presets() -> Sequence[LLMProviderPreset]:
    """Return all built-in provider presets."""
    return _BUILTIN_PRESETS


def get_provider_by_id(provider_id: str) -> LLMProviderPreset | None:
    """Look up a single preset by its identifier."""
    for preset in _BUILTIN_PRESETS:
        if preset.id == provider_id:
            return preset
    return None
