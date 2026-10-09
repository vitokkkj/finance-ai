from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "production"
    database_url: str
    session_cookie_name: str = "finance_ai_session"
    session_cookie_secure: bool = True
    session_ttl_hours: int = 168
    login_rate_limit_attempts: int = 5
    login_rate_limit_window_seconds: int = 300
    ai_provider: Literal["ollama", "chatgpt_plan"] = "chatgpt_plan"
    chatgpt_auth_dir: str = "/home/app/.config/sophia"
    ai_model_fast: str = "qwen3:1.7b"
    ai_model_smart: str = "qwen3:1.7b"
    ollama_base_url: str = "http://ollama:11434"
    ollama_context_length: int = Field(default=4096, ge=512, le=40960)
    ollama_timeout_seconds: int = Field(default=900, ge=30, le=1800)

    model_config = SettingsConfigDict(case_sensitive=False, extra="ignore")


settings = Settings()
