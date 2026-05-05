from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"

load_dotenv(ENV_FILE)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(ENV_FILE), extra="ignore")

    node_env: str = Field(default="development", alias="NODE_ENV")
    port: int = Field(default=3000, alias="PORT")
    admin_password: str = Field(default="change-me", alias="ADMIN_PASSWORD")
    database_path: str = Field(default="./data/app.db", alias="DATABASE_PATH")
    static_dir: str | None = Field(default=None, alias="STATIC_DIR")

    claw_api_key: str | None = Field(default=None, alias="CLAW_API_KEY")
    claw_dashboard_cookie: str | None = Field(default=None, alias="CLAW_DASHBOARD_COOKIE")
    claw_workspace_id: str | None = Field(default=None, alias="CLAW_WORKSPACE_ID")
    claw_parent_mailbox_id: str | None = Field(default=None, alias="CLAW_PARENT_MAILBOX_ID")
    claw_root_prefix: str | None = Field(default=None, alias="CLAW_ROOT_PREFIX")
    claw_domain: str = Field(default="claw.163.com", alias="CLAW_DOMAIN")
    claw_accounts_json: str | None = Field(default=None, alias="CLAW_ACCOUNTS_JSON")

    telegram_bot_token: str | None = Field(default=None, alias="TELEGRAM_BOT_TOKEN")
    telegram_chat_id: str | None = Field(default=None, alias="TELEGRAM_CHAT_ID")
    telegram_api_base: str = Field(default="https://api.telegram.org", alias="TELEGRAM_API_BASE")
    telegram_enabled: bool = Field(default=False, alias="TELEGRAM_ENABLED")

    enable_ws_listeners: bool = Field(default=True, alias="ENABLE_WS_LISTENERS")

    @field_validator("database_path", "static_dir", "claw_accounts_json", mode="after")
    @classmethod
    def resolve_project_path(cls, value: str | None) -> str | None:
        if not value:
            return value
        path = Path(value)
        return str(path if path.is_absolute() else PROJECT_ROOT / path)

    @property
    def db_path(self) -> Path:
        return Path(self.database_path)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
