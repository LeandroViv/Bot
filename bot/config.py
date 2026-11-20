"""Configuration management using Pydantic Settings."""

from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Bot
    bot_token: str = Field(..., description="Telegram Bot Token from @BotFather")
    bot_username: str = Field(default="", description="Bot username without @")

    # Database
    database_url: str = Field(
        default="sqlite+aiosqlite:///./data/bot.db",
        description="SQLAlchemy async database URL",
    )

    # External API
    external_api_base_url: str = Field(
        default="https://api.example.com",
        description="Base URL for external API",
    )
    external_api_key: str = Field(default="", description="API key for external service")
    external_api_timeout: int = Field(default=30, description="Request timeout in seconds")

    # Webhook
    webhook_url: str = Field(default="", description="Full webhook URL for production")
    webhook_secret: str = Field(default="", description="Secret token for webhook validation")
    webhook_port: int = Field(default=8080, description="Port for webhook server")
    webhook_host: str = Field(default="0.0.0.0", description="Host for webhook server")

    # Logging
    log_level: str = Field(default="INFO", description="Logging level")
    log_format: str = Field(default="json", description="Log format: json or console")

    # Scheduler
    scheduler_timezone: str = Field(default="UTC", description="Timezone for scheduled jobs")

    @property
    def is_webhook_mode(self) -> bool:
        """Check if running in webhook mode."""
        return bool(self.webhook_url)

    @property
    def data_dir(self) -> Path:
        """Get data directory path."""
        path = Path("./data")
        path.mkdir(parents=True, exist_ok=True)
        return path


settings = Settings()