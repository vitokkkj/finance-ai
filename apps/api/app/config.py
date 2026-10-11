from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "production"
    app_component: Literal["api", "worker"] = "api"
    database_url: str
    session_cookie_name: str = "finance_ai_session"
    session_cookie_secure: bool = True
    session_ttl_hours: int = Field(default=24, ge=1, le=168)
    login_rate_limit_attempts: int = Field(default=5, ge=3, le=20)
    login_rate_limit_window_seconds: int = Field(default=300, ge=60, le=3600)
    initial_setup_token: str | None = None
    owner_totp_secret: str | None = None
    ai_provider: Literal["ollama", "chatgpt_plan"] = "chatgpt_plan"
    chatgpt_auth_dir: str = "/home/app/.config/sophia"
    ai_model_fast: str = "qwen3:1.7b"
    ai_model_smart: str = "qwen3:1.7b"
    ollama_base_url: str = "http://ollama:11434"
    ollama_context_length: int = Field(default=4096, ge=512, le=40960)
    ollama_timeout_seconds: int = Field(default=900, ge=30, le=1800)

    model_config = SettingsConfigDict(case_sensitive=False, extra="ignore")

    @model_validator(mode="after")
    def require_public_runtime_security(self) -> "Settings":
        if self.app_env.casefold() == "production":
            if not self.session_cookie_secure:
                raise ValueError("SESSION_COOKIE_SECURE precisa estar ativado em produção.")
            if self.session_ttl_hours > 24:
                raise ValueError("SESSION_TTL_HOURS não pode passar de 24 horas em produção.")
            if self.app_component == "api":
                secret = (self.owner_totp_secret or "").strip().upper()
                valid_base32 = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567="
                if len(secret.rstrip("=")) < 32 or any(
                    char not in valid_base32 for char in secret
                ):
                    raise ValueError(
                        "OWNER_TOTP_SECRET precisa ser uma chave Base32 aleatória com ao menos "
                        "32 caracteres."
                    )
        return self


settings = Settings()
