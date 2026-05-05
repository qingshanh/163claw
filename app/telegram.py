from __future__ import annotations

import html
import re
from html.parser import HTMLParser

import httpx

from .config import settings


def telegram_config_for_account(account: dict | None) -> dict | None:
    if not account:
        return None
    enabled = bool(account.get("telegram_enabled")) or settings.telegram_enabled
    token = account.get("telegram_bot_token") or settings.telegram_bot_token
    chat_id = account.get("telegram_chat_id") or settings.telegram_chat_id
    api_base = (settings.telegram_api_base or account.get("telegram_api_base") or "https://api.telegram.org").rstrip("/")
    if not enabled or not token or not chat_id:
        return None
    return {"token": token, "chat_id": chat_id, "api_base": api_base}


async def notify_new_mail(account: dict | None, mailbox_email: str, mail: dict) -> bool:
    cfg = telegram_config_for_account(account)
    if not cfg:
        return False
    subject = mail.get("subject") or "(no subject)"
    sender = _first(mail.get("from")) or "unknown"
    content = mail_content_for_telegram(mail)
    code = verification_code_for_telegram(subject, content)
    if len(content) > 3200:
        content = content[:3200] + "\n\n...(truncated)"
    body = (
        "<b>New Claw mail</b>\n"
        f"Mailbox: <code>{html.escape(mailbox_email)}</code>\n"
        f"From: {html.escape(sender)}\n"
        f"Subject: {html.escape(subject)}"
    )
    if code:
        body += f"\nCode: <code>{html.escape(code)}</code>"
    if content:
        body += f"\n\n<b>Content</b>\n{html.escape(content)}"
    if len(body) > 3900:
        body = body[:3800] + "\n\n...(truncated)"
    url = f"{cfg['api_base']}/bot{cfg['token']}/sendMessage"
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            url,
            json={
                "chat_id": cfg["chat_id"],
                "text": body,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
        )
    if response.is_error:
        raise RuntimeError(f"Telegram notification failed: HTTP {response.status_code} {response.text[:200]}")
    data = response.json()
    if data.get("ok") is not True:
        raise RuntimeError(f"Telegram notification failed: {data.get('description') or data}")
    return True


async def send_test_message(account: dict | None) -> bool:
    cfg = telegram_config_for_account(account)
    if not cfg:
        raise RuntimeError("Telegram is not configured for this account")
    name = account.get("name") or account.get("user_email") or account.get("root_prefix") or "account"
    url = f"{cfg['api_base']}/bot{cfg['token']}/sendMessage"
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            url,
            json={
                "chat_id": cfg["chat_id"],
                "text": f"<b>Claw Email test</b>\nAccount: <code>{html.escape(str(name))}</code>",
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
        )
    if response.is_error:
        raise RuntimeError(f"Telegram test failed: HTTP {response.status_code} {response.text[:200]}")
    data = response.json()
    if data.get("ok") is not True:
        raise RuntimeError(f"Telegram test failed: {data.get('description') or data}")
    return True


def _first(value) -> str | None:
    if isinstance(value, list) and value:
        return str(value[0])
    if isinstance(value, str):
        return value
    return None


class _HtmlToText(HTMLParser):
    block_tags = {"br", "p", "div", "tr", "li", "table", "section", "article", "h1", "h2", "h3", "h4"}
    ignored_tags = {"style", "script", "head", "title", "meta", "noscript"}

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag: str, _attrs) -> None:
        tag = tag.lower()
        if tag in self.ignored_tags:
            self.skip_depth += 1
            return
        if self.skip_depth:
            return
        if tag in self.block_tags:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self.ignored_tags and self.skip_depth:
            self.skip_depth -= 1
            return
        if self.skip_depth:
            return
        if tag in self.block_tags:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self.skip_depth:
            return
        if data.strip():
            self.parts.append(data)

    def text(self) -> str:
        return _clean_mail_text("".join(self.parts))


def mail_content_for_telegram(mail: dict) -> str:
    text = (mail.get("text") or {}).get("content")
    if isinstance(text, str) and text.strip():
        return _clean_mail_text(text)
    html_body = (mail.get("html") or {}).get("content")
    if isinstance(html_body, str) and html_body.strip():
        parser = _HtmlToText()
        parser.feed(html_body)
        return parser.text()
    return ""


def verification_code_for_telegram(subject: str, content: str) -> str | None:
    haystack = f"{subject}\n{content}".lower()
    if not any(word in haystack for word in ["验证码", "verification", "verify", "code", "otp", "passcode"]):
        return None
    match = re.search(r"(?<!\d)(\d{4,8})(?!\d)", content)
    return match.group(1) if match else None


CSS_DECL_RE = re.compile(r"^[a-zA-Z_-][a-zA-Z0-9_-]*\s*:\s*.+;?$")
CSS_SELECTOR_PREFIXES = (".", "#", "@font-face", "@media", "body", "table", "td", "img", "a,", "blockquote")


def _clean_mail_text(value: str) -> str:
    text = html.unescape(value).replace("\r", "\n")
    text = re.sub(r"[\u200b-\u200f\ufeff]", "", text)
    lines = [line.strip() for line in text.splitlines()]
    cleaned: list[str] = []
    in_css_block = False
    for line in lines:
        if not line:
            continue
        lowered = line.lower()
        if "{" in line and not _looks_like_sentence(line):
            in_css_block = "}" not in line
            continue
        if in_css_block:
            if "}" in line:
                in_css_block = False
            continue
        if line == "}" or line.endswith("{"):
            continue
        if lowered.startswith(CSS_SELECTOR_PREFIXES):
            continue
        if lowered.startswith(("-webkit-", "-ms-", "mso-", "src: url", "format(")):
            continue
        if CSS_DECL_RE.match(line) and not _looks_like_sentence(line):
            continue
        cleaned.append(re.sub(r"\s+", " ", line))

    deduped: list[str] = []
    for line in cleaned:
        if deduped and deduped[-1] == line:
            continue
        deduped.append(line)
    return "\n".join(deduped).strip()


def _looks_like_sentence(line: str) -> bool:
    if re.search(r"[\u4e00-\u9fff]", line):
        return True
    return bool(re.search(r"\s", line)) and not line.rstrip().endswith((";", "{", "}"))
