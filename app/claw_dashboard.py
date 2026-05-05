from __future__ import annotations

import re
from typing import Any

import httpx

from .runtime_config import require_account

DASHBOARD_ORIGIN = "https://claw.163.com"
BASE_URL = f"{DASHBOARD_ORIGIN}/mailserv-claw-dashboard/api/v1"
PUBLIC_BASE_URL = f"{DASHBOARD_ORIGIN}/mailserv-claw-dashboard/p/v1"


def _cookie_from_response(response: httpx.Response) -> str:
    cookies = []
    for header in response.headers.get_list("set-cookie"):
        part = header.split(";", 1)[0].strip()
        if part:
            cookies.append(part)
    return "; ".join(cookies)


def _extract_auth_url(command: str | None) -> str | None:
    if not command:
        return None
    match = re.search(r'--auth-url\s+"([^"]+)"', command)
    return match.group(1) if match else None


def _optional_number(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str) and value.strip():
        try:
            return int(value)
        except ValueError:
            return None
    return None


def normalize_mailbox(raw: dict[str, Any], account_id: int | None = None) -> dict[str, Any]:
    email = str(raw.get("email") or "").strip().lower()
    install_command = raw.get("installCommand") or raw.get("install_command")
    return {
        "id": str(raw.get("id")),
        "email": email,
        "prefix": str(raw.get("prefix") or email.split("@")[0]),
        "display_name": raw.get("displayName") or raw.get("display_name"),
        "account_id": account_id,
        "status": raw.get("status") or "active",
        "openclaw_status": raw.get("openclawStatus") or raw.get("openclaw_status"),
        "install_command": install_command,
        "auth_url": raw.get("authUrl") or raw.get("auth_url") or _extract_auth_url(install_command),
        "comm_level": _optional_number(raw.get("commLevel") or raw.get("comm_level")),
        "ext_receive_type": _optional_number(raw.get("extReceiveType") or raw.get("ext_receive_type")),
        "ext_send_type": _optional_number(raw.get("extSendType") or raw.get("ext_send_type")),
    }


async def parse_dashboard_response(response: httpx.Response) -> Any:
    text = response.text
    if not text.strip():
        if response.is_error:
            raise RuntimeError(f"Claw dashboard error: HTTP {response.status_code}")
        return None
    try:
        body = response.json()
    except ValueError as exc:
        raise RuntimeError(f"Claw dashboard returned non-JSON response: HTTP {response.status_code}") from exc
    if response.is_error or body.get("success") is not True or body.get("code") != 200:
        raise RuntimeError(f"Claw dashboard error: {body.get('message') or response.reason_phrase}")
    return body.get("result")


def _headers(account: dict) -> dict[str, str]:
    cookie = account.get("dashboard_cookie")
    if not cookie:
        raise RuntimeError("dashboard_cookie is required for mailbox management")
    return {
        "accept": "application/json, text/plain, */*",
        "content-type": "application/json",
        "cookie": cookie,
    }


async def send_login_code(email: str) -> None:
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            f"{PUBLIC_BASE_URL}/auth/email/send-code",
            headers={"accept": "application/json, text/plain, */*", "referer": f"{DASHBOARD_ORIGIN}/projects/dashboard/"},
            json={"email": email},
        )
    await parse_dashboard_response(response)


async def verify_login_code(email: str, code: str) -> str:
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            f"{PUBLIC_BASE_URL}/auth/email/verify-code",
            headers={"accept": "application/json, text/plain, */*", "referer": f"{DASHBOARD_ORIGIN}/projects/dashboard/"},
            json={"email": email, "code": code},
        )
    await parse_dashboard_response(response)
    cookie = _cookie_from_response(response)
    if not cookie:
        raise RuntimeError("Claw login did not return a session cookie")
    return cookie


async def get_auth_me(cookie: str) -> dict[str, Any] | None:
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(f"{BASE_URL}/auth/me", headers={"accept": "application/json", "cookie": cookie})
    return await parse_dashboard_response(response)


async def list_workspaces(cookie: str) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(f"{BASE_URL}/workspaces", headers={"accept": "application/json", "cookie": cookie})
    result = await parse_dashboard_response(response)
    return result.get("workspaces", []) if isinstance(result, dict) else []


async def list_api_keys(cookie: str) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(f"{BASE_URL}/api-keys", headers={"accept": "application/json", "cookie": cookie})
    result = await parse_dashboard_response(response)
    if isinstance(result, list):
        candidates = result
    elif isinstance(result, dict):
        candidates = result.get("apiKeys") or result.get("items") or []
    else:
        candidates = []
    return [item for item in candidates if isinstance(item, dict) and isinstance(item.get("apiKey"), str)]


async def list_dashboard_mailboxes(account_id: int | None = None) -> list[dict[str, Any]]:
    account = require_account(account_id)
    workspace_id = account.get("workspace_id")
    if not workspace_id:
        raise RuntimeError("workspace_id is required for mailbox sync")
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            f"{BASE_URL}/mailboxes",
            params={"workspaceId": workspace_id},
            headers={"accept": "application/json", "cookie": account.get("dashboard_cookie") or ""},
        )
    result = await parse_dashboard_response(response)
    raw_items: list[dict[str, Any]] = []
    if isinstance(result, dict) and result.get("mailbox"):
        raw_items.append(result["mailbox"])
        raw_items.extend(result["mailbox"].get("subMailboxes") or [])
    elif isinstance(result, dict):
        raw_items = result.get("items") or result.get("list") or result.get("mailboxes") or []
    elif isinstance(result, list):
        raw_items = result
    return [normalize_mailbox(item, account["id"]) for item in raw_items]


async def create_mailbox(suffix: str, account_id: int | None = None) -> dict[str, Any]:
    normalized = suffix.strip().lower()
    if not re.fullmatch(r"[a-z0-9]{1,32}", normalized):
        raise ValueError("suffix must contain 1-32 lowercase letters or digits")
    account = require_account(account_id)
    if not account.get("dashboard_cookie"):
        email = f"{account.get('root_prefix')}.{normalized}@{account.get('domain') or 'claw.163.com'}"
        return normalize_mailbox({
            "id": f"local:{account['id']}:{email}",
            "email": email,
            "prefix": email.split("@", 1)[0],
            "displayName": normalized,
            "status": "active",
        }, account["id"])
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"{BASE_URL}/mailboxes",
            headers=_headers(account),
            json={
                "prefix": normalized,
                "displayName": normalized,
                "mailboxType": "sub",
                "workspaceId": account.get("workspace_id"),
                "parentMailboxId": account.get("parent_mailbox_id"),
            },
        )
    return normalize_mailbox(await parse_dashboard_response(response), account["id"])


async def delete_mailbox(mailbox_id: str, account_id: int | None = None) -> None:
    account = require_account(account_id)
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"{BASE_URL}/mailboxes/delete",
            params={"id": mailbox_id},
            headers={"accept": "application/json", "cookie": account.get("dashboard_cookie") or ""},
        )
    await parse_dashboard_response(response)


async def update_mailbox_communication_settings(mailbox_id: str, payload: dict[str, int], account_id: int | None = None) -> None:
    account = require_account(account_id)
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"{BASE_URL}/mailboxes/comm-settings",
            params={"id": mailbox_id},
            headers=_headers(account),
            json=payload,
        )
    await parse_dashboard_response(response)
