import os
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    llm_provider: str = "openai"  # "openai", "gigachat", "offline"
    llm_api_key: str = ""
    llm_model: str = "gpt-4o-mini"
    llm_timeout_sec: int = 10
    llm_base_url: str | None = None

    # Sber GigaChat settings
    gigachat_auth_key: str = ""
    gigachat_scope: str = "GIGACHAT_API_PERS"
    gigachat_model: str = "GigaChat-2-Max"

    stt_provider: str = "local"
    stt_model: str = "small"
    stt_language: str = "ru"

    tts_provider: str = "edge"
    tts_voice: str = "ru-RU-DmitryNeural"

    tts_output_dir: str = "./data/tts"
    db_path: str = "./data/sqlite.db"

    app_host: str = "0.0.0.0"
    app_port: int = 8000
    tz: str = "Europe/Moscow"

    def get_gigachat_key(self) -> str:
        return (
            self.gigachat_auth_key
            or os.environ.get("Authorization_key", "")
            or os.environ.get("GIGACHAT_AUTH_KEY", "")
        ).strip()


settings = Settings()
