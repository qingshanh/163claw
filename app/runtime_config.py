from __future__ import annotations

from . import db
from .config import settings

LEGACY_AUTH_SETTING_KEYS = [
    "claw.apiKey",
    "claw.dashboardCookie",
    "claw.userEmail",
    "claw.workspaceId",
    "claw.workspaceName",
    "claw.parentMailboxId",
    "claw.rootPrefix",
    "claw.domain",
]


def account_status(account: dict | None) -> dict:
    if not account:
        return {
            "connected": False,
            "hasApiKey": False,
            "hasDashboardCookie": False,
            "userEmail": None,
            "workspaceId": None,
            "workspaceName": None,
            "parentMailboxId": None,
            "rootPrefix": None,
            "domain": None,
            "apiKeyPrefix": None,
            "apiKeySuffix": None,
            "accountId": None,
            "accountName": None,
            "telegramEnabled": False,
            "telegramConfigured": False,
        }
    api_key = account.get("api_key")
    cookie = account.get("dashboard_cookie")
    connected = bool(
        api_key
        and cookie
        and account.get("workspace_id")
        and account.get("parent_mailbox_id")
        and account.get("root_prefix")
        and account.get("domain")
    )
    return {
        "connected": connected,
        "hasApiKey": bool(api_key),
        "hasDashboardCookie": bool(cookie),
        "userEmail": account.get("user_email"),
        "workspaceId": account.get("workspace_id"),
        "workspaceName": account.get("workspace_name"),
        "parentMailboxId": account.get("parent_mailbox_id"),
        "rootPrefix": account.get("root_prefix"),
        "domain": account.get("domain"),
        "apiKeyPrefix": api_key[:10] if api_key else None,
        "apiKeySuffix": api_key[-4:] if api_key else None,
        "accountId": account.get("id"),
        "accountName": account.get("name"),
        "telegramEnabled": bool(account.get("telegram_enabled")) or settings.telegram_enabled,
        "telegramConfigured": bool(
            (account.get("telegram_bot_token") or settings.telegram_bot_token)
            and (account.get("telegram_chat_id") or settings.telegram_chat_id)
        ),
    }


def get_default_account_status() -> dict:
    return account_status(db.get_default_account())


def require_account(account_id: int | None = None) -> dict:
    account = db.get_account(account_id) if account_id else db.get_default_account()
    if not account:
        raise RuntimeError("No Claw account is configured; add an account first")
    return account


def require_mail_account(mailbox_email: str) -> dict:
    account = db.get_account_for_mailbox(mailbox_email)
    if not account or not account.get("api_key"):
        raise RuntimeError(f"No API key configured for {mailbox_email}")
    return account


def clear_legacy_auth_settings() -> None:
    db.delete_settings(LEGACY_AUTH_SETTING_KEYS)
