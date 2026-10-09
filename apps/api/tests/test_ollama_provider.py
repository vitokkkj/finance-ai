from __future__ import annotations

import json
from asyncio import run

import httpx
import pytest

from app.ai_provider import (
    AIProviderError,
    OllamaProvider,
    ProviderEvent,
    ProviderRequest,
    _ollama_messages,
    _ollama_tool_schemas,
)


def test_ollama_tools_and_history_use_native_chat_shape() -> None:
    request = ProviderRequest(
        model="qwen3:1.7b",
        instructions="Regras privadas da SophIA",
        input_items=[
            {"role": "user", "content": "Quanto tenho?"},
            {
                "type": "function_call",
                "call_id": "call-1",
                "name": "get_accounts",
                "arguments": '{"include_archived":false}',
            },
            {
                "type": "function_call_output",
                "call_id": "call-1",
                "output": '{"accounts":[]}',
            },
        ],
        tools=[
            {
                "type": "function",
                "name": "get_accounts",
                "description": "Lista contas",
                "parameters": {"type": "object", "properties": {}},
                "strict": True,
            }
        ],
    )

    messages = _ollama_messages(request)
    tools = _ollama_tool_schemas(request.tools)

    assert messages == [
        {"role": "system", "content": "Regras privadas da SophIA"},
        {"role": "user", "content": "Quanto tenho?"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "type": "function",
                    "function": {
                        "name": "get_accounts",
                        "arguments": {"include_archived": False},
                    },
                }
            ],
        },
        {"role": "tool", "tool_name": "get_accounts", "content": '{"accounts":[]}'},
    ]
    assert tools == [
        {
            "type": "function",
            "function": {
                "name": "get_accounts",
                "description": "Lista contas",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]


def test_ollama_stream_emits_text_tool_calls_and_usage() -> None:
    chunks = [
        {"message": {"role": "assistant", "content": "Vou consultar."}, "done": False},
        {
            "message": {
                "role": "assistant",
                "tool_calls": [
                    {
                        "index": 0,
                        "function": {
                            "name": "get_accounts",
                            "arguments": {"include_archived": False},
                        },
                    }
                ],
            },
            "done": False,
        },
        {
            "done": True,
            "prompt_eval_count": 54,
            "prompt_eval_cached_count": 10,
            "eval_count": 6,
        },
    ]
    request_payload: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_payload
        request_payload = json.loads(request.content)
        return httpx.Response(
            200,
            content="\n".join(json.dumps(chunk) for chunk in chunks).encode(),
        )

    client = httpx.AsyncClient(
        base_url="http://ollama:11434/",
        transport=httpx.MockTransport(handler),
    )
    provider = OllamaProvider("http://ollama:11434", 4096, client=client)
    request = ProviderRequest(
        model="qwen3:1.7b",
        instructions="Regras",
        input_items=[{"role": "user", "content": "Veja minhas contas"}],
        tools=[{"type": "function", "name": "get_accounts", "parameters": {}}],
    )

    async def collect() -> list[ProviderEvent]:
        events = [event async for event in provider.stream(request)]
        await client.aclose()
        return events

    events = run(collect())

    assert [event.type for event in events] == ["text_delta", "function_call", "completed"]
    assert events[0].text == "Vou consultar."
    assert events[1].function_call is not None
    assert events[1].function_call.name == "get_accounts"
    assert json.loads(events[1].function_call.arguments) == {"include_archived": False}
    assert events[1].function_call.call_id
    assert events[2].input_tokens == 54
    assert events[2].cached_input_tokens == 10
    assert events[2].output_tokens == 6
    assert request_payload["model"] == "qwen3:1.7b"
    assert request_payload["think"] is False
    assert request_payload["options"] == {
        "num_ctx": 4096,
        "num_predict": 128,
        "temperature": 0.1,
    }


def test_ollama_rejects_invalid_stream_without_echoing_provider_body() -> None:
    client = httpx.AsyncClient(
        base_url="http://ollama:11434/",
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, content=b'{"error":"private server body"}')
        )
    )
    provider = OllamaProvider("http://ollama:11434", client=client)
    request = ProviderRequest("qwen3:1.7b", "rules", [], [])

    async def collect() -> None:
        async for _ in provider.stream(request):
            pass

    with pytest.raises(AIProviderError, match="não conseguiu concluir") as caught:
        run(collect())
    run(client.aclose())

    assert caught.value.code == "provider_error"
    assert "private server body" not in str(caught.value)
