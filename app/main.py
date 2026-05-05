from __future__ import annotations

import json
import os
import asyncio
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from pydantic import BaseModel, Field, field_validator

from . import db
from .claw_dashboard import (
    create_mailbox as dashboard_create_mailbox,
    delete_mailbox as dashboard_delete_mailbox,
    get_auth_me,
    list_api_keys,
    list_dashboard_mailboxes,
    list_workspaces,
    primary_mailbox_from_items,
    send_login_code,
    update_mailbox_communication_settings,
    verify_login_code,
)
from .claw_mail import (
    delete_remote_mail,
    get_mail_client,
    list_remote_inbox_message_ids,
    mail_to_db_input,
    read_remote_mail,
    reply_mail as claw_reply_mail,
    reset_mail_clients,
    send_mail as claw_send_mail,
)
from .config import CONFIG_FILE, read_config_file, save_config_file, settings
from .listener_manager import (
    listener_snapshot,
    start_all_mailbox_listeners,
    start_mailbox_listener,
    stop_all_mailbox_listeners,
    stop_mailbox_listener,
)
from .runtime_config import account_status, get_default_account_status, require_account
from .sse import sse_hub
from .telegram import notify_new_mail, send_test_message

app = FastAPI(title="Claw Email Web Manager", version="0.2.0-python")


def quiet_event_loop_exception_handler(loop: asyncio.AbstractEventLoop, context: dict[str, Any]) -> None:
    exc = context.get("exception")
    message = str(context.get("message") or "")
    if isinstance(exc, ConnectionResetError):
        return
    if "_ProactorBasePipeTransport._call_connection_lost" in message:
        return
    loop.default_exception_handler(context)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(_request: Request, exc: StarletteHTTPException) -> Response:
    detail = exc.detail if isinstance(exc.detail, str) else "request failed"
    return Response(content=json.dumps({"error": detail}, ensure_ascii=False), status_code=exc.status_code, media_type="application/json")


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(_request: Request, exc: RequestValidationError) -> Response:
    return Response(
        content=json.dumps({"error": "invalid input", "details": exc.errors()}, ensure_ascii=False),
        status_code=400,
        media_type="application/json",
    )


@app.exception_handler(Exception)
async def generic_exception_handler(_request: Request, exc: Exception) -> Response:
    return Response(content=json.dumps({"error": str(exc)}, ensure_ascii=False), status_code=500, media_type="application/json")


def require_admin(
    request: Request,
    x_admin_password: str | None = Header(default=None),
    token: str | None = Query(default=None),
) -> None:
    if request.url.path.startswith("/api/") and (x_admin_password or token) != settings.admin_password:
        raise HTTPException(status_code=401, detail="unauthorized")


def public_account(account: dict[str, Any]) -> dict[str, Any]:
    has_account_telegram = bool(account.get("telegram_enabled"))
    has_global_telegram = bool(settings.telegram_enabled)
    effective_telegram_enabled = has_account_telegram or has_global_telegram
    effective_telegram_chat_id = account.get("telegram_chat_id") or settings.telegram_chat_id
    effective_telegram_api_base = account.get("telegram_api_base") or settings.telegram_api_base
    has_telegram_token = bool(account.get("telegram_bot_token") or settings.telegram_bot_token)
    return {
        **account,
        "api_key": None,
        "dashboard_cookie": None,
        "has_api_key_value": bool(account.get("api_key")),
        "has_dashboard_cookie_value": bool(account.get("dashboard_cookie")),
        "telegram_enabled": 1 if effective_telegram_enabled else 0,
        "telegram_bot_token": None,
        "telegram_chat_id": effective_telegram_chat_id,
        "telegram_api_base": effective_telegram_api_base,
        "has_telegram_bot_token_value": has_telegram_token,
        "config_sources": {
            "telegram_enabled": "global" if not has_account_telegram and has_global_telegram else "account",
            "telegram_bot_token": "global" if settings.telegram_bot_token and not account.get("telegram_bot_token") else "account",
            "telegram_chat_id": "global" if settings.telegram_chat_id and not account.get("telegram_chat_id") else "account",
            "telegram_api_base": "global" if settings.telegram_api_base and not account.get("telegram_api_base") else "account",
        },
        "status": account_status(account),
    }


api = APIRouter(dependencies=[Depends(require_admin)])


class AccountInput(BaseModel):
    name: str | None = None
    user_email: str | None = None
    registered_email: str | None = None
    api_key: str
    dashboard_cookie: str | None = None
    workspace_id: str | None = None
    workspace_name: str | None = None
    parent_mailbox_id: str | None = None
    root_prefix: str | None = None
    domain: str = "claw.163.com"
    telegram_enabled: bool = False
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    telegram_api_base: str | None = None
    sort_order: int | None = None
    is_active: bool = True


class AccountPatch(BaseModel):
    name: str | None = None
    user_email: str | None = None
    registered_email: str | None = None
    api_key: str | None = None
    dashboard_cookie: str | None = None
    workspace_id: str | None = None
    workspace_name: str | None = None
    parent_mailbox_id: str | None = None
    root_prefix: str | None = None
    domain: str | None = None
    telegram_enabled: bool | None = None
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    telegram_api_base: str | None = None
    sort_order: int | None = None
    is_active: bool | None = None


ACCOUNT_FIELD_HELP = {
    "name": "主账号显示名，用于区分多个 Claw 主账号。",
    "user_email": "Claw 主邮箱地址，必须是 @claw.163.com 后缀；注册邮箱会单独显示。",
    "registered_email": "注册/登录 Claw 控制台使用的邮箱，例如 mail@example.com，仅作备注显示。",
    "api_key": "Claw API Key，通常以 ck_live_ 开头；用于收信、发信、回复、附件和监听。",
    "dashboard_cookie": "Claw 控制台登录 Cookie，用于同步邮箱树、创建和删除子邮箱。",
    "workspace_id": "Claw 工作区 ID，从工作区接口返回里获取。",
    "parent_mailbox_id": "主邮箱 ID，从工作区邮箱列表接口里获取。",
    "root_prefix": "主邮箱 @ 前缀，例如 root；子邮箱会拼成 root.xxx@claw.163.com。",
    "domain": "邮箱域名，通常是 claw.163.com。",
    "telegram_enabled": "是否启用该账号的新邮件 Telegram 推送。",
    "telegram_bot_token": "Telegram Bot Token，可从 BotFather 获取。",
    "telegram_chat_id": "接收通知的 Telegram chat_id。",
    "telegram_api_base": "Telegram Bot API 地址，可填写反代地址。",
    "sort_order": "主账号显示顺序，数字越小越靠前。",
}

CONFIG_FIELDS: list[dict[str, Any]] = [
    {"key": "NODE_ENV", "section": "app", "field": "nodeEnv", "label": "运行模式", "help": "production 使用 dist/web 静态文件；development 适合本地开发。"},
    {"key": "PORT", "section": "app", "field": "port", "label": "服务端口", "help": "FastAPI 监听端口。改动后通常需要重启容器或进程。"},
    {"key": "ADMIN_PASSWORD", "section": "app", "field": "adminPassword", "label": "管理密码", "secret": True, "help": "登录面板和调用 API 使用的密码。留空不会覆盖现有值。"},
    {"key": "DATABASE_PATH", "section": "app", "field": "databasePath", "label": "数据库路径", "help": "SQLite 数据库文件路径，支持相对路径。"},
    {"key": "STATIC_DIR", "section": "app", "field": "staticDir", "label": "静态目录", "help": "前端构建产物目录，支持相对路径。"},
    {"key": "TELEGRAM_ENABLED", "section": "telegram", "field": "enabled", "label": "Telegram 推送", "help": "开启后，未单独配置的账号会使用全局 Telegram 设置。"},
    {"key": "TELEGRAM_BOT_TOKEN", "section": "telegram", "field": "botToken", "label": "全局 Bot Token", "secret": True, "help": "全局 Telegram Bot Token。留空不会覆盖现有值。"},
    {"key": "TELEGRAM_CHAT_ID", "section": "telegram", "field": "chatId", "label": "全局 Chat ID", "help": "全局 Telegram 接收账号或群组 chat_id。"},
    {"key": "TELEGRAM_API_BASE", "section": "telegram", "field": "apiBase", "label": "Telegram API 地址", "help": "Bot API 根地址，可填写反代地址。"},
    {"key": "ENABLE_WS_LISTENERS", "section": "app", "field": "enableWsListeners", "label": "实时监听", "help": "是否启动 WebSocket 邮件监听。"},
]

CONFIG_FIELD_MAP = {item["key"]: item for item in CONFIG_FIELDS}


class ConfigPatch(BaseModel):
    values: dict[str, str | bool | int | None]


class CreateMailboxInput(BaseModel):
    suffix: str = Field(pattern=r"^[a-z0-9]{1,32}$")
    account_id: int | None = None


class CommInput(BaseModel):
    commLevel: int = Field(ge=0, le=2)
    extReceiveType: int | None = Field(default=None, ge=0, le=1)
    extSendType: int | None = Field(default=None, ge=0, le=1)


class SendInput(BaseModel):
    from_: str = Field(alias="from")
    to: list[str]
    subject: str | None = None
    body: str | None = None
    html: bool | None = None
    cc: list[str] | None = None
    bcc: list[str] | None = None

    @field_validator("to")
    @classmethod
    def to_not_empty(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("to must not be empty")
        return value


class ReplyInput(BaseModel):
    mailId: int
    body: str | None = None
    html: bool | None = None
    toAll: bool | None = None


class ClawCodeInput(BaseModel):
    email: str


class ClawVerifyInput(BaseModel):
    email: str
    code: str
    accountName: str | None = None
    telegramEnabled: bool = False
    telegramBotToken: str | None = None
    telegramChatId: str | None = None
    telegramApiBase: str | None = None


def _config_data() -> dict[str, Any]:
    data = read_config_file(CONFIG_FILE)
    return data if isinstance(data, dict) else {}


def _config_section(data: dict[str, Any], name: str) -> dict[str, Any]:
    section = data.get(name)
    if not isinstance(section, dict):
        section = {}
        data[name] = section
    return section


def _config_item_value(meta: dict[str, Any], data: dict[str, Any]) -> tuple[Any, bool]:
    section = _config_section(data, meta["section"])
    field = meta["field"]
    configured = field in section and section[field] not in (None, "")
    if configured:
        return section[field], True
    runtime_value = {
        "NODE_ENV": settings.node_env,
        "PORT": settings.port,
        "ADMIN_PASSWORD": settings.admin_password,
        "DATABASE_PATH": settings.database_path,
        "STATIC_DIR": settings.static_dir,
        "TELEGRAM_ENABLED": settings.telegram_enabled,
        "TELEGRAM_BOT_TOKEN": settings.telegram_bot_token,
        "TELEGRAM_CHAT_ID": settings.telegram_chat_id,
        "TELEGRAM_API_BASE": settings.telegram_api_base,
        "ENABLE_WS_LISTENERS": settings.enable_ws_listeners,
    }.get(meta["key"])
    return runtime_value, bool(runtime_value not in (None, ""))


def _public_config() -> dict[str, Any]:
    data = _config_data()
    items: list[dict[str, Any]] = []
    for meta in CONFIG_FIELDS:
        value, configured = _config_item_value(meta, data)
        items.append(
            {
                **meta,
                "value": "" if meta.get("secret") else ("" if value is None else str(value).lower() if isinstance(value, bool) else str(value)),
                "configured": configured,
            }
        )
    return {"path": str(CONFIG_FILE), "items": items}


def _coerce_config_value(meta: dict[str, Any], raw_value: str | bool | int | None) -> Any:
    if raw_value is None:
        return None
    if meta["key"] == "PORT":
        return int(raw_value)
    if meta["key"] in {"TELEGRAM_ENABLED", "ENABLE_WS_LISTENERS"}:
        if isinstance(raw_value, bool):
            return raw_value
        return str(raw_value).strip().lower() in {"1", "true", "yes", "on"}
    return str(raw_value).strip()


def _apply_runtime_config(updates: dict[str, Any]) -> None:
    mapping = {
        "NODE_ENV": ("node_env", str),
        "PORT": ("port", int),
        "ADMIN_PASSWORD": ("admin_password", str),
        "DATABASE_PATH": ("database_path", str),
        "STATIC_DIR": ("static_dir", lambda v: v if v else None),
        "TELEGRAM_ENABLED": ("telegram_enabled", bool),
        "TELEGRAM_BOT_TOKEN": ("telegram_bot_token", lambda v: v if v else None),
        "TELEGRAM_CHAT_ID": ("telegram_chat_id", lambda v: v if v else None),
        "TELEGRAM_API_BASE": ("telegram_api_base", lambda v: v if v else None),
        "ENABLE_WS_LISTENERS": ("enable_ws_listeners", bool),
    }
    for key, value in updates.items():
        os.environ[key] = "true" if value is True else "false" if value is False else str(value)
        if key not in mapping:
            continue
        attr, cast = mapping[key]
        try:
            setattr(settings, attr, cast(value))
        except Exception:
            pass


@app.get("/health")
async def health() -> dict[str, bool]:
    return {"ok": True}


@api.get("/auth/claw/status")
async def auth_status() -> dict[str, Any]:
    return get_default_account_status()


@api.post("/auth/claw/send-code")
async def auth_send_code(body: ClawCodeInput) -> dict[str, bool]:
    await send_login_code(body.email.strip())
    return {"success": True}


async def sync_account_mailboxes(account_id: int) -> int:
    account = db.get_account(account_id)
    remote = await list_dashboard_mailboxes(account_id)
    if account:
        primary = primary_mailbox_from_items(account, remote)
        if primary:
            primary_email = (primary.get("email") or "").strip().lower()
            patch: dict[str, Any] = {"parent_mailbox_id": primary["id"]}
            if "@" in primary_email:
                root_prefix, domain = primary_email.split("@", 1)
                patch.update({"root_prefix": root_prefix, "domain": domain, "user_email": primary_email})
            db.update_account(account_id, patch)
    for item in remote:
        row = db.upsert_mailbox(item)
        start_mailbox_listener(row)
    for mailbox in db.mark_missing_mailboxes_deleted(account_id, [item["email"] for item in remote]):
        stop_mailbox_listener(mailbox["email"])
    return len(remote)


@api.post("/auth/claw/verify-code")
async def auth_verify_code(body: ClawVerifyInput) -> dict[str, Any]:
    cookie = await verify_login_code(body.email.strip(), body.code.strip())
    me = await get_auth_me(cookie)
    workspaces = await list_workspaces(cookie)
    workspace = next((item for item in workspaces if item.get("status") == "active"), None) or (workspaces[0] if workspaces else None)
    if not workspace:
        raise HTTPException(status_code=500, detail="No active Claw workspace found")
    api_keys = await list_api_keys(cookie)
    api_key_item = next((item for item in api_keys if item.get("defaultFlag") == 1), None) or (api_keys[0] if api_keys else None)
    if not api_key_item:
        raise HTTPException(status_code=500, detail="No Claw API key found")
    account = db.create_account({
        "name": body.accountName or body.email,
        "user_email": (me or {}).get("email") or (me or {}).get("emailAddress") or body.email,
        "api_key": api_key_item["apiKey"],
        "dashboard_cookie": cookie,
        "workspace_id": workspace["id"],
        "workspace_name": workspace.get("name"),
        "parent_mailbox_id": None,
        "root_prefix": None,
        "domain": "claw.163.com",
        "telegram_enabled": body.telegramEnabled,
        "telegram_bot_token": body.telegramBotToken,
        "telegram_chat_id": body.telegramChatId,
        "telegram_api_base": body.telegramApiBase or settings.telegram_api_base,
    })
    remote = await list_dashboard_mailboxes(account["id"])
    primary = next((item for item in remote if item["email"] == body.email.strip().lower()), None) or (remote[0] if remote else None)
    if primary:
        db.update_account(account["id"], {
            "parent_mailbox_id": primary["id"],
            "root_prefix": primary["email"].split("@")[0],
            "domain": primary["email"].split("@", 1)[1],
        })
    count = await sync_account_mailboxes(account["id"])
    reset_mail_clients()
    return {"auth": account_status(db.get_account(account["id"])), "syncedMailboxes": count}


@api.post("/auth/claw/refresh")
async def auth_refresh(account_id: int | None = None) -> dict[str, Any]:
    account = require_account(account_id)
    count = await sync_account_mailboxes(account["id"])
    return {"auth": account_status(account), "syncedMailboxes": count}


@api.post("/auth/claw/logout")
async def auth_logout() -> dict[str, Any]:
    stop_all_mailbox_listeners()
    reset_mail_clients()
    for account in db.list_accounts(active_only=True):
        db.delete_account(account["id"])
    return get_default_account_status()


@api.get("/accounts")
async def accounts() -> dict[str, Any]:
    db.seed_env_account()
    db.dedupe_accounts()
    db.dedupe_mailboxes()
    db.cleanup_account_root_mailboxes()
    items = db.list_accounts(active_only=True)
    return {"items": [public_account(item) for item in items], "help": ACCOUNT_FIELD_HELP}


@api.get("/config")
@api.get("/env-config")
async def app_config() -> dict[str, Any]:
    return _public_config()


@api.patch("/config")
@api.patch("/env-config")
async def app_config_update(body: ConfigPatch) -> dict[str, Any]:
    data = _config_data()
    updates: dict[str, Any] = {}
    for key, raw_value in body.values.items():
        meta = CONFIG_FIELD_MAP.get(key)
        if not meta:
            continue
        section = _config_section(data, meta["section"])
        field = meta["field"]
        if raw_value is None or raw_value == "":
            if meta.get("secret"):
                continue
            section.pop(field, None)
            updates[key] = None
            continue
        value = _coerce_config_value(meta, raw_value)
        if meta.get("secret") and not value:
            continue
        section[field] = value
        updates[key] = value
    if updates:
        save_config_file(data, CONFIG_FILE)
        _apply_runtime_config(updates)
        db.seed_env_account()
    return _public_config()


@api.post("/accounts")
async def accounts_create(body: AccountInput) -> dict[str, Any]:
    account = db.create_account(body.model_dump())
    return public_account(account)


@api.patch("/accounts/{account_id}")
async def accounts_update(account_id: int, body: AccountPatch) -> dict[str, Any]:
    account = db.update_account(account_id, body.model_dump(exclude_unset=True))
    if not account:
        raise HTTPException(status_code=404, detail="account not found")
    return public_account(account)


@api.post("/accounts/{account_id}/telegram-test")
async def accounts_telegram_test(account_id: int) -> dict[str, bool]:
    account = db.get_account(account_id)
    if not account:
        raise HTTPException(status_code=404, detail="account not found")
    await send_test_message(account)
    return {"success": True}


@api.post("/config/telegram-test")
async def config_telegram_test() -> dict[str, bool]:
    await send_test_message(
        {
            "name": "global",
            "telegram_enabled": True,
            "telegram_bot_token": settings.telegram_bot_token,
            "telegram_chat_id": settings.telegram_chat_id,
            "telegram_api_base": settings.telegram_api_base,
        }
    )
    return {"success": True}


@api.delete("/accounts/{account_id}")
async def accounts_delete(account_id: int) -> dict[str, bool]:
    for mailbox in db.list_mailboxes(account_id=account_id):
        stop_mailbox_listener(mailbox["email"])
    db.delete_account(account_id)
    return {"success": True}


@api.get("/mailboxes")
async def mailboxes(sync: str | None = None, account_id: int | None = None) -> dict[str, Any]:
    db.seed_env_account()
    if sync == "true":
        accounts = [require_account(account_id)] if account_id else db.list_accounts(active_only=True)
        for account in accounts:
            if account.get("workspace_id") and account.get("dashboard_cookie"):
                await sync_account_mailboxes(account["id"])
            else:
                print(f"[sync:{account.get('name') or account.get('user_email')}] skipped: workspace_id/dashboard_cookie missing")
    db.cleanup_account_root_mailboxes()
    return {"items": db.list_mailboxes(account_id=account_id)}


@api.post("/mailboxes")
async def mailboxes_create(body: CreateMailboxInput) -> Response:
    account = require_account(body.account_id)
    mailbox = await dashboard_create_mailbox(body.suffix, account["id"])
    if account.get("dashboard_cookie"):
        await update_mailbox_communication_settings(mailbox["id"], {"commLevel": 2, "extReceiveType": 1, "extSendType": 1}, account["id"])
    row = db.upsert_mailbox({**mailbox, "comm_level": 2, "ext_receive_type": 1, "ext_send_type": 1})
    start_mailbox_listener(row)
    return Response(content=json.dumps(row, ensure_ascii=False), status_code=201, media_type="application/json")


@api.post("/mailboxes/{mailbox_id}/comm-settings")
async def mailboxes_comm(mailbox_id: str, body: CommInput) -> dict[str, Any]:
    mailbox = db.get_mailbox_by_id(mailbox_id)
    if not mailbox:
        raise HTTPException(status_code=404, detail="mailbox not found")
    if body.commLevel == 2 and (body.extReceiveType is None or body.extSendType is None):
        raise HTTPException(status_code=400, detail="extReceiveType and extSendType are required when commLevel is 2")
    payload = {"commLevel": body.commLevel}
    if body.commLevel == 2:
        payload.update({"extReceiveType": body.extReceiveType, "extSendType": body.extSendType})
    await update_mailbox_communication_settings(mailbox_id, payload, mailbox.get("account_id"))
    return db.update_mailbox_comm_settings(mailbox_id, {
        "comm_level": body.commLevel,
        "ext_receive_type": body.extReceiveType if body.commLevel == 2 else None,
        "ext_send_type": body.extSendType if body.commLevel == 2 else None,
    })


@api.delete("/mailboxes/{mailbox_id}")
async def mailboxes_delete(mailbox_id: str) -> dict[str, bool]:
    mailbox = db.get_mailbox_by_id(mailbox_id)
    if not mailbox:
        return {"success": True}
    account = require_account(mailbox.get("account_id"))
    root_prefix = (account.get("root_prefix") or "").strip().lower()
    domain = (account.get("domain") or "claw.163.com").strip().lower()
    root_email = f"{root_prefix}@{domain}" if root_prefix else ""
    if root_email and mailbox["email"].strip().lower() == root_email:
        raise HTTPException(status_code=400, detail="primary mailbox cannot be deleted here")
    if account.get("dashboard_cookie") and not mailbox_id.startswith(("json:", "local:")):
        await dashboard_delete_mailbox(mailbox_id, account["id"])
    db.mark_mailbox_deleted(mailbox_id)
    stop_mailbox_listener(mailbox["email"])
    return {"success": True}


async def sync_mailbox_inbox(mailbox_email: str) -> None:
    mailbox = db.get_mailbox_by_email(mailbox_email)
    if mailbox and str(mailbox.get("id", "")).startswith("local:"):
        return
    remote_ids = await list_remote_inbox_message_ids(mailbox_email)
    remote_set = set(remote_ids)
    local_ids = db.list_mail_provider_ids(mailbox_email)
    db.delete_mails_by_provider_ids(mailbox_email, [item for item in local_ids if item not in remote_set])
    account = db.get_account_for_mailbox(mailbox_email)
    for provider_id in remote_ids:
        if db.get_mail_by_provider_id(mailbox_email, provider_id):
            continue
        mail = await read_remote_mail(mailbox_email, provider_id)
        row = db.save_mail(mail_to_db_input(mailbox_email, mail, account.get("id") if account else None))
        try:
            if await notify_new_mail(account, mailbox_email, mail):
                db.mark_mail_notified(row["id"])
        except Exception as exc:
            print(f"[telegram:{mailbox_email}] {exc}")


@api.get("/mails")
async def mails(mailbox: str | None = None, sync: str | None = None, account_id: int | None = None, limit: int = 50, offset: int = 0) -> dict[str, Any]:
    limit = min(max(limit, 1), 100)
    offset = max(offset, 0)
    if sync == "true" and mailbox:
        await sync_mailbox_inbox(mailbox.strip().lower())
    elif sync == "true":
        for item in db.list_active_mailboxes():
            if account_id is None or item.get("account_id") == account_id:
                try:
                    await sync_mailbox_inbox(item["email"])
                except Exception as exc:
                    if "资源不存在" in str(exc) or "user not found" in str(exc).lower():
                        db.update_mailbox_status(item["id"], "invalid")
                    else:
                        print(f"[sync:{item['email']}] {exc}")
    return db.list_mails(mailbox.strip().lower() if mailbox else None, account_id, limit, offset)


@api.get("/mails/{mail_id}")
async def mail_detail(mail_id: int) -> dict[str, Any]:
    mail = db.get_mail_by_id(mail_id)
    if not mail:
        raise HTTPException(status_code=404, detail="mail not found")
    return {**mail, "parsed": json.loads(mail["raw_json"]), "attachments": db.list_attachments(mail_id)}


@api.get("/mails/{mail_id}/attachments/{part_id}")
async def attachment(mail_id: int, part_id: str) -> StreamingResponse:
    mail = db.get_mail_by_id(mail_id)
    if not mail:
        raise HTTPException(status_code=404, detail="mail not found")
    stream, content_type, filename = await get_mail_client(mail["mailbox_email"]).stream(
        "mbox:getMessageData",
        {"mid": mail["provider_mail_id"], "part": part_id, "mode": "download"},
    )
    return StreamingResponse(stream, media_type=content_type, headers={"content-disposition": f'attachment; filename="{filename}"'})


@api.delete("/mails/{mail_id}")
async def mail_delete(mail_id: int) -> dict[str, bool]:
    mail = db.get_mail_by_id(mail_id)
    if not mail:
        return {"success": True}
    await delete_remote_mail(mail["mailbox_email"], mail["provider_mail_id"])
    db.delete_mail_by_id(mail_id)
    return {"success": True}


@api.post("/send")
async def send(body: SendInput) -> dict[str, str]:
    if not db.get_mailbox_by_email(body.from_.strip().lower()):
        raise HTTPException(status_code=400, detail="from must be a managed mailbox")
    return await claw_send_mail({**body.model_dump(by_alias=True), "from": body.from_})


@api.post("/reply")
async def reply(body: ReplyInput) -> dict[str, str]:
    mail = db.get_mail_by_id(body.mailId)
    if not mail:
        raise HTTPException(status_code=404, detail="mail not found")
    return await claw_reply_mail({
        "mailboxEmail": mail["mailbox_email"],
        "providerMailId": mail["provider_mail_id"],
        "body": body.body,
        "html": body.html,
        "toAll": body.toAll,
    })


@api.get("/events")
async def events() -> StreamingResponse:
    queue = sse_hub.subscribe()

    async def generator():
        try:
            yield ": connected\n\n"
            while True:
                yield await queue.get()
        finally:
            sse_hub.unsubscribe(queue)

    return StreamingResponse(generator(), media_type="text/event-stream")


@api.get("/listeners")
async def listeners() -> dict[str, Any]:
    return {"items": listener_snapshot()}


@app.on_event("startup")
async def startup() -> None:
    asyncio.get_running_loop().set_exception_handler(quiet_event_loop_exception_handler)
    start_all_mailbox_listeners()


@app.on_event("shutdown")
async def shutdown() -> None:
    stop_all_mailbox_listeners()


app.include_router(api, prefix="/api")

web_root = Path(settings.static_dir) if settings.static_dir else Path(__file__).resolve().parent.parent / "dist" / "web"
if web_root.exists():
    app.mount("/", StaticFiles(directory=web_root, html=True), name="web")
