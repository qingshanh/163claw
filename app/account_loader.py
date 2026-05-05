from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_accounts_json(path: str | Path) -> list[dict[str, Any]]:
    source = Path(path)
    data = json.loads(source.read_text(encoding="utf-8"))
    raw_accounts = data.get("accounts") if isinstance(data, dict) else data
    if not isinstance(raw_accounts, list):
        raise ValueError("accounts json must be a list or contain an accounts list")
    accounts: list[dict[str, Any]] = []
    for raw in raw_accounts:
        if not isinstance(raw, dict):
            continue
        api_key = raw.get("apiKey") or raw.get("api_key")
        user = raw.get("user") or raw.get("user_email") or raw.get("email")
        if not api_key or not user:
            continue
        root, domain = _split_email(user)
        accounts.append({
            "name": raw.get("name") or root,
            "user_email": user,
            "registered_email": raw.get("registeredEmail") or raw.get("registered_email"),
            "api_key": api_key,
            "dashboard_cookie": raw.get("dashboardCookie") or raw.get("dashboard_cookie"),
            "workspace_id": raw.get("workspaceId") or raw.get("workspace_id"),
            "workspace_name": raw.get("workspaceName") or raw.get("workspace_name"),
            "parent_mailbox_id": raw.get("parentMailboxId") or raw.get("parent_mailbox_id"),
            "root_prefix": raw.get("rootPrefix") or raw.get("root_prefix") or root,
            "domain": raw.get("domain") or domain,
            "telegram_enabled": bool(raw.get("telegramEnabled") or raw.get("telegram_enabled")),
            "telegram_bot_token": raw.get("telegramBotToken") or raw.get("telegram_bot_token"),
            "telegram_chat_id": raw.get("telegramChatId") or raw.get("telegram_chat_id"),
            "telegram_api_base": raw.get("telegramApiBase") or raw.get("telegram_api_base"),
            "users": _users(raw, user),
        })
    return accounts


def _split_email(email: str) -> tuple[str, str]:
    if "@" not in email:
        return email, "claw.163.com"
    root, domain = email.strip().lower().split("@", 1)
    return root, domain


def _users(raw: dict[str, Any], user: str) -> list[str]:
    if not isinstance(raw.get("users"), list):
        return []
    users = raw.get("users") or []
    result = [str(item).strip().lower() for item in users if str(item).strip()]
    if raw.get("includePrimary", True) or raw.get("include_primary", True):
        result.insert(0, user.strip().lower())
    return list(dict.fromkeys(result))
