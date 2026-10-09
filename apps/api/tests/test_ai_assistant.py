from __future__ import annotations

import json
from asyncio import run
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.ai import get_ai_provider
from app.ai_chat import choose_model
from app.ai_pricing import estimated_cost
from app.ai_provider import (
    AIProviderError,
    FunctionCall,
    OpenAIResponsesProvider,
    ProviderEvent,
    ProviderRequest,
    _friendly_plan_error,
)
from app.auth import password_hasher
from app.chatgpt_plan import ChatGPTPlanError
from app.config import settings
from app.main import app
from app.models import AIMessage, User


class FakeAIProvider:
    def __init__(self, responses: list[list[ProviderEvent]]) -> None:
        self.responses = responses
        self.requests: list[ProviderRequest] = []

    def stream(self, request: ProviderRequest) -> AsyncIterator[ProviderEvent]:
        self.requests.append(request)

        async def generate() -> AsyncIterator[ProviderEvent]:
            for event in self.responses.pop(0):
                yield event

        return generate()

    async def close(self) -> None:
        return None


def _sign_up(client: TestClient) -> None:
    response = client.post(
        "/api/auth/setup",
        json={
            "email": "assistant@example.com",
            "display_name": "Pessoa",
            "password": "uma-senha-local-segura",
        },
    )
    assert response.status_code == 201


def test_conversation_can_be_created_renamed_and_archived(client: TestClient) -> None:
    _sign_up(client)

    created = client.post("/api/ai/conversations", json={})

    assert created.status_code == 201
    conversation = created.json()
    assert conversation["title"] == "Nova conversa"
    assert conversation["messages"] == []

    renamed = client.patch(
        f"/api/ai/conversations/{conversation['id']}",
        json={"title": "Gastos de outubro"},
    )
    assert renamed.status_code == 200
    assert renamed.json()["title"] == "Gastos de outubro"

    archived = client.post(f"/api/ai/conversations/{conversation['id']}/archive")
    assert archived.status_code == 204
    assert client.get("/api/ai/conversations").json() == []


def test_conversation_cannot_be_read_by_a_different_user(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    _sign_up(client)
    created = client.post("/api/ai/conversations", json={})
    conversation_id = created.json()["id"]

    with test_session_factory() as db:
        db.add(
            User(
                email="other@example.com",
                display_name="Outra pessoa",
                password_hash=password_hasher.hash("outra-senha-local-segura"),
            )
        )
        db.commit()

    client.cookies.clear()
    login = client.post(
        "/api/auth/login",
        json={"email": "other@example.com", "password": "outra-senha-local-segura"},
    )
    assert login.status_code == 200

    assert client.get(f"/api/ai/conversations/{conversation_id}").status_code == 404
    assert (
        client.patch(
            f"/api/ai/conversations/{conversation_id}", json={"title": "Invasão"}
        ).status_code
        == 404
    )


def _set_fake_provider(client: TestClient, fake: FakeAIProvider) -> None:
    _ = client
    app.dependency_overrides[get_ai_provider] = lambda: fake


def _create_assistant_basics(client: TestClient) -> tuple[str, str]:
    account = client.post(
        "/api/accounts",
        json={
            "name": "Conta principal",
            "type": "CHECKING",
            "opening_balance": "0.00",
            "opening_balance_date": "2026-01-01",
        },
    )
    category = client.post("/api/categories", json={"name": "Alimentação", "type": "EXPENSE"})
    assert account.status_code == 201
    assert category.status_code == 201
    return account.json()["id"], category.json()["id"]


def _completed(input_tokens: int = 14, output_tokens: int = 8) -> ProviderEvent:
    return ProviderEvent(
        type="completed",
        input_tokens=input_tokens,
        cached_input_tokens=0,
        cache_write_tokens=0,
        output_tokens=output_tokens,
    )


@pytest.mark.parametrize(
    ("code", "expected_code"),
    [
        ("subscription_sharing_usage_limit_exceeded", "plan_usage_limit"),
        ("subscription_sharing_usage_unavailable", "plan_usage_unavailable"),
        ("subscription_sharing_user_not_eligible", "plan_not_eligible"),
        ("subscription_sharing_unsupported_capability", "unsupported_capability"),
    ],
)
def test_chatgpt_plan_errors_are_friendly_and_do_not_echo_details(
    code: str, expected_code: str
) -> None:
    friendly = _friendly_plan_error({"code": code, "message": "private token details"})

    assert friendly.code == expected_code
    assert "private" not in str(friendly)
    assert "token details" not in str(friendly)


def test_model_router_replays_stateless_reasoning_items_with_tool_outputs(
    client: TestClient,
) -> None:
    _sign_up(client)
    _create_assistant_basics(client)
    conversation = client.post("/api/ai/conversations", json={}).json()
    summary_arguments = json.dumps({"year": _today().year, "month": _today().month})
    response_items: list[dict[str, object]] = [
        {"type": "reasoning", "encrypted_content": "opaque-reasoning-state"},
        {
            "type": "function_call",
            "call_id": "call_stateful",
            "name": "get_month_summary",
            "arguments": summary_arguments,
        },
    ]
    fake = FakeAIProvider(
        [
            [
                ProviderEvent(
                    type="function_call",
                    function_call=FunctionCall(
                        "call_stateful", "get_month_summary", summary_arguments
                    ),
                ),
                ProviderEvent(type="completed", output_items=response_items),
            ],
            [ProviderEvent(type="text_delta", text="Aqui está."), _completed()],
        ]
    )
    _set_fake_provider(client, fake)

    response = client.post(
        f"/api/ai/conversations/{conversation['id']}/messages",
        json={"content": "Quanto gastei este mês?"},
    )

    assert response.status_code == 200
    assert fake.requests[1].input_items[-3] == response_items[0]
    assert fake.requests[1].input_items[-2] == {
        "type": "function_call",
        "call_id": "call_stateful",
        "name": "get_month_summary",
        "arguments": summary_arguments,
    }
    assert "status" not in fake.requests[1].input_items[-2]
    assert fake.requests[1].input_items[-1]["type"] == "function_call_output"


@pytest.mark.parametrize(
    ("content", "smart"),
    [
        ("Gastei R$ 87,50 de combustível hoje no Sicredi.", False),
        ("Quanto gastei este mês?", False),
        ("Só alimentação.", False),
        ("E mês passado?", False),
        ("qnt gastei esse mes", False),
        ("botei 100 de gasolina hj", False),
        ("passei 240 no nubank no mercado", False),
        ("Quanto está minha fatura?", False),
        ("Compare minhas despesas deste mês e do mês passado.", True),
        ("O que mudou nos meus gastos nos últimos 3 meses?", True),
        ("Faça uma análise detalhada dos últimos meses.", True),
        ("Me ajude com meu planejamento financeiro.", True),
    ],
)
def test_model_routing_uses_fast_by_default_and_smart_for_complex_analysis(
    content: str, smart: bool
) -> None:
    expected = settings.ai_model_smart if smart else settings.ai_model_fast

    assert choose_model(content) == expected


def test_explicit_preferences_can_be_created_updated_and_removed(client: TestClient) -> None:
    _sign_up(client)

    created = client.post("/api/ai/memories", json={"content": "  Prefiro respostas diretas.  "})

    assert created.status_code == 201
    preference = created.json()
    assert preference["content"] == "Prefiro respostas diretas."
    assert "user_id" not in preference

    updated = client.patch(
        f"/api/ai/memories/{preference['id']}",
        json={"content": "Classifique compras na Padaria como Alimentação."},
    )
    assert updated.status_code == 200
    assert updated.json()["content"].startswith("Classifique compras")
    assert client.get("/api/ai/memories").json() == [updated.json()]

    removed = client.delete(f"/api/ai/memories/{preference['id']}")
    assert removed.status_code == 204
    assert client.get("/api/ai/memories").json() == []


def test_explicit_preference_endpoints_validate_and_enforce_ownership(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    _sign_up(client)
    preference = client.post("/api/ai/memories", json={"content": "Conta Sicredi"}).json()

    assert client.post("/api/ai/memories", json={"content": "   "}).status_code == 422
    assert client.post("/api/ai/memories", json={"content": "x" * 501}).status_code == 422

    with test_session_factory() as db:
        db.add(
            User(
                email="other-preference@example.com",
                display_name="Outra pessoa",
                password_hash=password_hasher.hash("outra-senha-local-segura"),
            )
        )
        db.commit()

    client.cookies.clear()
    login = client.post(
        "/api/auth/login",
        json={"email": "other-preference@example.com", "password": "outra-senha-local-segura"},
    )
    assert login.status_code == 200
    assert (
        client.patch(
            f"/api/ai/memories/{preference['id']}", json={"content": "Alteração indevida"}
        ).status_code
        == 404
    )
    assert client.delete(f"/api/ai/memories/{preference['id']}").status_code == 404


def test_pricing_uses_versioned_cache_rates_and_unknown_models_are_unavailable() -> None:
    cost = estimated_cost("gpt-6-luna", 1_000, 100, 100, 1_000)

    assert cost == Decimal("0.0005935")
    assert estimated_cost("custom-model", 1_000, 0, 0, 1_000) is None
    assert estimated_cost("gpt-6-luna", 1_000, None, None, 1_000) is None


def test_provider_uses_plan_token_store_false_and_namespaced_input_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, object] = {}
    tokens: list[str] = []

    class Credentials:
        async def get_access_token(self) -> str:
            return "oauth-plan-token"

    class CompletedStream:
        async def __aiter__(self) -> AsyncIterator[object]:
            yield SimpleNamespace(
                type="response.completed",
                response=SimpleNamespace(
                    output=[],
                    usage=SimpleNamespace(
                        input_tokens=30,
                        input_tokens_details=SimpleNamespace(cached_tokens=8, cache_write_tokens=4),
                        output_tokens=6,
                    ),
                ),
            )

    class FakeResponses:
        async def create(self, **kwargs: object) -> CompletedStream:
            calls.update(kwargs)
            return CompletedStream()

    class FakeClient:
        responses = FakeResponses()

        async def close(self) -> None:
            return None

    provider = OpenAIResponsesProvider(Credentials())

    def make_client(token: str) -> FakeClient:
        tokens.append(token)
        return FakeClient()

    monkeypatch.setattr(provider, "_new_client", make_client)
    tools = [
        {
            "type": "function",
            "name": "get_accounts",
            "description": "List the signed-in user's accounts.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        }
    ]

    async def collect() -> list[ProviderEvent]:
        return [
            event
            async for event in provider.stream(
                ProviderRequest(
                    "gpt-6-luna",
                    "instruções",
                    [{"role": "user", "content": "Mostre minhas contas"}],
                    tools,
                )
            )
        ]

    events = run(collect())
    completed = events[-1]

    assert tokens == ["oauth-plan-token"]
    assert calls["store"] is False
    assert calls["stream"] is True
    assert calls["model"] == "gpt-6-luna"
    assert "max_output_tokens" not in calls
    assert "tools" not in calls
    input_items = calls["input"]
    assert isinstance(input_items, list)
    assert input_items[0] == {
        "type": "additional_tools",
        "role": "developer",
        "tools": tools,
    }
    assert completed.cached_input_tokens == 8
    assert completed.cache_write_tokens == 4


def test_provider_maps_streamed_plan_usage_limit_without_paid_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Credentials:
        async def get_access_token(self) -> str:
            return "oauth-plan-token"

    class FailedStream:
        async def __aiter__(self) -> AsyncIterator[object]:
            yield SimpleNamespace(
                type="response.failed",
                response=SimpleNamespace(
                    error=SimpleNamespace(
                        code="subscription_sharing_usage_limit_exceeded",
                        message="private account details",
                    )
                ),
            )

    class FakeResponses:
        async def create(self, **kwargs: object) -> FailedStream:
            _ = kwargs
            return FailedStream()

    class FakeClient:
        responses = FakeResponses()

        async def close(self) -> None:
            return None

    provider = OpenAIResponsesProvider(Credentials())
    monkeypatch.setattr(provider, "_new_client", lambda token: FakeClient())

    async def collect() -> None:
        async for _ in provider.stream(ProviderRequest("gpt-6-luna", "", [], [])):
            pass

    with pytest.raises(AIProviderError) as caught:
        run(collect())

    assert caught.value.code == "plan_usage_limit"
    assert "não trocará para uma API paga" in str(caught.value)
    assert "private account" not in str(caught.value)


def test_provider_requires_authorized_plan_and_never_requests_api_key() -> None:
    class MissingCredentials:
        async def get_access_token(self) -> str:
            raise ChatGPTPlanError(
                "connection_required",
                "Conecte o plano ChatGPT. A SophIA não usará uma API paga.",
            )

    provider = OpenAIResponsesProvider(MissingCredentials())

    async def collect() -> None:
        async for _ in provider.stream(ProviderRequest("gpt-6-luna", "", [], [])):
            pass

    with pytest.raises(AIProviderError) as caught:
        run(collect())

    assert caught.value.code == "connection_required"
    assert "API paga" in str(caught.value)


def _today() -> date:
    return datetime.now(UTC).astimezone(ZoneInfo("America/Sao_Paulo")).date()


def test_sse_response_persists_messages_context_and_usage(client: TestClient) -> None:
    _sign_up(client)
    conversation = client.post("/api/ai/conversations", json={}).json()
    fake = FakeAIProvider(
        [
            [ProviderEvent(type="text_delta", text="Olá, Pessoa."), _completed()],
            [ProviderEvent(type="text_delta", text="Posso ajudar."), _completed(20, 9)],
        ]
    )
    _set_fake_provider(client, fake)

    first = client.post(
        f"/api/ai/conversations/{conversation['id']}/messages", json={"content": "Oi"}
    )
    second = client.post(
        f"/api/ai/conversations/{conversation['id']}/messages",
        json={"content": "O que pode fazer?"},
    )

    assert first.status_code == second.status_code == 200
    assert first.headers["content-type"].startswith("text/event-stream")
    assert "event: text_delta" in first.text
    assert 'event: done\ndata: {"status": "ok"}' in first.text
    messages = client.get(f"/api/ai/conversations/{conversation['id']}").json()["messages"]
    assert [(item["role"], item["content"]) for item in messages] == [
        ("USER", "Oi"),
        ("ASSISTANT", "Olá, Pessoa."),
        ("USER", "O que pode fazer?"),
        ("ASSISTANT", "Posso ajudar."),
    ]
    assert any(item == {"role": "user", "content": "Oi"} for item in fake.requests[1].input_items)
    assert all(
        "user_id" not in json.dumps(tool) for request in fake.requests for tool in request.tools
    )
    usage = client.get("/api/ai/usage").json()
    assert usage["calls_today"] == 2
    assert usage["input_tokens_today"] == 34
    assert usage["output_tokens_today"] == 17


def test_month_summary_uses_finance_engine_and_returns_structured_card(client: TestClient) -> None:
    _sign_up(client)
    account_id, category_id = _create_assistant_basics(client)
    today = _today()
    month = {"year": today.year, "month": today.month}
    created = client.post(
        "/api/transactions",
        json={
            "account_id": account_id,
            "category_id": category_id,
            "type": "EXPENSE",
            "description": "Mercado",
            "amount": "87.50",
            "occurred_at": today.isoformat(),
        },
    )
    assert created.status_code == 201
    conversation = client.post("/api/ai/conversations", json={}).json()
    fake = FakeAIProvider(
        [
            [
                ProviderEvent(
                    type="function_call",
                    function_call=FunctionCall(
                        "call_summary", "get_month_summary", json.dumps(month)
                    ),
                ),
                _completed(30, 5),
            ],
            [ProviderEvent(type="text_delta", text="As despesas somam R$ 87,50."), _completed()],
        ]
    )
    _set_fake_provider(client, fake)

    response = client.post(
        f"/api/ai/conversations/{conversation['id']}/messages",
        json={"content": "Quanto gastei neste mês?"},
    )

    assert response.status_code == 200
    assert '"type": "financial_summary"' in response.text
    assert '"expenses": "87.50"' in response.text
    assert fake.requests[1].input_items[-1]["type"] == "function_call_output"


def test_ai_created_amount_is_exact_decimal_and_tool_failure_cannot_claim_success(
    client: TestClient,
) -> None:
    _sign_up(client)
    account_id, category_id = _create_assistant_basics(client)
    today = _today().isoformat()
    conversation = client.post("/api/ai/conversations", json={}).json()
    fake = FakeAIProvider(
        [
            [
                ProviderEvent(
                    type="function_call",
                    function_call=FunctionCall(
                        "call_create",
                        "create_transaction",
                        json.dumps(
                            {
                                "account_id": account_id,
                                "category_id": category_id,
                                "movement_type": "EXPENSE",
                                "description": "Café",
                                "amount": "R$ 87,50",
                                "occurred_at": today,
                            }
                        ),
                    ),
                ),
                _completed(),
            ],
            [ProviderEvent(type="text_delta", text="Lançamento registrado."), _completed()],
            [
                ProviderEvent(
                    type="function_call",
                    function_call=FunctionCall(
                        "call_invalid",
                        "create_transaction",
                        json.dumps(
                            {
                                "account_id": "00000000-0000-0000-0000-000000000000",
                                "category_id": category_id,
                                "movement_type": "EXPENSE",
                                "description": "Inválido",
                                "amount": "25,00",
                                "occurred_at": today,
                            }
                        ),
                    ),
                ),
                _completed(),
            ],
        ]
    )
    _set_fake_provider(client, fake)

    success = client.post(
        f"/api/ai/conversations/{conversation['id']}/messages",
        json={"content": "Registre um café de R$ 87,50"},
    )
    transactions = client.get("/api/transactions").json()
    failure = client.post(
        f"/api/ai/conversations/{conversation['id']}/messages",
        json={"content": "Registre um lançamento"},
    )
    messages = client.get(f"/api/ai/conversations/{conversation['id']}").json()["messages"]

    assert success.status_code == 200
    assert transactions[-1]["amount"] == "87.50"
    assert failure.status_code == 200
    assert '"status": "error"' in failure.text
    assert "Não consegui concluir essa operação" in messages[-1]["content"]
    assert "Lançamento registrado" not in messages[-1]["content"]
    assert len(transactions) == 1


@pytest.mark.parametrize(
    ("content", "category_name", "amount", "description"),
    [
        (
            "Gastei 87 reais em combustível na moto.",
            "Combustível",
            "87.00",
            "Combustível na moto",
        ),
        ("Gastei 34 reais em alimentação.", "Alimentação", "34.00", "Alimentação"),
    ],
)
def test_clear_expense_is_registered_from_chat_without_model_or_form(
    client: TestClient,
    content: str,
    category_name: str,
    amount: str,
    description: str,
) -> None:
    _sign_up(client)
    _account_id, food_category_id = _create_assistant_basics(client)
    category_id = food_category_id
    if category_name == "Combustível":
        created_category = client.post(
            "/api/categories", json={"name": category_name, "type": "EXPENSE"}
        )
        assert created_category.status_code == 201
        category_id = created_category.json()["id"]
    conversation = client.post("/api/ai/conversations", json={}).json()
    fake = FakeAIProvider([])
    _set_fake_provider(client, fake)

    response = client.post(
        f"/api/ai/conversations/{conversation['id']}/messages",
        json={"content": content},
    )

    transactions = client.get("/api/transactions").json()
    messages = client.get(f"/api/ai/conversations/{conversation['id']}").json()["messages"]
    assert response.status_code == 200
    assert fake.requests == []
    assert '"model": "local-expense-parser-v1"' in response.text
    assert "Pronto, registrei R$" in response.text
    assert len(transactions) == 1
    assert transactions[0]["type"] == "EXPENSE"
    assert transactions[0]["amount"] == amount
    assert transactions[0]["category_id"] == category_id
    assert transactions[0]["description"] == description
    assert [message["role"] for message in messages] == ["USER", "ASSISTANT"]
    assert messages[-1]["structured_content"][0]["type"] == "transaction_card"


def test_clear_expense_duplicate_is_not_created_twice_and_missing_category_is_asked(
    client: TestClient,
) -> None:
    _sign_up(client)
    _create_assistant_basics(client)
    conversation = client.post("/api/ai/conversations", json={}).json()
    fake = FakeAIProvider([])
    _set_fake_provider(client, fake)
    message = "Gastei R$ 34,00 em alimentação."

    first = client.post(
        f"/api/ai/conversations/{conversation['id']}/messages", json={"content": message}
    )
    duplicate = client.post(
        f"/api/ai/conversations/{conversation['id']}/messages", json={"content": message}
    )
    missing_category = client.post(
        f"/api/ai/conversations/{conversation['id']}/messages",
        json={"content": "Gastei R$ 200."},
    )

    assert first.status_code == duplicate.status_code == missing_category.status_code == 200
    assert "Pronto, registrei" in first.text
    assert "não criei outro" in duplicate.text
    assert "categoria" in missing_category.text.casefold()
    assert len(client.get("/api/transactions").json()) == 1
    assert fake.requests == []


def test_category_answer_resolves_pending_expense_without_calling_model(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    _sign_up(client)
    _create_assistant_basics(client)
    created_category = client.post(
        "/api/categories", json={"name": "Combustível", "type": "EXPENSE"}
    )
    assert created_category.status_code == 201
    category_id = created_category.json()["id"]
    conversation = client.post("/api/ai/conversations", json={}).json()
    fake = FakeAIProvider([[ProviderEvent(type="text_delta", text="Resposta do modelo.")]])
    _set_fake_provider(client, fake)

    first = client.post(
        f"/api/ai/conversations/{conversation['id']}/messages",
        json={"content": "Gastei R$ 57 no carro."},
    )
    # The live conversation that exposed this bug predates clarification markers.
    with test_session_factory() as db:
        clarification = db.scalar(
            select(AIMessage).where(
                AIMessage.conversation_id == UUID(conversation["id"]),
                AIMessage.role == "ASSISTANT",
            )
        )
        assert clarification is not None
        clarification.structured_content = None
        db.commit()

    answer = client.post(
        f"/api/ai/conversations/{conversation['id']}/messages",
        json={"content": "Combustível"},
    )

    transactions = client.get("/api/transactions").json()
    messages = client.get(f"/api/ai/conversations/{conversation['id']}").json()["messages"]
    assert first.status_code == answer.status_code == 200
    assert "categoria" in first.text.casefold()
    assert '"model": "local-expense-parser-v1"' in answer.text
    assert "Pronto, registrei R$ 57,00" in answer.text
    assert fake.requests == []
    assert len(transactions) == 1
    assert transactions[0]["amount"] == "57.00"
    assert transactions[0]["category_id"] == category_id
    assert [message["role"] for message in messages] == [
        "USER",
        "ASSISTANT",
        "USER",
        "ASSISTANT",
    ]


def test_unregistered_category_answer_does_not_call_model_or_create_transaction(
    client: TestClient,
) -> None:
    _sign_up(client)
    client.post(
        "/api/accounts",
        json={
            "name": "Conta principal",
            "type": "CHECKING",
            "opening_balance": "0.00",
            "opening_balance_date": "2026-01-01",
        },
    )
    conversation = client.post("/api/ai/conversations", json={}).json()
    fake = FakeAIProvider([[ProviderEvent(type="text_delta", text="Resposta do modelo.")]])
    _set_fake_provider(client, fake)

    first = client.post(
        f"/api/ai/conversations/{conversation['id']}/messages",
        json={"content": "Gastei R$ 57 em combustível no carro."},
    )
    answer = client.post(
        f"/api/ai/conversations/{conversation['id']}/messages",
        json={"content": "Combustível"},
    )

    messages = client.get(f"/api/ai/conversations/{conversation['id']}").json()["messages"]
    assert first.status_code == answer.status_code == 200
    assert "não encontrei uma categoria" in first.text.casefold()
    assert "posso criar" in first.text.casefold()
    assert "posso criar" in answer.text.casefold()
    assert fake.requests == []
    assert client.get("/api/transactions").json() == []
    assert [message["role"] for message in messages] == [
        "USER",
        "ASSISTANT",
        "USER",
        "ASSISTANT",
    ]


def test_explicit_category_creation_resumes_pending_expense_in_chat(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    _sign_up(client)
    account = client.post(
        "/api/accounts",
        json={
            "name": "Conta principal",
            "type": "CHECKING",
            "opening_balance": "0.00",
            "opening_balance_date": "2026-01-01",
        },
    )
    assert account.status_code == 201
    conversation = client.post("/api/ai/conversations", json={}).json()
    fake = FakeAIProvider([])
    _set_fake_provider(client, fake)

    first = client.post(
        f"/api/ai/conversations/{conversation['id']}/messages",
        json={"content": "Gastei 97 reais de combustível no Carro"},
    )
    with test_session_factory() as db:
        clarification = db.scalar(
            select(AIMessage).where(
                AIMessage.conversation_id == UUID(conversation["id"]),
                AIMessage.role == "ASSISTANT",
            )
        )
        assert clarification is not None
        clarification.structured_content = None
        db.commit()
    follow_up = client.post(
        f"/api/ai/conversations/{conversation['id']}/messages",
        json={"content": "Crie a categoria Combustível"},
    )

    categories = client.get("/api/categories").json()
    transactions = client.get("/api/transactions").json()
    assert first.status_code == follow_up.status_code == 200
    assert "categoria" in first.text.casefold()
    assert "criei a categoria combustível" in follow_up.text.casefold()
    assert "registrei r$ 97,00" in follow_up.text.casefold()
    assert len(categories) == len(transactions) == 1
    assert categories[0]["name"] == "Combustível"
    assert categories[0]["type"] == "EXPENSE"
    assert transactions[0]["type"] == "EXPENSE"
    assert transactions[0]["amount"] == "97.00"
    assert transactions[0]["category_id"] == categories[0]["id"]
    assert fake.requests == []


def test_suggested_category_requires_chat_confirmation_before_creation(
    client: TestClient,
) -> None:
    _sign_up(client)
    account = client.post(
        "/api/accounts",
        json={
            "name": "Conta principal",
            "type": "CHECKING",
            "opening_balance": "0.00",
            "opening_balance_date": "2026-01-01",
        },
    )
    assert account.status_code == 201
    conversation = client.post("/api/ai/conversations", json={}).json()
    fake = FakeAIProvider([])
    _set_fake_provider(client, fake)

    suggested = client.post(
        f"/api/ai/conversations/{conversation['id']}/messages",
        json={"content": "Gastei 97 reais de combustível no Carro"},
    )
    before_confirmation = client.get("/api/transactions").json()
    confirmed = client.post(
        f"/api/ai/conversations/{conversation['id']}/messages",
        json={"content": "Sim"},
    )

    categories = client.get("/api/categories").json()
    transactions = client.get("/api/transactions").json()
    assert suggested.status_code == confirmed.status_code == 200
    assert "sugiro criar “combustível”" in suggested.text.casefold()
    assert "posso criar" in suggested.text.casefold()
    assert before_confirmation == []
    assert "criei a categoria combustível" in confirmed.text.casefold()
    assert "registrei r$ 97,00" in confirmed.text.casefold()
    assert len(categories) == len(transactions) == 1
    assert categories[0]["name"] == "Combustível"
    assert transactions[0]["amount"] == "97.00"
    assert fake.requests == []


def test_croissant_suggests_food_category_without_recording_before_confirmation(
    client: TestClient,
) -> None:
    _sign_up(client)
    client.post(
        "/api/accounts",
        json={
            "name": "Conta principal",
            "type": "CHECKING",
            "opening_balance": "0.00",
            "opening_balance_date": "2026-01-01",
        },
    )
    client.post("/api/categories", json={"name": "Combustível", "type": "EXPENSE"})
    conversation = client.post("/api/ai/conversations", json={}).json()
    fake = FakeAIProvider([])
    _set_fake_provider(client, fake)

    response = client.post(
        f"/api/ai/conversations/{conversation['id']}/messages",
        json={"content": "Gastei R$ 7,70 com croissant."},
    )

    assert response.status_code == 200
    assert "sugiro criar “alimentação”" in response.text.casefold()
    assert "posso criar" in response.text.casefold()
    assert client.get("/api/transactions").json() == []
    assert [category["name"] for category in client.get("/api/categories").json()] == [
        "Combustível"
    ]
    assert fake.requests == []


def test_category_confirmation_clause_uses_requested_food_category_once(
    client: TestClient,
) -> None:
    _sign_up(client)
    client.post(
        "/api/accounts",
        json={
            "name": "Conta principal",
            "type": "CHECKING",
            "opening_balance": "0.00",
            "opening_balance_date": "2026-01-01",
        },
    )
    fuel = client.post("/api/categories", json={"name": "Combustível", "type": "EXPENSE"})
    assert fuel.status_code == 201
    conversation = client.post("/api/ai/conversations", json={}).json()
    fake = FakeAIProvider([])
    _set_fake_provider(client, fake)

    first = client.post(
        f"/api/ai/conversations/{conversation['id']}/messages",
        json={"content": "Gastei R$ 7,70 com croissant."},
    )
    named_category = client.post(
        f"/api/ai/conversations/{conversation['id']}/messages",
        json={"content": "Lanche"},
    )
    confirmed = client.post(
        f"/api/ai/conversations/{conversation['id']}/messages",
        json={"content": "Pode criar lanche deve entrar como Alimentação"},
    )

    categories = client.get("/api/categories").json()
    transactions = client.get("/api/transactions").json()
    food = next((category for category in categories if category["name"] == "Alimentação"), None)
    assert first.status_code == named_category.status_code == confirmed.status_code == 200
    assert food is not None
    assert not any(category["name"].casefold().startswith("lanche") for category in categories)
    assert "criei a categoria alimentação" in confirmed.text.casefold()
    assert "registrei r$ 7,70" in confirmed.text.casefold()
    assert len(transactions) == 1
    assert transactions[0]["amount"] == "7.70"
    assert transactions[0]["description"] == "Croissant"
    assert transactions[0]["category_id"] == food["id"]
    assert fake.requests == []


def test_chat_detects_legacy_description_with_category_suffix_as_duplicate(
    client: TestClient,
) -> None:
    _sign_up(client)
    account_id, food_category_id = _create_assistant_basics(client)
    existing = client.post(
        "/api/transactions",
        json={
            "account_id": account_id,
            "category_id": food_category_id,
            "type": "EXPENSE",
            "description": "croissant Alimentação",
            "amount": "7.70",
            "occurred_at": _today().isoformat(),
        },
    )
    assert existing.status_code == 201
    conversation = client.post("/api/ai/conversations", json={}).json()
    fake = FakeAIProvider([])
    _set_fake_provider(client, fake)

    repeated = client.post(
        f"/api/ai/conversations/{conversation['id']}/messages",
        json={"content": "Gastei R$ 7,70 com croissant."},
    )

    transactions = client.get("/api/transactions").json()
    assert repeated.status_code == 200
    assert "já existe um lançamento igual" in repeated.text.casefold()
    assert len(transactions) == 1
    assert transactions[0]["description"] == "croissant Alimentação"
    assert fake.requests == []


def test_unrelated_sentence_is_not_treated_as_pending_category_name(
    client: TestClient,
) -> None:
    _sign_up(client)
    client.post(
        "/api/accounts",
        json={
            "name": "Conta principal",
            "type": "CHECKING",
            "opening_balance": "0.00",
            "opening_balance_date": "2026-01-01",
        },
    )
    conversation = client.post("/api/ai/conversations", json={}).json()
    fake = FakeAIProvider(
        [[ProviderEvent(type="text_delta", text="Teste de conexão recebido."), _completed()]]
    )
    _set_fake_provider(client, fake)

    first = client.post(
        f"/api/ai/conversations/{conversation['id']}/messages",
        json={"content": "Gastei R$ 7,70 com croissant."},
    )
    unrelated = client.post(
        f"/api/ai/conversations/{conversation['id']}/messages",
        json={"content": "Responda apenas: teste de conexão."},
    )

    assert first.status_code == unrelated.status_code == 200
    assert "teste de conexão recebido" in unrelated.text.casefold()
    assert "sugiro criar “responda apenas" not in unrelated.text.casefold()
    assert fake.requests
    assert client.get("/api/transactions").json() == []
    assert client.get("/api/categories").json() == []


def test_chat_category_creation_reuses_existing_category_without_duplicate(
    client: TestClient,
) -> None:
    _sign_up(client)
    account = client.post(
        "/api/accounts",
        json={
            "name": "Conta principal",
            "type": "CHECKING",
            "opening_balance": "0.00",
            "opening_balance_date": "2026-01-01",
        },
    )
    assert account.status_code == 201
    category = client.post("/api/categories", json={"name": "Transporte", "type": "EXPENSE"})
    assert category.status_code == 201
    conversation = client.post("/api/ai/conversations", json={}).json()
    fake = FakeAIProvider([])
    _set_fake_provider(client, fake)

    client.post(
        f"/api/ai/conversations/{conversation['id']}/messages",
        json={"content": "Gastei R$ 22 hoje."},
    )
    completed = client.post(
        f"/api/ai/conversations/{conversation['id']}/messages",
        json={"content": "Crie a categoria Transporte"},
    )

    categories = client.get("/api/categories").json()
    transactions = client.get("/api/transactions").json()
    assert completed.status_code == 200
    assert "registrei r$ 22,00" in completed.text.casefold()
    assert len(categories) == len(transactions) == 1
    assert categories[0]["id"] == category.json()["id"]
    assert transactions[0]["category_id"] == category.json()["id"]
    assert fake.requests == []


def test_correcting_recent_expense_updates_same_transaction_after_confirmation(
    client: TestClient,
) -> None:
    _sign_up(client)
    _create_assistant_basics(client)
    conversation = client.post("/api/ai/conversations", json={}).json()
    fake = FakeAIProvider([])
    _set_fake_provider(client, fake)

    created = client.post(
        f"/api/ai/conversations/{conversation['id']}/messages",
        json={"content": "Gastei R$ 100 em alimentação no mercado."},
    )
    transactions = client.get("/api/transactions").json()
    assert created.status_code == 200
    assert len(transactions) == 1
    transaction_id = transactions[0]["id"]

    fake.responses.append(
        [
            ProviderEvent(
                type="function_call",
                function_call=FunctionCall(
                    "call_update_correction",
                    "update_transaction",
                    json.dumps({"transaction_id": transaction_id, "amount": "120.00"}),
                ),
            ),
            _completed(),
        ]
    )
    corrected = client.post(
        f"/api/ai/conversations/{conversation['id']}/messages",
        json={"content": "Na verdade foram R$ 120."},
    )
    assert corrected.status_code == 200
    assert len(client.get("/api/transactions").json()) == 1
    assert client.get("/api/transactions").json()[0]["amount"] == "100.00"

    confirmation_id = next(
        json.loads(line.removeprefix("data: "))["items"][0]["tool_call_id"]
        for line in corrected.text.splitlines()
        if line.startswith("data: ") and '"tool_call_id"' in line
    )
    confirmed = client.post(
        f"/api/ai/conversations/{conversation['id']}/tool-calls/{confirmation_id}/confirm"
    )

    final_transactions = client.get("/api/transactions").json()
    assert confirmed.status_code == 200
    assert len(final_transactions) == 1
    assert final_transactions[0]["amount"] == "120.00"


def test_update_tool_waits_for_explicit_confirmation(client: TestClient) -> None:
    _sign_up(client)
    account_id, category_id = _create_assistant_basics(client)
    today = _today().isoformat()
    transaction = client.post(
        "/api/transactions",
        json={
            "account_id": account_id,
            "category_id": category_id,
            "type": "EXPENSE",
            "description": "Original",
            "amount": "10.00",
            "occurred_at": today,
        },
    ).json()
    conversation = client.post("/api/ai/conversations", json={}).json()
    fake = FakeAIProvider(
        [
            [
                ProviderEvent(
                    type="function_call",
                    function_call=FunctionCall(
                        "call_update",
                        "update_transaction",
                        json.dumps(
                            {"transaction_id": transaction["id"], "description": "Corrigido"}
                        ),
                    ),
                ),
                _completed(),
            ]
        ]
    )
    _set_fake_provider(client, fake)

    response = client.post(
        f"/api/ai/conversations/{conversation['id']}/messages",
        json={"content": "Corrija a descrição"},
    )
    transaction_before = client.get("/api/transactions").json()[0]
    structured = next(
        json.loads(line.removeprefix("data: "))["items"]
        for line in response.text.splitlines()
        if line.startswith("data: ") and '"items"' in line
    )
    confirmation_id = structured[0]["tool_call_id"]
    confirmed = client.post(
        f"/api/ai/conversations/{conversation['id']}/tool-calls/{confirmation_id}/confirm"
    )

    assert transaction_before["description"] == "Original"
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "SUCCEEDED", confirmed.json()
    assert client.get("/api/transactions").json()[0]["description"] == "Corrigido"


def test_ai_status_reports_plan_connection_without_returning_credentials(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _sign_up(client)
    monkeypatch.setattr(settings, "ai_provider", "chatgpt_plan")

    class ConnectedStore:
        def is_connected(self) -> bool:
            return True

    monkeypatch.setattr("app.ai.chatgpt_credentials", ConnectedStore())
    response = client.get("/api/ai/status")

    assert response.status_code == 200
    assert response.json()["configured"] is True
    assert response.json()["provider"] == "chatgpt_plan"
    assert set(response.json()) == {
        "configured",
        "provider",
        "fast_model",
        "smart_model",
        "diagnostics_enabled",
    }
    assert "access_token" not in response.text
    assert "refresh_token" not in response.text


def test_development_diagnostics_show_usage_without_messages_or_secrets(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _sign_up(client)
    monkeypatch.setattr(settings, "app_env", "development")
    monkeypatch.setattr(settings, "ai_provider", "chatgpt_plan")
    monkeypatch.setattr(settings, "ai_model_fast", "gpt-6-luna")
    secret = "sensitive-prompt-marker"
    conversation = client.post("/api/ai/conversations", json={}).json()
    _set_fake_provider(client, FakeAIProvider([[_completed(30, 6)]]))

    sent = client.post(
        f"/api/ai/conversations/{conversation['id']}/messages",
        json={"content": f"Não mostre isto nos diagnósticos: {secret}"},
    )
    diagnostics = client.get("/api/ai/diagnostics")
    rows = diagnostics.json()

    assert sent.status_code == 200
    assert diagnostics.status_code == 200
    assert len(rows) == 1
    row = rows[0]
    assert row["conversation_id"] == conversation["id"]
    assert row["model"] == settings.ai_model_fast
    assert row["status"] == "SUCCEEDED"
    assert row["duration_ms"] >= 0
    assert row["input_tokens"] == 30
    assert row["cached_input_tokens"] == 0
    assert row["output_tokens"] == 6
    assert row["estimated_cost_usd"] is None
    assert secret not in diagnostics.text
    assert client.cookies.get("finance_ai_session") not in diagnostics.text
    assert "content" not in row
    assert "user_id" not in row


def test_diagnostics_endpoint_is_hidden_outside_development(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _sign_up(client)
    monkeypatch.setattr(settings, "app_env", "production")

    response = client.get("/api/ai/diagnostics")

    assert response.status_code == 404


def test_missing_conversation_is_not_found(client: TestClient) -> None:
    _sign_up(client)

    assert (
        client.get("/api/ai/conversations/00000000-0000-0000-0000-000000000000").status_code == 404
    )
