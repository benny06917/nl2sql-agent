
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Secrets
    groq_api_key: str = ""           

    # Model
    model: str = "qwen/qwen3.8-27b"
    temperature: float = 0.0         

    # Agent behaviour
    max_retries: int = 2            
    max_display_rows: int = 50       
    use_critic: bool = True          

    # Data
    db_path: str = "data/retail.db"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()


def get_llm(temperature: float | None = None):

    from langchain_groq import ChatGroq

    if not settings.groq_api_key:
        raise RuntimeError(
            "GROQ_API_KEY is not set. Copy .env.example to .env and add your key."
        )
    return ChatGroq(
        model=settings.model,
        temperature=settings.temperature if temperature is None else temperature,
        api_key=settings.groq_api_key,
    )
