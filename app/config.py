from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"
CONFIG_FILE = Path(os.environ.get("CONFIG_JSON", PROJECT_ROOT / "config.json"))
if not CONFIG_FILE.is_absolute():
    CONFIG_FILE = PROJECT_ROOT / CONFIG_FILE

_ORIGINAL_ENV = dict(os.environ)
load_dotenv(ENV_FILE)


def _env_string(value: Any) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    return str(value)


def _set_env_if_unset(key: str, value: Any) -> None:
    if value is None or value == "":
        return
    if key in _ORIGINAL_ENV:
        return
    os.environ[key] = _env_string(value)


def _load_json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[config] failed to load {path}: {exc}")
        return {}
    return data if isinstance(data, dict) else {}


def read_config_file(path: Path | str = CONFIG_FILE) -> dict[str, Any]:
    return _load_json_file(Path(path))


def save_config_file(data: dict[str, Any], path: Path | str = CONFIG_FILE) -> None:
    target = Path(path)
    if not target.is_absolute():
        target = PROJECT_ROOT / target
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def _load_config_json_defaults() -> None:
    data = read_config_file()
    app = data.get("app") if isinstance(data.get("app"), dict) else {}
    telegram = data.get("telegram") if isinstance(data.get("telegram"), dict) else {}
    claw = data.get("claw") if isinstance(data.get("claw"), dict) else {}

    _set_env_if_unset("NODE_ENV", app.get("nodeEnv") or app.get("node_env"))
    _set_env_if_unset("PORT", app.get("port"))
    _set_env_if_unset("ADMIN_PASSWORD", app.get("adminPassword") or app.get("admin_password"))
    _set_env_if_unset("DATABASE_PATH", app.get("databasePath") or app.get("database_path"))
    _set_env_if_unset("STATIC_DIR", app.get("staticDir") or app.get("static_dir"))
    _set_env_if_unset("ENABLE_WS_LISTENERS", app.get("enableWsListeners") if "enableWsListeners" in app else app.get("enable_ws_listeners"))

    _set_env_if_unset("TELEGRAM_ENABLED", telegram.get("enabled"))
    _set_env_if_unset("TELEGRAM_BOT_TOKEN", telegram.get("botToken") or telegram.get("bot_token"))
    _set_env_if_unset("TELEGRAM_CHAT_ID", telegram.get("chatId") or telegram.get("chat_id"))
    _set_env_if_unset("TELEGRAM_API_BASE", telegram.get("apiBase") or telegram.get("api_base"))

    _set_env_if_unset("CLAW_API_KEY", claw.get("apiKey") or claw.get("api_key"))
    _set_env_if_unset("CLAW_DASHBOARD_COOKIE", claw.get("dashboardCookie") or claw.get("dashboard_cookie"))
    _set_env_if_unset("CLAW_WORKSPACE_ID", claw.get("workspaceId") or claw.get("workspace_id"))
    _set_env_if_unset("CLAW_PARENT_MAILBOX_ID", claw.get("parentMailboxId") or claw.get("parent_mailbox_id"))
    _set_env_if_unset("CLAW_ROOT_PREFIX", claw.get("rootPrefix") or claw.get("root_prefix"))
    _set_env_if_unset("CLAW_DOMAIN", claw.get("domain"))

    if "CLAW_ACCOUNTS_JSON" not in _ORIGINAL_ENV:
        os.environ["CLAW_ACCOUNTS_JSON"] = str(CONFIG_FILE)


_load_config_json_defaults()


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
