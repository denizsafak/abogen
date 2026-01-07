from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
from urllib import error, parse, request


class LLMClientError(RuntimeError):
    """Raised when an LLM request fails."""


@dataclass(frozen=True)
class LLMConfiguration:
    base_url: str
    api_key: str
    model: str
    timeout: float = 30.0

    def is_configured(self) -> bool:
        return bool(self.base_url.strip() and self.model.strip())


@dataclass(frozen=True)
class LLMToolCall:
    name: str
    arguments: str


@dataclass(frozen=True)
class LLMCompletion:
    content: Optional[str]
    tool_calls: Tuple[LLMToolCall, ...]


_DEFAULT_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
}


def _normalized_base_url(base_url: str) -> str:
    trimmed = (base_url or "").strip()
    if not trimmed:
        raise LLMClientError("LLM base URL is required")
    if not trimmed.endswith("/"):
        trimmed += "/"
    return trimmed


def _build_url(base_url: str, path: str) -> str:
    normalized = _normalized_base_url(base_url)
    trimmed_path = path.lstrip("/")
    parsed = parse.urlparse(normalized)
    if parsed.path.rstrip("/").lower().endswith("/v1") and trimmed_path.startswith("v1/"):
        trimmed_path = trimmed_path[len("v1/"):]
    return parse.urljoin(normalized, trimmed_path)


def _build_headers(api_key: str) -> Dict[str, str]:
    headers = dict(_DEFAULT_HEADERS)
    token = (api_key or "").strip()
    if token and token.lower() != "ollama":
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _perform_request(
    method: str,
    url: str,
    *,
    headers: Optional[Mapping[str, str]] = None,
    payload: Optional[Mapping[str, Any]] = None,
    timeout: float = 30.0,
) -> Any:
    data_bytes: Optional[bytes] = None
    if payload is not None:
        data_bytes = json.dumps(payload).encode("utf-8")
    request_headers = dict(headers or {})
    req = request.Request(url, data=data_bytes, headers=request_headers, method=method.upper())
    try:
        with request.urlopen(req, timeout=timeout) as response:
            body = response.read()
    except error.HTTPError as exc:  # pragma: no cover - defensive network guard
        message = exc.read().decode("utf-8", "ignore") if exc.fp else exc.reason
        raise LLMClientError(f"LLM request failed ({exc.code}): {message}") from exc
    except error.URLError as exc:  # pragma: no cover - defensive network guard
        raise LLMClientError(f"LLM request failed: {exc.reason}") from exc
    except Exception as exc:  # pragma: no cover - defensive network guard
        raise LLMClientError("LLM request failed") from exc

    if not body:
        return None
    try:
        return json.loads(body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise LLMClientError("LLM response was not valid JSON") from exc


def list_models(configuration: LLMConfiguration) -> List[Dict[str, str]]:
    if not configuration.is_configured() and not configuration.base_url.strip():
        raise LLMClientError("LLM configuration is incomplete")
    url = _build_url(configuration.base_url, "v1/models")
    headers = _build_headers(configuration.api_key)
    payload = _perform_request("GET", url, headers=headers, timeout=configuration.timeout)
    if not isinstance(payload, Mapping):
        raise LLMClientError("Unexpected response when listing models")
    data = payload.get("data")
    if not isinstance(data, list):
        return []
    models: List[Dict[str, str]] = []
    for entry in data:
        if not isinstance(entry, Mapping):
            continue
        identifier = str(entry.get("id") or "").strip()
        if not identifier:
            continue
        description = str(entry.get("name") or entry.get("description") or identifier)
        models.append({"id": identifier, "label": description})
    return models


def generate_completion(
    configuration: LLMConfiguration,
    *,
    system_message: str,
    user_message: str,
    temperature: float = 0.2,
    max_tokens: Optional[int] = None,
    tools: Optional[Sequence[Mapping[str, Any]]] = None,
    tool_choice: Optional[Mapping[str, Any]] = None,
    response_format: Optional[Mapping[str, Any]] = None,
) -> LLMCompletion:
    if not configuration.is_configured():
        raise LLMClientError("LLM configuration is incomplete")

    url = _build_url(configuration.base_url, "v1/chat/completions")
    headers = _build_headers(configuration.api_key)
    payload: Dict[str, Any] = {
        "model": configuration.model,
        "messages": [
            {"role": "system", "content": system_message},
            {"role": "user", "content": user_message},
        ],
        "temperature": temperature,
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    if tools:
        payload["tools"] = list(tools)
    if tool_choice:
        payload["tool_choice"] = dict(tool_choice)
    if response_format:
        payload["response_format"] = dict(response_format)

    response = _perform_request("POST", url, headers=headers, payload=payload, timeout=configuration.timeout)
    if not isinstance(response, Mapping):
        raise LLMClientError("Unexpected response from LLM")
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise LLMClientError("LLM response did not include choices")
    first = choices[0]
    if not isinstance(first, Mapping):
        raise LLMClientError("LLM response choice was invalid")
    message = first.get("message")
    content: Optional[str] = None
    tool_calls: List[LLMToolCall] = []
    if isinstance(message, Mapping):
        content = message.get("content")
        if isinstance(content, str):
            stripped = content.strip()
            if stripped:
                content = stripped
            else:
                content = None
        tool_call_entries = message.get("tool_calls")
        if isinstance(tool_call_entries, list):
            for entry in tool_call_entries:
                if not isinstance(entry, Mapping):
                    continue
                fn = entry.get("function")
                if not isinstance(fn, Mapping):
                    continue
                name = str(fn.get("name") or "").strip()
                if not name:
                    continue
                args = fn.get("arguments", "")
                if isinstance(args, (dict, list)):
                    arguments = json.dumps(args)
                else:
                    arguments = str(args)
                tool_calls.append(LLMToolCall(name=name, arguments=arguments))
    if content:
        return LLMCompletion(content=content, tool_calls=tuple(tool_calls))
    text = first.get("text")
    if isinstance(text, str):
        stripped = text.strip()
        if stripped:
            content = stripped
    if content or tool_calls:
        return LLMCompletion(content=content, tool_calls=tuple(tool_calls))
    raise LLMClientError("LLM response did not include text content")
