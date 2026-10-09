from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_serializer, field_validator


class ConversationCreate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        title = value.strip()
        if not title:
            raise ValueError("Informe um título para a conversa.")
        return title


class ConversationUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=120)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        title = value.strip()
        if not title:
            raise ValueError("Informe um título para a conversa.")
        return title


class MessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=4000)

    @field_validator("content")
    @classmethod
    def normalize_content(cls, value: str) -> str:
        content = value.strip()
        if not content:
            raise ValueError("Escreva uma mensagem antes de enviar.")
        return content


class AIMessageResponse(BaseModel):
    id: UUID
    role: Literal["USER", "ASSISTANT"]
    content: str
    structured_content: list[dict[str, object]] | None
    created_at: datetime


class ConversationResponse(BaseModel):
    id: UUID
    title: str
    created_at: datetime
    updated_at: datetime


class ConversationDetail(ConversationResponse):
    messages: list[AIMessageResponse]


class AIStatusResponse(BaseModel):
    configured: bool
    provider: Literal["ollama", "chatgpt_plan"]
    fast_model: str
    smart_model: str
    diagnostics_enabled: bool


class AIInteractionDiagnostic(BaseModel):
    id: UUID
    created_at: datetime
    conversation_id: UUID
    model: str | None
    tool_name: str | None
    status: str
    duration_ms: int | None
    input_tokens: int | None
    cached_input_tokens: int | None
    output_tokens: int | None
    estimated_cost_usd: Decimal | None
    error_summary: str | None

    @field_serializer("estimated_cost_usd")
    def serialize_cost(self, value: Decimal | None) -> str | None:
        return format(value, ".8f") if value is not None else None


class AIUsageResponse(BaseModel):
    calls_today: int
    input_tokens_today: int
    output_tokens_today: int
    cost_usd_today: Decimal | None
    calls_month: int
    input_tokens_month: int
    output_tokens_month: int
    cost_usd_month: Decimal | None

    @field_serializer("cost_usd_today", "cost_usd_month")
    def serialize_cost(self, value: Decimal | None) -> str | None:
        return format(value, ".8f") if value is not None else None


class AIMemoryWrite(BaseModel):
    content: str = Field(min_length=1, max_length=500)

    @field_validator("content")
    @classmethod
    def normalize_content(cls, value: str) -> str:
        content = value.strip()
        if not content:
            raise ValueError("Escreva uma preferência antes de salvar.")
        return content


class AIMemoryResponse(BaseModel):
    id: UUID
    content: str
    created_at: datetime


class ToolConfirmationResponse(BaseModel):
    id: UUID
    status: Literal["SUCCEEDED", "FAILED", "CANCELLED"]
    result: dict[str, object]
