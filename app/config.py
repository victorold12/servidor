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

    # Token de acesso (opcional). Setado como env var no Render/servidor — NUNCA
    # pelo site. Sem ele, o backend fica aberto (ok só em uso 100% local).
    # Com ele, toda chamada (exceto /api/health) exige o header X-Backend-Token.
    backend_token: str = ""

    # Conectores (precisam das chaves do usuário — todas gratuitas. Ver README).
    notion_token: str = ""
    figma_token: str = ""
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/api/connectors/google/callback"
    replicate_api_key: str = ""

    # Rate limit por IP. Generoso porque é single-user e uma interação do painel
    # já faz várias chamadas; ver o comentário em security.py.
    rate_limit: int = 600
    rate_window: float = 300.0

    # Backup automático (app/autobackup.py). Desligado por padrão: escrever no
    # disco de alguém sem ele pedir não é papel do programa. BACKUP_EVERY_HOURS>0
    # liga o agendamento; BACKUP_DIR vazio = pasta "backups" ao lado do banco.
    backup_every_hours: float = 0.0
    backup_keep: int = 14
    backup_dir: str = ""

    # Discord/Telegram (Seção 5). Sem MESSAGING_SECRET o webhook fica desligado;
    # sem allowlist, ele recusa tudo — negar é o padrão seguro aqui.
    messaging_secret: str = ""
    telegram_bot_token: str = ""
    telegram_allowed_chats: str = ""      # ids separados por vírgula
    discord_webhook_url: str = ""
    discord_allowed_users: str = ""       # ids separados por vírgula

    # Fallback LLM local (Seção 5): sem internet ou sem chave, cai num modelo
    # rodando na máquina. Endpoint compatível com a API da OpenAI — o Ollama
    # expõe isso em /v1. Vazio = sem fallback (falha honesta em vez de silêncio).
    ollama_base: str = ""
    ollama_model: str = ""

    # Busca semântica na memória. Endpoint compatível com a API da OpenAI
    # (/embeddings): OpenAI, HuggingFace TEI, Ollama, LM Studio, vLLM.
    # Sem isto, a busca cai em escore léxico e diz que caiu.
    embeddings_base: str = ""
    embeddings_model: str = ""
    embeddings_key: str = ""

    request_timeout: float = 60.0

    @property
    def origins(self) -> list[str]:
        items = [o.strip() for o in self.allowed_origins.split(",") if o.strip()]
        return items or ["*"]


settings = Settings()
