from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import struct
import time
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

import websockets
from websockets.exceptions import ConnectionClosed, ConnectionClosedError
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from nacl.bindings import crypto_scalarmult
from nacl.public import PrivateKey

from . import db
from .claw_mail import get_mail_client, mail_to_db_input
from .config import settings
from .sse import sse_hub
from .telegram import notify_new_mail

WS_URL = "wss://claw.126.net:5210"
MAIL_EVENT_TYPE = 3001
BACKOFF_SECONDS = [1, 2, 4, 8, 16, 30]


@dataclass
class ListenerState:
    email: str
    stopped: bool = False
    connected: bool = False
    retry: int = 0
    task: asyncio.Task | None = None
    started_at: float | None = None
    last_event_at: float | None = None
    error: str | None = None
    disabled: bool = False


listeners: dict[str, ListenerState] = {}


def b64url(value: str) -> str:
    return base64.b64encode(value.encode()).decode().replace("+", "-").replace("/", "_").rstrip("=")


def varint(length: int) -> bytes:
    out = bytearray()
    while True:
        byte = length % 128
        length //= 128
        if length:
            byte |= 128
        out.append(byte)
        if not length:
            return bytes(out)


def packet(packet_type: int, body: bytes) -> bytes:
    return bytes([(packet_type << 4)]) + varint(len(body)) + body


def wstr(value: str) -> bytes:
    data = value.encode()
    return struct.pack(">H", len(data)) + data


def connect_packet(uid: str, token: str, device_id: str, public_key: str) -> bytes:
    body = bytearray()
    body.append(4)
    body.append(1)
    body += wstr(device_id)
    body += wstr(b64url(uid))
    body += wstr(token)
    body += struct.pack(">Q", int(time.time() * 1000))
    body += wstr(public_key)
    return packet(1, bytes(body))


def ping_packet() -> bytes:
    return bytes([112])


def recv_ack_packet(message_id: int, message_seq: int) -> bytes:
    return packet(6, struct.pack(">QI", message_id, message_seq))


class Reader:
    def __init__(self, data: bytes):
        self.data = data
        self.offset = 0

    def byte(self) -> int:
        value = self.data[self.offset]
        self.offset += 1
        return value

    def int16(self) -> int:
        value = struct.unpack_from(">H", self.data, self.offset)[0]
        self.offset += 2
        return value

    def int32(self) -> int:
        value = struct.unpack_from(">I", self.data, self.offset)[0]
        self.offset += 4
        return value

    def int64(self) -> int:
        value = struct.unpack_from(">Q", self.data, self.offset)[0]
        self.offset += 8
        return value

    def string(self) -> str:
        length = self.int16()
        if length <= 0:
            return ""
        raw = self.data[self.offset:self.offset + length]
        self.offset += length
        return raw.decode(errors="replace")

    def varint(self) -> int:
        value = 0
        shift = 0
        while shift < 28:
            byte = self.byte()
            value |= (byte & 127) << shift
            if not (byte & 128):
                break
            shift += 7
        return value

    def remaining(self) -> bytes:
        raw = self.data[self.offset:]
        self.offset = len(self.data)
        return raw


def parse_packet(data: bytes) -> dict[str, Any]:
    first = data[0]
    packet_type = (first >> 4) & 15
    if packet_type in (7, 8):
        return {"type": "pong"}
    reader = Reader(data)
    reader.byte()
    reader.varint()
    if packet_type == 2:
        has_version = (first & 1) > 0
        server_version = reader.byte() if has_version else 0
        time_diff = reader.int64()
        reason_code = reader.byte()
        server_key = reader.string()
        salt = reader.string()
        if server_version >= 4:
            reader.int64()
        return {"type": "connack", "reasonCode": reason_code, "serverVersion": server_version, "timeDiff": time_diff, "serverKey": server_key, "salt": salt}
    if packet_type == 5:
        reader.byte()
        reader.string()
        from_uid = reader.string()
        channel_id = reader.string()
        channel_type = reader.byte()
        reader.int32()
        reader.string()
        message_id = reader.int64()
        message_seq = reader.int32()
        reader.int32()
        return {"type": "recv", "messageID": message_id, "messageSeq": message_seq, "fromUID": from_uid, "channelID": channel_id, "channelType": channel_type, "payload": reader.remaining()}
    if packet_type == 9:
        reason_code = reader.byte()
        reason = reader.string()
        return {"type": "disconnect", "reasonCode": reason_code, "reason": reason}
    return {"type": "unknown", "packetType": packet_type}


def derive_aes(private_key: PrivateKey, server_key: str, salt: str) -> tuple[bytes, bytes] | None:
    if not server_key or not salt:
        return None
    shared = crypto_scalarmult(bytes(private_key), base64.b64decode(server_key))
    digest = hashlib.md5(base64.b64encode(shared)).hexdigest()
    return digest[:16].encode(), salt[:16].encode()


def decrypt_payload(payload: bytes, key_iv: tuple[bytes, bytes] | None) -> bytes:
    if not key_iv:
        return payload
    key, iv = key_iv
    encrypted = base64.b64decode(payload.decode())
    decryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    padded = decryptor.update(encrypted) + decryptor.finalize()
    pad = padded[-1]
    return padded[:-pad]


async def _persist_and_notify(email: str, provider_mail_id: str) -> None:
    account = db.get_account_for_mailbox(email)
    mail = await get_mail_client(email).read_mail(provider_mail_id, mark_read=True)
    row = db.save_mail(mail_to_db_input(email, mail, account.get("id") if account else None))
    try:
        sent = await notify_new_mail(account, email, mail)
        if sent:
            db.mark_mail_notified(row["id"])
    except Exception as exc:
        print(f"[telegram:{email}] {exc}")
    sse_hub.broadcast("mail", {"mailboxEmail": email, "id": row["id"], "providerMailId": provider_mail_id})


async def _listen(state: ListenerState) -> None:
    while not state.stopped:
        delay = 0 if state.retry == 0 else BACKOFF_SECONDS[min(state.retry - 1, len(BACKOFF_SECONDS) - 1)]
        if delay:
            await asyncio.sleep(delay)
        try:
            client = get_mail_client(state.email)
            token = await client.ensure_im_token()
            seed = sum(ord(ch) for ch in state.email) & 0xFFFFFFFF
            device_id = f"claw-py-{seed:08x}"
            private_key = PrivateKey.generate()
            public_key = base64.b64encode(bytes(private_key.public_key)).decode()
            async with websockets.connect(WS_URL, open_timeout=10, ping_interval=None) as ws:
                await ws.send(connect_packet(state.email, token, device_id, public_key))
                raw = await ws.recv()
                pkt = parse_packet(bytes(raw))
                if pkt.get("type") != "connack" or pkt.get("reasonCode") != 1:
                    raise RuntimeError(f"CONNACK failed: {pkt}")
                key_iv = derive_aes(private_key, pkt.get("serverKey") or "", pkt.get("salt") or "")
                state.connected = True
                state.retry = 0
                state.started_at = time.time()
                state.error = None

                async def heartbeat() -> None:
                    while state.connected and not state.stopped:
                        await asyncio.sleep(60)
                        try:
                            await ws.send(ping_packet())
                        except Exception:
                            break

                hb = asyncio.create_task(heartbeat())
                try:
                    async for message in ws:
                        pkt = parse_packet(bytes(message))
                        if pkt.get("type") == "recv":
                            payload = decrypt_payload(pkt["payload"], key_iv)
                            await ws.send(recv_ack_packet(pkt["messageID"], pkt["messageSeq"]))
                            try:
                                event = json.loads(payload.decode())
                            except ValueError:
                                continue
                            if event.get("type") == MAIL_EVENT_TYPE and event.get("mailId"):
                                state.last_event_at = time.time()
                                await _persist_and_notify(state.email, event["mailId"])
                        elif pkt.get("type") == "disconnect":
                            raise RuntimeError(f"server disconnect: {pkt.get('reason')}")
                finally:
                    hb.cancel()
                    with suppress(asyncio.CancelledError):
                        await hb
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            state.connected = False
            state.retry += 1
            if is_transient_listener_disconnect(exc):
                state.error = "connection reset by remote; reconnecting"
                continue
            state.error = str(exc)
            if is_permanent_mailbox_error(exc):
                state.disabled = True
                mailbox = db.get_mailbox_by_email(state.email)
                if mailbox:
                    db.update_mailbox_status(mailbox["id"], "invalid")
                print(f"[listener:{state.email}] disabled: {exc}")
                break
            print(f"[listener:{state.email}] {exc}")


def is_permanent_mailbox_error(exc: Exception) -> bool:
    message = str(exc)
    return "资源不存在" in message or "user not found" in message.lower() or "USER_NOT_FOUND" in message


def is_transient_listener_disconnect(exc: Exception) -> bool:
    message = str(exc).lower()
    return (
        isinstance(exc, (ConnectionClosed, ConnectionClosedError, ConnectionResetError, TimeoutError, OSError))
        and (
            "no close frame received or sent" in message
            or "connection reset" in message
            or "winerror 10054" in message
            or "forcibly closed" in message
            or "远程主机强迫关闭" in message
        )
    )


def start_mailbox_listener(mailbox: dict) -> None:
    if not settings.enable_ws_listeners or mailbox.get("status") != "active":
        return
    if str(mailbox.get("id", "")).startswith("local:"):
        return
    email = mailbox["email"].strip().lower()
    existing = listeners.get(email)
    if existing and existing.task and not existing.task.done() and not existing.stopped:
        return
    state = ListenerState(email=email)
    state.task = asyncio.create_task(_listen(state))
    listeners[email] = state


def stop_mailbox_listener(email: str) -> None:
    normalized = email.strip().lower()
    state = listeners.get(normalized)
    if not state:
        return
    state.stopped = True
    state.connected = False
    if state.task:
        state.task.cancel()
    listeners.pop(normalized, None)


def start_all_mailbox_listeners() -> None:
    for mailbox in db.list_active_mailboxes():
        start_mailbox_listener(mailbox)


def stop_all_mailbox_listeners() -> None:
    for email in list(listeners):
        stop_mailbox_listener(email)


def listener_snapshot() -> list[dict[str, Any]]:
    def iso(ts: float | None) -> str | None:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts)) if ts else None

    return [
        {
            "email": state.email,
            "connected": state.connected,
            "retry": state.retry,
            "status": "running" if state.connected else ("error" if state.error else "connecting"),
            "disabled": state.disabled,
            "startedAt": iso(state.started_at),
            "lastEventAt": iso(state.last_event_at),
            "error": state.error,
        }
        for state in listeners.values()
    ]
