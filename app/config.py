"""Configuração via variáveis de ambiente (.env). Nada de segredo hardcoded."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # OpenRouter — a chave pode vir por request (a do usuário, do navegador) OU daqui.
    openrouter_api_key: str = ""
    openrouter_base: str = "https://openrouter.ai/api/v1"
    default_model: str = "openai/gpt-4.1-mini"
    site_title: str = "VTz LLM Backend"

    # CORS — domínios do site que podem chamar este backend (separados por vírgula).
    allowed_origins: str = "*"

    # Conectores (precisam das chaves do usuário — ver README).
    notion_token: str = ""

    request_timeout: float = 60.0

    @property
    def origins(self) -> list[str]:
        items = [o.strip() for o in self.allowed_origins.split(",") if o.strip()]
        return items or ["*"]


settings = Settings()
