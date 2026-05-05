from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, AsyncIterator

import httpx

from .config import settings
from .runtime_config import require_mail_account

CLAW_ORIGIN = settings.claw_origin.rstrip("/")
TOKEN_URL = f"{CLAW_ORIGIN}/claw-api-gateway/open/v1/mail/auth/token"
IM_TOKEN_URL = f"{CLAW_ORIGIN}/claw-api-gateway/open/v1/mail/auth/im-token"

FOLDER_IDS = {
    "INBOX": 1,
    "Inbox": 1,
    "inbox": 1,
    "Trash": 4,
    "Deleted": 4,
}


@dataclass
class Token:
    value: str
    expires_at: float


class ClawMailClient:
    def __init__(self, account: dict, user: str):
        self.account = account
        self.user = user.strip().lower()
        self.api_key = account["api_key"]
        self.access_token: Token | None = None
        self.im_token: Token | None = None
        self.base_url = f"{CLAW_ORIGIN}/claw-api-gateway/api/coremail"

    async def ensure_token(self) -> str:
        if self.access_token and self.access_token.expires_at - time.time() > 60:
            return self.access_token.value
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                TOKEN_URL,
                headers={"authorization": f"Bearer {self.api_key}", "content-type": "application/json"},
                json={"uid": self.user},
            )
        data = response.json()
        if data.get("success") is False or data.get("code") not in (None, 200, "S_OK"):
            raise RuntimeError(f"failed to obtain Claw access token: {data.get('message') or data.get('code') or data}")
        result = data.get("result") or {}
        token = result.get("accessToken")
        expires = result.get("expiresIn")
        if not token or not expires:
            raise RuntimeError(f"failed to obtain Claw access token: {data.get('message') or 'missing accessToken'}")
        self.access_token = Token(token, time.time() + int(expires))
        return token

    async def ensure_im_token(self) -> str:
        if self.im_token and self.im_token.expires_at - time.time() > 60:
            return self.im_token.value
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                IM_TOKEN_URL,
                headers={"authorization": f"Bearer {self.api_key}", "content-type": "application/json"},
                json={"uid": self.user},
            )
        data = response.json()
        if data.get("success") is not True:
            raise RuntimeError(f"failed to obtain IM token: {data.get('message') or 'unknown error'}")
        result = data.get("result") or {}
        token = result.get("accessToken")
        if not token:
            raise RuntimeError("failed to obtain IM token: missing accessToken")
        expires = int(result.get("expiresIn") or 1800)
        self.im_token = Token(token, time.time() + expires)
        return token

    async def call(self, func: str, payload: dict[str, Any] | None = None) -> Any:
        token = await self.ensure_token()
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{self.base_url}/proxy",
                params={"uid": self.user, "func": func},
                headers={"authorization": f"Bearer {token}", "content-type": "application/json"},
                json=payload or {},
            )
        if response.is_error:
            raise RuntimeError(f"Claw mail request failed: HTTP {response.status_code}")
        data = response.json()
        if data.get("code") != "S_OK":
            raise RuntimeError(f"Claw mail error: {data.get('code') or data.get('message')}")
        return data.get("var")

    async def stream(self, func: str, params: dict[str, Any]) -> tuple[AsyncIterator[bytes], str, str]:
        token = await self.ensure_token()
        client = httpx.AsyncClient(timeout=300)
        request = client.build_request(
            "GET",
            f"{self.base_url}/proxy",
            params={"uid": self.user, "func": func, **params},
            headers={"authorization": f"Bearer {token}"},
        )
        response = await client.send(request, stream=True)
        if response.is_error:
            await client.aclose()
            raise RuntimeError(f"Claw stream failed: HTTP {response.status_code}")
        content_type = response.headers.get("content-type") or "application/octet-stream"
        filename = _filename_from_disposition(response.headers.get("content-disposition")) or "attachment"

        async def iterator() -> AsyncIterator[bytes]:
            try:
                async for chunk in response.aiter_bytes():
                    yield chunk
            finally:
                await response.aclose()
                await client.aclose()

        return iterator(), content_type, filename

    async def list_messages(self, fid: str | int = "INBOX", start: int = 0, limit: int = 100) -> list[dict[str, Any]]:
        folder = FOLDER_IDS.get(str(fid), fid)
        rows = await self.call("mbox:listMessages", {"fid": folder, "order": "date", "desc": True, "start": start, "limit": limit})
        return [_summary(row) for row in (rows or [])]

    async def read_mail(self, provider_id: str, mark_read: bool = False) -> dict[str, Any]:
        raw = await self.call(
            "mbox:readMessage",
            {"id": provider_id, "mode": "html", "markRead": mark_read, "header": True, "securityLevel": 1, "filterLinks": False, "filterImages": False},
        )
        return _detail(provider_id, raw or {})

    async def send_mail(self, data: dict[str, Any]) -> dict[str, str]:
        attrs = {
            "to": data["to"],
            "subject": data.get("subject") or "",
            "content": data.get("body") or "",
            "isHtml": bool(data.get("html")),
            "priority": 3,
            "saveSentCopy": True,
            "account": self.user,
        }
        if data.get("cc"):
            attrs["cc"] = data["cc"]
        if data.get("bcc"):
            attrs["bcc"] = data["bcc"]
        compose = await self.call("mbox:compose", {"action": "continue", "attrs": attrs})
        compose_id = compose if isinstance(compose, str) else (compose or {}).get("id")
        if not compose_id:
            raise RuntimeError("compose did not return a compose id")
        await self.call("mbox:compose", {"id": compose_id, "action": "deliver", "attrs": attrs})
        return {"status": "sent"}

    async def reply_mail(self, data: dict[str, Any]) -> dict[str, str]:
        await self.call(
            "mbox:replyMessage",
            {
                "id": data["id"],
                "toAll": bool(data.get("toAll")),
                "withAttachments": False,
                "action": "deliver",
                "attrs": {"content": data.get("body") or "", "isHtml": bool(data.get("html")), "saveSentCopy": True},
            },
        )
        return {"status": "sent"}

    async def move_messages(self, ids: list[str], target: str | int) -> None:
        await self.call("mbox:updateMessageInfos", {"ids": ids, "attrs": {"fid": FOLDER_IDS.get(str(target), target)}})


clients: dict[tuple[int, str], ClawMailClient] = {}


def get_mail_client(email: str) -> ClawMailClient:
    account = require_mail_account(email)
    key = (account["id"], email.strip().lower())
    if key not in clients:
        clients[key] = ClawMailClient(account, key[1])
    return clients[key]


def reset_mail_clients() -> None:
    clients.clear()


async def send_mail(data: dict[str, Any]) -> dict[str, str]:
    if not data.get("to"):
        raise ValueError("to must not be empty")
    return await get_mail_client(data["from"]).send_mail(data)


async def reply_mail(data: dict[str, Any]) -> dict[str, str]:
    return await get_mail_client(data["mailboxEmail"]).reply_mail({
        "id": data["providerMailId"],
        "body": data.get("body"),
        "html": data.get("html"),
        "toAll": data.get("toAll"),
    })


async def delete_remote_mail(mailbox_email: str, provider_mail_id: str) -> None:
    await get_mail_client(mailbox_email).move_messages([provider_mail_id], "Trash")


async def list_remote_inbox_message_ids(mailbox_email: str, max_messages: int = 500) -> list[str]:
    client = get_mail_client(mailbox_email)
    ids: list[str] = []
    page_size = 100
    for start in range(0, max_messages, page_size):
        rows = await client.list_messages("INBOX", start=start, limit=min(page_size, max_messages - start))
        ids.extend([row["id"] for row in rows if row.get("id")])
        if len(rows) < page_size:
            break
    return ids


async def read_remote_mail(mailbox_email: str, provider_mail_id: str, mark_read: bool = False) -> dict[str, Any]:
    return await get_mail_client(mailbox_email).read_mail(provider_mail_id, mark_read=mark_read)


def mail_to_db_input(mailbox_email: str, mail: dict[str, Any], account_id: int | None = None) -> dict[str, Any]:
    attachments = [
        {
            "provider_part_id": str(item.get("id")),
            "filename": item.get("filename"),
            "content_type": item.get("contentType"),
            "size": item.get("size"),
        }
        for item in mail.get("attachments") or []
    ]
    return {
        "provider_mail_id": mail["id"],
        "mailbox_email": mailbox_email,
        "account_id": account_id,
        "source": _first(mail.get("from")),
        "address": _first(mail.get("to")) or mailbox_email,
        "subject": mail.get("subject"),
        "text": (mail.get("text") or {}).get("content"),
        "html": (mail.get("html") or {}).get("content"),
        "raw_json": json.dumps(mail, ensure_ascii=False),
        "header_raw": mail.get("headerRaw"),
        "has_attachments": 1 if attachments else 0,
        "received_at": mail.get("date"),
        "attachments": attachments,
    }


def _first(value: Any) -> str | None:
    if isinstance(value, list) and value:
        return str(value[0])
    if isinstance(value, str):
        return value
    return None


def _summary(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(raw.get("id")),
        "from": raw.get("from"),
        "subject": raw.get("subject"),
        "date": raw.get("receivedDate") or raw.get("sentDate"),
        "size": raw.get("size"),
        "read": bool((raw.get("flags") or {}).get("read", False)),
    }


def _detail(provider_id: str, raw: dict[str, Any]) -> dict[str, Any]:
    detail = {
        "id": provider_id,
        "from": raw.get("from"),
        "to": raw.get("to"),
        "cc": raw.get("cc"),
        "bcc": raw.get("bcc"),
        "subject": raw.get("subject"),
        "date": raw.get("sentDate") or raw.get("receivedDate"),
        "priority": raw.get("priority"),
        "headerRaw": raw.get("headerRaw"),
    }
    if raw.get("text"):
        detail["text"] = {"content": raw["text"].get("content")}
    if raw.get("html"):
        detail["html"] = {"content": raw["html"].get("content")}
    if raw.get("attachments"):
        detail["attachments"] = [
            {
                "id": str(item.get("id")),
                "filename": item.get("filename"),
                "contentType": item.get("contentType") or "application/octet-stream",
                "size": item.get("contentLength"),
                "inline": item.get("inlined"),
                "contentId": item.get("contentId"),
            }
            for item in raw["attachments"]
        ]
    return detail


def _filename_from_disposition(value: str | None) -> str | None:
    if not value:
        return None
    marker = "filename="
    if marker not in value:
        return None
    return value.split(marker, 1)[1].strip('"; ')
