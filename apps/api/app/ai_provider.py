from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, cast
from uuid import uuid4

import httpx
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    AuthenticationError,
    RateLimitError,
)

from app.chatgpt_plan import ChatGPTCredentialStore, ChatGPTPlanError

ProviderEventType = Literal["text_delta", "function_call", "completed"]
@dataclass(frozen=True, slots=True)
class FunctionCall:
    call_id: str
    name: str
    arguments: str


@dataclass(frozen=True, slots=True)
class ProviderEvent:
    type: ProviderEventType
    text: str = ""
    function_call: FunctionCall | None = None
    output_items: list[dict[str, object]] = field(default_factory=list)
    input_tokens: int | None = None
    cached_input_tokens: int | None = None
    cache_write_tokens: int | None = None
    output_tokens: int | None = None


@dataclass(frozen=True, slots=True)
class ProviderRequest:
    model: str
    instructions: str
    input_items: list[dict[str, object]]
    tools: list[dict[str, object]]
    tool_choice: Literal["auto", "none"] = "auto"


class AIProvider(Protocol):
    def stream(self, request: ProviderRequest) -> AsyncIterator[ProviderEvent]: ...

    async def close(self) -> None: ...


class AIProviderError(Exception):
    def __init__(self, message: str, code: str = "provider_error") -> None:
        super().__init__(message)
        self.code = code


def _safe_provider_error_code(error: object) -> str:
    if isinstance(error, dict):
        candidate = error.get("code") or error.get("type")
    else:
        candidate = getattr(error, "code", None) or getattr(error, "type", None)
    if isinstance(candidate, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,63}", candidate):
        return candidate
    return "provider_error"


CHATGPT_PLAN_ERRORS: dict[str, tuple[str, str]] = {
    "subscription_sharing_usage_limit_exceeded": (
        "plan_usage_limit",
        "O limite de uso do seu plano ChatGPT foi atingido. "
        "A SophIA não trocará para uma API paga. Confira o uso da conta e tente novamente depois.",
    ),
    "subscription_sharing_usage_unavailable": (
        "plan_usage_unavailable",
        "O uso do plano ChatGPT está indisponível no momento. Tente novamente mais tarde.",
    ),
    "subscription_sharing_user_not_eligible": (
        "plan_not_eligible",
        "Esta conta ou workspace não está habilitada para usar o plano ChatGPT na SophIA.",
    ),
    "subscription_sharing_unsupported_capability": (
        "unsupported_capability",
        "O modelo ou recurso solicitado não é compatível com o uso do plano ChatGPT.",
    ),
    "subscription_sharing_route_not_supported": (
        "route_not_supported",
        "A rota de inferência não está habilitada para esta conexão ChatGPT.",
    ),
    "subscription_sharing_invalid_user": (
        "reconnect_required",
        "A conexão com o ChatGPT não foi validada. Reconecte sua conta.",
    ),
    "subscription_sharing_user_unavailable": (
        "plan_usage_unavailable",
        "A conta ChatGPT está temporariamente indisponível. Tente novamente mais tarde.",
    ),
    "chatpass_v2_scope_not_authorized": (
        "plan_scope_missing",
        "A conexão não autorizou o uso do plano ChatGPT. Reconecte e aceite essa permissão.",
    ),
    "chatpass_v2_invalid_authorization_context": (
        "invalid_authorization",
        "A autorização do plano ChatGPT não corresponde a esta conexão.",
    ),
}


def _friendly_plan_error(provider_error: object, status_code: int | None = None) -> AIProviderError:
    code = _safe_provider_error_code(provider_error)
    known = CHATGPT_PLAN_ERRORS.get(code)
    if known:
        return AIProviderError(known[1], known[0])
    if status_code == 401:
        return AIProviderError(
            "A conexão com o ChatGPT expirou ou foi recusada. Reconecte sua conta.",
            "reconnect_required",
        )
    if status_code == 403:
        return AIProviderError(
            "O acesso ao plano ChatGPT foi recusado para esta solicitação.",
            "plan_access_denied",
        )
    if status_code == 429:
        return AIProviderError(
            "O limite de uso do seu plano ChatGPT foi atingido. "
            "A SophIA não trocará para uma API paga.",
            "plan_usage_limit",
        )
    if status_code == 408:
        return AIProviderError(
            "A resposta do ChatGPT demorou mais que o esperado. Tente novamente.",
            "timeout",
        )
    if status_code is not None and status_code >= 500:
        return AIProviderError(
            "O serviço do ChatGPT está indisponível no momento. Tente novamente.",
            "provider_unavailable",
        )
    return AIProviderError(
        "O ChatGPT não conseguiu concluir a resposta. Tente novamente.",
        code if code != "provider_error" else "invalid_response",
    )


class OpenAIResponsesProvider:
    """Responses API adapter authenticated with the user's ChatGPT plan OAuth token."""

    def __init__(self, credentials: ChatGPTCredentialStore) -> None:
        self._credentials = credentials

    def _new_client(self, access_token: str) -> AsyncOpenAI:
        return AsyncOpenAI(
            api_key=access_token,
            base_url="https://api.openai.com/v1",
            timeout=45.0,
            max_retries=0,
        )

    async def stream(self, request: ProviderRequest) -> AsyncIterator[ProviderEvent]:
        try:
            access_token = await self._credentials.get_access_token()
        except ChatGPTPlanError as error:
            raise AIProviderError(str(error), error.code) from None

        client = self._new_client(access_token)
        # This plan-sharing route requires tools in the input stream and rejects
        # max_output_tokens. The app's own PostgreSQL history is sent each turn.
        input_items = list(request.input_items)
        create_kwargs: dict[str, object] = {
            "model": request.model,
            "instructions": request.instructions,
            "input": input_items,
            "store": False,
            "stream": True,
            "parallel_tool_calls": False,
        }
        if request.tools and request.tool_choice != "none":
            input_items.insert(
                0,
                {
                    "type": "additional_tools",
                    "role": "developer",
                    "tools": request.tools,
                },
            )
            create_kwargs["tool_choice"] = request.tool_choice

        create = cast(Any, client.responses).create
        completed = False
        try:
            stream = await create(**create_kwargs)
            async for raw_event in stream:
                event = cast(object, raw_event)
                event_type = getattr(event, "type", "")
                if event_type == "response.output_text.delta":
                    yield ProviderEvent(type="text_delta", text=str(getattr(event, "delta", "")))
                elif event_type == "response.output_item.done":
                    item = getattr(event, "item", None)
                    if getattr(item, "type", "") == "function_call":
                        yield ProviderEvent(
                            type="function_call",
                            function_call=FunctionCall(
                                call_id=str(getattr(item, "call_id", "")),
                                name=str(getattr(item, "name", "")),
                                arguments=str(getattr(item, "arguments", "{}")),
                            ),
                        )
                elif event_type == "response.completed":
                    response = getattr(event, "response", None)
                    usage = getattr(response, "usage", None)
                    details = getattr(usage, "input_tokens_details", None)
                    output = getattr(response, "output", [])
                    output_items = [
                        cast(dict[str, object], item.model_dump(mode="json"))
                        for item in output
                        if hasattr(item, "model_dump")
                    ]
                    completed = True
                    yield ProviderEvent(
                        type="completed",
                        output_items=output_items,
                        input_tokens=getattr(usage, "input_tokens", None),
                        cached_input_tokens=getattr(details, "cached_tokens", None),
                        cache_write_tokens=getattr(details, "cache_write_tokens", None),
                        output_tokens=getattr(usage, "output_tokens", None),
                    )
                elif event_type == "response.incomplete":
                    raise AIProviderError(
                        "A resposta do ChatGPT ficou incompleta. Tente dividir a solicitação.",
                        "incomplete_response",
                    )
                elif event_type in {"response.failed", "error"}:
                    response = getattr(event, "response", None)
                    provider_error = getattr(response, "error", None) or getattr(
                        event, "error", None
                    )
                    raise _friendly_plan_error(provider_error)
            if not completed:
                raise AIProviderError(
                    "A resposta do ChatGPT foi encerrada antes da conclusão.",
                    "invalid_response",
                )
        except AIProviderError:
            raise
        except APITimeoutError:
            raise AIProviderError(
                "A solicitação ao ChatGPT excedeu o tempo limite. Tente novamente.", "timeout"
            ) from None
        except AuthenticationError:
            raise _friendly_plan_error(None, 401) from None
        except RateLimitError:
            raise _friendly_plan_error(None, 429) from None
        except APIStatusError as error:
            body = getattr(error, "body", None)
            provider_error = body.get("error") if isinstance(body, dict) else None
            raise _friendly_plan_error(provider_error, error.status_code) from None
        except (APIConnectionError, TimeoutError, OSError):
            raise AIProviderError(
                "Não foi possível conectar ao ChatGPT. Tente novamente.", "network_error"
            ) from None
        except Exception:
            raise AIProviderError(
                "O ChatGPT retornou uma resposta inválida. Tente novamente.", "invalid_response"
            ) from None
        finally:
            await client.close()

    async def close(self) -> None:
        return None


def _ollama_tool_schemas(tools: list[dict[str, object]]) -> list[dict[str, object]]:
    converted: list[dict[str, object]] = []
    for tool in tools:
        name = tool.get("name")
        parameters = tool.get("parameters")
        if tool.get("type") != "function" or not isinstance(name, str):
            continue
        function: dict[str, object] = {"name": name}
        for key in ("description", "parameters"):
            value = tool.get(key)
            if value is not None:
                function[key] = value
        if not isinstance(parameters, dict):
            function["parameters"] = {"type": "object", "properties": {}}
        converted.append({"type": "function", "function": function})
    return converted


def _ollama_messages(request: ProviderRequest) -> list[dict[str, object]]:
    messages: list[dict[str, object]] = [{"role": "system", "content": request.instructions}]
    tool_names: dict[str, str] = {}
    pending_calls: list[dict[str, object]] = []

    def flush_tool_calls() -> None:
        if pending_calls:
            messages.append({"role": "assistant", "content": "", "tool_calls": list(pending_calls)})
            pending_calls.clear()

    for item in request.input_items:
        item_type = item.get("type")
        if item_type == "function_call":
            name = item.get("name")
            call_id = item.get("call_id")
            if not isinstance(name, str) or not isinstance(call_id, str):
                continue
            raw_arguments = item.get("arguments")
            try:
                arguments = json.loads(raw_arguments) if isinstance(raw_arguments, str) else {}
            except json.JSONDecodeError:
                arguments = {}
            if not isinstance(arguments, dict):
                arguments = {}
            tool_names[call_id] = name
            pending_calls.append(
                {
                    "type": "function",
                    "function": {"name": name, "arguments": arguments},
                }
            )
            continue

        if item_type == "function_call_output":
            flush_tool_calls()
            call_id = item.get("call_id")
            if not isinstance(call_id, str):
                continue
            name = tool_names.get(call_id)
            if name is None:
                continue
            output = item.get("output")
            messages.append(
                {
                    "role": "tool",
                    "tool_name": name,
                    "content": output if isinstance(output, str) else "{}",
                }
            )
            continue

        role = item.get("role")
        if role == "user" or role == "assistant":
            flush_tool_calls()
            content = item.get("content")
            messages.append({"role": role, "content": content if isinstance(content, str) else ""})

    flush_tool_calls()
    return messages


class OllamaProvider:
    """Adapter for Ollama's local native chat API."""

    def __init__(
        self,
        base_url: str,
        context_length: int = 4096,
        *,
        timeout_seconds: float = 900.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._client = client or httpx.AsyncClient(
            base_url=f"{base_url.rstrip('/')}/",
            timeout=httpx.Timeout(timeout_seconds, connect=5.0),
        )
        self._owns_client = client is None
        self._context_length = context_length

    async def stream(self, request: ProviderRequest) -> AsyncIterator[ProviderEvent]:
        payload: dict[str, object] = {
            "model": request.model,
            "messages": _ollama_messages(request),
            "stream": True,
            # Tool selection is a short, structured task for this constrained
            # CPU deployment; disable Qwen's optional reasoning trace to keep
            # first-token latency practical.
            "think": False,
            "keep_alive": "5m",
            "options": {
                "num_ctx": self._context_length,
                "num_predict": 128,
                "temperature": 0.1,
            },
        }
        if request.tools and request.tool_choice != "none":
            payload["tools"] = _ollama_tool_schemas(request.tools)

        calls: dict[int, dict[str, object]] = {}
        completed = False
        try:
            async with self._client.stream("POST", "api/chat", json=payload) as response:
                if response.is_error:
                    code = "provider_unavailable"
                    message = "A IA local não está disponível no momento. Tente novamente."
                    if response.status_code == 404:
                        code = "model_not_found"
                        message = (
                            "O modelo local não está instalado. Reinicie o ambiente para baixá-lo."
                        )
                    elif response.status_code == 429:
                        code = "rate_limit"
                        message = "A IA local está ocupada. Aguarde um pouco e tente novamente."
                    elif response.status_code < 500:
                        code = "invalid_response"
                        message = "O modelo local não conseguiu processar esta solicitação."
                    raise AIProviderError(message, code)

                async for line in response.aiter_lines():
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError as error:
                        raise AIProviderError(
                            "A IA local retornou uma resposta inválida.", "invalid_response"
                        ) from error
                    if not isinstance(chunk, dict):
                        raise AIProviderError(
                            "A IA local retornou uma resposta inválida.", "invalid_response"
                        )
                    if "error" in chunk:
                        raise AIProviderError(
                            "A IA local não conseguiu concluir a resposta.", "provider_error"
                        )

                    raw_message = chunk.get("message")
                    if isinstance(raw_message, dict):
                        content = raw_message.get("content")
                        if isinstance(content, str) and content:
                            yield ProviderEvent(type="text_delta", text=content)
                        raw_calls = raw_message.get("tool_calls")
                        if isinstance(raw_calls, list):
                            for offset, raw_call in enumerate(raw_calls):
                                if not isinstance(raw_call, dict):
                                    continue
                                raw_index = raw_call.get("index", offset)
                                index = raw_index if isinstance(raw_index, int) else offset
                                function = raw_call.get("function")
                                if not isinstance(function, dict):
                                    continue
                                call = calls.setdefault(index, {"name": "", "arguments": {}})
                                name = function.get("name")
                                if isinstance(name, str) and name:
                                    call["name"] = name
                                arguments = function.get("arguments")
                                if isinstance(arguments, dict):
                                    current = call.get("arguments")
                                    merged = dict(current) if isinstance(current, dict) else {}
                                    merged.update(arguments)
                                    call["arguments"] = merged
                                elif isinstance(arguments, str) and arguments:
                                    current = call.get("arguments")
                                    call["arguments"] = (
                                        f"{current}{arguments}"
                                        if isinstance(current, str)
                                        else arguments
                                    )

                    if chunk.get("done") is True:
                        for call in calls.values():
                            name = call.get("name")
                            arguments = call.get("arguments")
                            if not isinstance(name, str) or not name:
                                raise AIProviderError(
                                    "A IA local retornou uma ferramenta sem nome.",
                                    "invalid_response",
                                )
                            if isinstance(arguments, str):
                                try:
                                    parsed_arguments = json.loads(arguments)
                                except json.JSONDecodeError as error:
                                    raise AIProviderError(
                                        "A IA local retornou parâmetros inválidos "
                                        "para uma ferramenta.",
                                        "invalid_response",
                                    ) from error
                            else:
                                parsed_arguments = arguments
                            if not isinstance(parsed_arguments, dict):
                                raise AIProviderError(
                                    "A IA local retornou parâmetros inválidos para uma ferramenta.",
                                    "invalid_response",
                                )
                            yield ProviderEvent(
                                type="function_call",
                                function_call=FunctionCall(
                                    call_id=uuid4().hex,
                                    name=name,
                                    arguments=json.dumps(parsed_arguments, ensure_ascii=False),
                                ),
                            )
                        completed = True
                        cached_tokens = chunk.get("prompt_eval_cached_count")
                        yield ProviderEvent(
                            type="completed",
                            input_tokens=_optional_int(chunk.get("prompt_eval_count")),
                            cached_input_tokens=_optional_int(cached_tokens),
                            output_tokens=_optional_int(chunk.get("eval_count")),
                        )
            if not completed:
                raise AIProviderError(
                    "A IA local encerrou a resposta antes da conclusão.", "invalid_response"
                )
        except AIProviderError:
            raise
        except httpx.TimeoutException as error:
            raise AIProviderError(
                "A resposta da IA local demorou mais que o esperado. Tente novamente.", "timeout"
            ) from error
        except httpx.HTTPStatusError as error:
            raise AIProviderError(
                "A IA local não está disponível no momento. Tente novamente.",
                "provider_unavailable",
            ) from error
        except httpx.RequestError as error:
            raise AIProviderError(
                "Não foi possível conectar à IA local. Tente novamente.", "network_error"
            ) from error
        except Exception as error:
            raise AIProviderError(
                "A IA local retornou uma resposta inválida. Tente novamente.", "invalid_response"
            ) from error

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


async def ollama_models_available(base_url: str, model_names: set[str]) -> bool:
    try:
        async with httpx.AsyncClient(
            base_url=f"{base_url.rstrip('/')}/", timeout=httpx.Timeout(2.0, connect=1.0)
        ) as client:
            response = await client.get("api/tags")
        response.raise_for_status()
        body = response.json()
    except (httpx.HTTPError, ValueError):
        return False
    models = body.get("models") if isinstance(body, dict) else None
    if not isinstance(models, list):
        return False
    available = {
        entry.get("name")
        for entry in models
        if isinstance(entry, dict) and isinstance(entry.get("name"), str)
    }
    return model_names.issubset(available)
