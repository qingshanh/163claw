from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable

from .account_loader import load_accounts_json
from .config import settings

Path(settings.database_path).parent.mkdir(parents=True, exist_ok=True)


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(settings.database_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


db = connect()


@contextmanager
def transaction():
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise


def init_db() -> None:
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS accounts (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT,
          user_email TEXT,
          registered_email TEXT,
          api_key TEXT NOT NULL,
          dashboard_cookie TEXT,
          workspace_id TEXT,
          workspace_name TEXT,
          parent_mailbox_id TEXT,
          root_prefix TEXT,
          domain TEXT NOT NULL DEFAULT 'claw.163.com',
          telegram_enabled INTEGER NOT NULL DEFAULT 0,
          telegram_bot_token TEXT,
          telegram_chat_id TEXT,
          telegram_api_base TEXT,
          sort_order INTEGER NOT NULL DEFAULT 0,
          is_active INTEGER NOT NULL DEFAULT 1,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS mailboxes (
          id TEXT PRIMARY KEY,
          email TEXT NOT NULL UNIQUE,
          prefix TEXT NOT NULL,
          display_name TEXT,
          account_id INTEGER,
          status TEXT NOT NULL DEFAULT 'active',
          openclaw_status TEXT,
          install_command TEXT,
          auth_url TEXT,
          comm_level INTEGER,
          ext_receive_type INTEGER,
          ext_send_type INTEGER,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          FOREIGN KEY(account_id) REFERENCES accounts(id) ON DELETE SET NULL
        );

        CREATE INDEX IF NOT EXISTS idx_mailboxes_email ON mailboxes(email);
        CREATE INDEX IF NOT EXISTS idx_mailboxes_status ON mailboxes(status);
        CREATE INDEX IF NOT EXISTS idx_mailboxes_account ON mailboxes(account_id);

        CREATE TABLE IF NOT EXISTS mails (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          provider_mail_id TEXT NOT NULL,
          mailbox_email TEXT NOT NULL,
          account_id INTEGER,
          source TEXT,
          address TEXT,
          subject TEXT,
          text TEXT,
          html TEXT,
          raw_json TEXT NOT NULL,
          header_raw TEXT,
          has_attachments INTEGER NOT NULL DEFAULT 0,
          received_at TEXT,
          notified_at TEXT,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          UNIQUE(mailbox_email, provider_mail_id),
          FOREIGN KEY(account_id) REFERENCES accounts(id) ON DELETE SET NULL
        );

        CREATE INDEX IF NOT EXISTS idx_mails_mailbox_email ON mails(mailbox_email);
        CREATE INDEX IF NOT EXISTS idx_mails_created_at ON mails(created_at);
        CREATE INDEX IF NOT EXISTS idx_mails_account ON mails(account_id);

        CREATE TABLE IF NOT EXISTS attachments (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          mail_id INTEGER NOT NULL,
          provider_part_id TEXT NOT NULL,
          filename TEXT,
          content_type TEXT,
          size INTEGER,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          FOREIGN KEY(mail_id) REFERENCES mails(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_attachments_mail_id ON attachments(mail_id);

        CREATE TABLE IF NOT EXISTS app_settings (
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL,
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    for table, column, definition in [
        ("mailboxes", "account_id", "INTEGER"),
        ("mailboxes", "comm_level", "INTEGER"),
        ("mailboxes", "ext_receive_type", "INTEGER"),
        ("mailboxes", "ext_send_type", "INTEGER"),
        ("mails", "account_id", "INTEGER"),
        ("mails", "notified_at", "TEXT"),
        ("accounts", "registered_email", "TEXT"),
        ("accounts", "sort_order", "INTEGER NOT NULL DEFAULT 0"),
    ]:
        ensure_column(table, column, definition)
    seed_env_account()
    dedupe_accounts()
    dedupe_mailboxes()
    cleanup_account_root_mailboxes()
    db.commit()


def ensure_column(table: str, column: str, definition: str) -> None:
    rows = db.execute(f"PRAGMA table_info({table})").fetchall()
    if any(row["name"] == column for row in rows):
        return
    db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row else None


def rows_to_dicts(rows: Iterable[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


def seed_env_account() -> None:
    if settings.claw_accounts_json:
        seed_accounts_json(settings.claw_accounts_json)
    if not settings.claw_api_key:
        return
    existing = db.execute("SELECT id FROM accounts WHERE api_key = ? LIMIT 1", (settings.claw_api_key,)).fetchone()
    if existing:
        payload = {
            key: value
            for key, value in {
                "name": settings.claw_root_prefix,
                "dashboard_cookie": settings.claw_dashboard_cookie,
                "workspace_id": settings.claw_workspace_id,
                "parent_mailbox_id": settings.claw_parent_mailbox_id,
                "root_prefix": settings.claw_root_prefix,
                "domain": settings.claw_domain,
                "telegram_bot_token": settings.telegram_bot_token,
                "telegram_chat_id": settings.telegram_chat_id,
                "telegram_api_base": settings.telegram_api_base,
            }.items()
            if value
        }
        payload["telegram_enabled"] = settings.telegram_enabled
        update_account(existing["id"], payload)
        return
    db.execute(
        """
        INSERT INTO accounts
          (name, user_email, registered_email, api_key, dashboard_cookie, workspace_id, parent_mailbox_id, root_prefix, domain,
           telegram_enabled, telegram_bot_token, telegram_chat_id, telegram_api_base)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            settings.claw_root_prefix,
            None,
            None,
            settings.claw_api_key,
            settings.claw_dashboard_cookie,
            settings.claw_workspace_id,
            settings.claw_parent_mailbox_id,
            settings.claw_root_prefix,
            settings.claw_domain,
            1 if settings.telegram_enabled else 0,
            settings.telegram_bot_token,
            settings.telegram_chat_id,
            settings.telegram_api_base,
        ),
    )


def seed_accounts_json(path: str) -> None:
    try:
        accounts = load_accounts_json(path)
    except FileNotFoundError:
        return
    except Exception as exc:
        print(f"[accounts] failed to load {path}: {exc}")
        return
    with transaction():
        for account in accounts:
            existing = db.execute("SELECT id FROM accounts WHERE api_key = ? LIMIT 1", (account["api_key"],)).fetchone()
            if existing:
                account_id = existing["id"]
                db.execute(
                    """
                    UPDATE accounts
                    SET name = ?,
                        user_email = ?,
                        registered_email = COALESCE(NULLIF(registered_email, ''), ?),
                        dashboard_cookie = COALESCE(NULLIF(?, ''), dashboard_cookie),
                        workspace_id = COALESCE(NULLIF(?, ''), workspace_id),
                        workspace_name = COALESCE(NULLIF(?, ''), workspace_name),
                        parent_mailbox_id = COALESCE(NULLIF(?, ''), parent_mailbox_id),
                        root_prefix = COALESCE(NULLIF(?, ''), root_prefix),
                        domain = COALESCE(NULLIF(?, ''), domain),
                        telegram_enabled = CASE WHEN ? THEN 1 ELSE telegram_enabled END,
                        telegram_bot_token = COALESCE(NULLIF(?, ''), telegram_bot_token),
                        telegram_chat_id = COALESCE(NULLIF(?, ''), telegram_chat_id),
                        telegram_api_base = COALESCE(NULLIF(?, ''), telegram_api_base),
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (
                        account.get("name"),
                        account.get("user_email"),
                        account.get("registered_email"),
                        account.get("dashboard_cookie"),
                        account.get("workspace_id"),
                        account.get("workspace_name"),
                        account.get("parent_mailbox_id"),
                        account.get("root_prefix"),
                        account.get("domain") or "claw.163.com",
                        1 if account.get("telegram_enabled") else 0,
                        account.get("telegram_bot_token"),
                        account.get("telegram_chat_id"),
                        account.get("telegram_api_base"),
                        account_id,
                    ),
                )
            else:
                cur = db.execute(
                    """
                    INSERT INTO accounts
                      (name, user_email, registered_email, api_key, dashboard_cookie, workspace_id, workspace_name, parent_mailbox_id,
                       root_prefix, domain, telegram_enabled, telegram_bot_token, telegram_chat_id, telegram_api_base, sort_order, is_active)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                    """,
                    (
                        account.get("name"),
                        account.get("user_email"),
                        account.get("registered_email"),
                        account["api_key"],
                        account.get("dashboard_cookie"),
                        account.get("workspace_id"),
                        account.get("workspace_name"),
                        account.get("parent_mailbox_id"),
                        account.get("root_prefix"),
                        account.get("domain") or "claw.163.com",
                        1 if account.get("telegram_enabled") else 0,
                        account.get("telegram_bot_token"),
                        account.get("telegram_chat_id"),
                        account.get("telegram_api_base") or settings.telegram_api_base,
                        account.get("sort_order") or 0,
                    ),
                )
                account_id = cur.lastrowid
            seed_users = account.get("users", [])
            if seed_users:
                for email in seed_users:
                    prefix = email.split("@", 1)[0]
                    db.execute(
                        """
                        INSERT INTO mailboxes (id, email, prefix, display_name, account_id, status)
                        VALUES (?, ?, ?, ?, ?, 'active')
                        ON CONFLICT(id) DO UPDATE SET
                          email = excluded.email, prefix = excluded.prefix, display_name = excluded.display_name,
                          account_id = excluded.account_id, status = 'active', updated_at = CURRENT_TIMESTAMP
                        ON CONFLICT(email) DO UPDATE SET
                          id = excluded.id, prefix = excluded.prefix, display_name = excluded.display_name,
                          account_id = excluded.account_id, status = 'active', updated_at = CURRENT_TIMESTAMP
                        """,
                        (f"json:{account_id}:{email}", email, prefix, prefix, account_id),
                    )


def account_dedupe_key(account: dict[str, Any] | sqlite3.Row) -> tuple[str, str, str]:
    api_key = (account["api_key"] or "").strip()
    user_email = (account["user_email"] or "").strip().lower()
    root_prefix = (account["root_prefix"] or "").strip().lower()
    return api_key, user_email, root_prefix


def account_identity_keys(account: dict[str, Any] | sqlite3.Row) -> list[tuple[str, str]]:
    keys: list[tuple[str, str]] = []
    api_key = (account["api_key"] or "").strip()
    user_email = (account["user_email"] or "").strip().lower()
    root_prefix = (account["root_prefix"] or "").strip().lower()
    domain = (account["domain"] or "claw.163.com").strip().lower()
    if api_key:
        keys.append(("api", api_key))
    if user_email.endswith("@claw.163.com"):
        keys.append(("claw", user_email))
    if root_prefix:
        keys.append(("claw", f"{root_prefix}@{domain}"))
    return keys


def dedupe_accounts() -> int:
    accounts = db.execute("SELECT * FROM accounts WHERE is_active = 1 ORDER BY id ASC").fetchall()
    seen: dict[tuple[str, str], int] = {}
    removed = 0
    with transaction():
        for account in accounts:
            keys = account_identity_keys(account)
            if not keys:
                continue
            keeper_id = next((seen[key] for key in keys if key in seen), None)
            if keeper_id is None:
                for key in keys:
                    seen[key] = account["id"]
                continue
            db.execute(
                """
                UPDATE accounts
                SET dashboard_cookie = COALESCE(NULLIF(dashboard_cookie, ''), (SELECT dashboard_cookie FROM accounts WHERE id = ?)),
                    workspace_id = COALESCE(NULLIF(workspace_id, ''), (SELECT workspace_id FROM accounts WHERE id = ?)),
                    workspace_name = COALESCE(NULLIF(workspace_name, ''), (SELECT workspace_name FROM accounts WHERE id = ?)),
                    parent_mailbox_id = COALESCE(NULLIF(parent_mailbox_id, ''), (SELECT parent_mailbox_id FROM accounts WHERE id = ?)),
                    registered_email = COALESCE(NULLIF(registered_email, ''), (SELECT registered_email FROM accounts WHERE id = ?)),
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (account["id"], account["id"], account["id"], account["id"], account["id"], keeper_id),
            )
            db.execute("UPDATE mailboxes SET account_id = ? WHERE account_id = ?", (keeper_id, account["id"]))
            db.execute("UPDATE mails SET account_id = ? WHERE account_id = ?", (keeper_id, account["id"]))
            db.execute("UPDATE accounts SET is_active = 0, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (account["id"],))
            removed += 1
    return removed


def dedupe_mailboxes() -> int:
    rows = db.execute("SELECT * FROM mailboxes WHERE status != 'deleted' ORDER BY created_at ASC, id ASC").fetchall()
    seen: dict[tuple[int | None, str], str] = {}
    removed = 0
    with transaction():
        for row in rows:
            key = (row["account_id"], row["email"].strip().lower())
            keeper_id = seen.get(key)
            if keeper_id is None:
                seen[key] = row["id"]
                continue
            db.execute("UPDATE mailboxes SET status = 'deleted', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (row["id"],))
            removed += 1
    return removed


def cleanup_account_root_mailboxes() -> int:
    accounts = list_accounts(active_only=True, dedupe=False)
    removed = 0
    with transaction():
        for account in accounts:
            root_prefix = (account.get("root_prefix") or "").strip().lower()
            domain = (account.get("domain") or "claw.163.com").strip().lower()
            if not root_prefix:
                continue
            root_email = f"{root_prefix}@{domain}"
            rows = db.execute(
                """
                SELECT * FROM mailboxes
                WHERE account_id = ? AND lower(email) = lower(?) AND status != 'deleted'
                ORDER BY CASE WHEN id = ? THEN 0 ELSE 1 END, created_at ASC, id ASC
                """,
                (account["id"], root_email, account.get("parent_mailbox_id")),
            ).fetchall()
            for row in rows[1:]:
                db.execute("UPDATE mailboxes SET status = 'deleted', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (row["id"],))
                removed += 1
    return removed


def get_setting(key: str) -> str | None:
    row = db.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_setting(key: str, value: str) -> None:
    with transaction():
        db.execute(
            """
            INSERT INTO app_settings (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP
            """,
            (key, value),
        )


def delete_settings(keys: list[str]) -> None:
    with transaction():
        db.executemany("DELETE FROM app_settings WHERE key = ?", [(key,) for key in keys])


def create_account(data: dict[str, Any]) -> dict[str, Any]:
    api_key = data["api_key"].strip()
    user_email = (data.get("user_email") or "").strip().lower()
    root_prefix = (data.get("root_prefix") or "").strip().lower()
    domain = (data.get("domain") or "claw.163.com").strip().lower()
    root_email = f"{root_prefix}@{domain}" if root_prefix else ""
    existing = db.execute(
        """
        SELECT * FROM accounts
        WHERE is_active = 1
          AND (
            api_key = ?
            OR (? != '' AND lower(COALESCE(user_email, '')) = ?)
            OR (? != '' AND lower(COALESCE(root_prefix, '') || '@' || COALESCE(domain, 'claw.163.com')) = ?)
          )
        LIMIT 1
        """,
        (api_key, user_email, user_email, root_email, root_email),
    ).fetchone()
    if existing:
        return dict(existing)
    with transaction():
        cur = db.execute(
            """
            INSERT INTO accounts
              (name, user_email, registered_email, api_key, dashboard_cookie, workspace_id, workspace_name, parent_mailbox_id,
               root_prefix, domain, telegram_enabled, telegram_bot_token, telegram_chat_id, telegram_api_base, sort_order, is_active)
            VALUES
              (:name, :user_email, :registered_email, :api_key, :dashboard_cookie, :workspace_id, :workspace_name, :parent_mailbox_id,
               :root_prefix, :domain, :telegram_enabled, :telegram_bot_token, :telegram_chat_id, :telegram_api_base, :sort_order, :is_active)
            """,
            {
                "name": data.get("name"),
                "user_email": data.get("user_email"),
                "registered_email": data.get("registered_email"),
                "api_key": api_key,
                "dashboard_cookie": data.get("dashboard_cookie"),
                "workspace_id": data.get("workspace_id"),
                "workspace_name": data.get("workspace_name"),
                "parent_mailbox_id": data.get("parent_mailbox_id"),
                "root_prefix": data.get("root_prefix"),
                "domain": data.get("domain") or "claw.163.com",
                "telegram_enabled": 1 if data.get("telegram_enabled") else 0,
                "telegram_bot_token": data.get("telegram_bot_token"),
                "telegram_chat_id": data.get("telegram_chat_id"),
                "telegram_api_base": data.get("telegram_api_base") or settings.telegram_api_base,
                "sort_order": data.get("sort_order") or next_sort_order(),
                "is_active": 1 if data.get("is_active", True) else 0,
            },
        )
    return get_account(cur.lastrowid)  # type: ignore[arg-type]


def update_account(account_id: int, data: dict[str, Any]) -> dict[str, Any] | None:
    fields = []
    params: dict[str, Any] = {"id": account_id}
    for key in [
        "name", "user_email", "registered_email", "api_key", "dashboard_cookie", "workspace_id", "workspace_name",
        "parent_mailbox_id", "root_prefix", "domain", "telegram_bot_token", "telegram_chat_id",
        "telegram_api_base", "sort_order"
    ]:
        if key in data:
            fields.append(f"{key} = :{key}")
            params[key] = data[key]
    for key in ["telegram_enabled", "is_active"]:
        if key in data:
            fields.append(f"{key} = :{key}")
            params[key] = 1 if data[key] else 0
    if not fields:
        return get_account(account_id)
    fields.append("updated_at = CURRENT_TIMESTAMP")
    with transaction():
        db.execute(f"UPDATE accounts SET {', '.join(fields)} WHERE id = :id", params)
    return get_account(account_id)


def next_sort_order() -> int:
    row = db.execute("SELECT COALESCE(MAX(sort_order), 0) + 10 AS next_order FROM accounts").fetchone()
    return int(row["next_order"])


def list_accounts(active_only: bool = False, dedupe: bool = True) -> list[dict[str, Any]]:
    if dedupe:
        dedupe_accounts()
    where = "WHERE is_active = 1" if active_only else ""
    return rows_to_dicts(db.execute(f"SELECT * FROM accounts {where} ORDER BY sort_order ASC, id ASC").fetchall())


def get_account(account_id: int | None) -> dict[str, Any] | None:
    if account_id is None:
        return None
    return row_to_dict(db.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone())


def get_default_account() -> dict[str, Any] | None:
    return row_to_dict(db.execute("SELECT * FROM accounts WHERE is_active = 1 ORDER BY sort_order ASC, id ASC LIMIT 1").fetchone())


def get_account_for_mailbox(email: str) -> dict[str, Any] | None:
    row = db.execute("SELECT account_id FROM mailboxes WHERE lower(email) = lower(?) LIMIT 1", (email,)).fetchone()
    if row and row["account_id"]:
        return get_account(row["account_id"])
    return get_default_account()


def delete_account(account_id: int) -> None:
    with transaction():
        db.execute("UPDATE accounts SET is_active = 0, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (account_id,))


def upsert_mailbox(data: dict[str, Any]) -> dict[str, Any]:
    with transaction():
        db.execute(
            """
            INSERT INTO mailboxes
              (id, email, prefix, display_name, account_id, status, openclaw_status, install_command, auth_url,
               comm_level, ext_receive_type, ext_send_type)
            VALUES
              (:id, :email, :prefix, :display_name, :account_id, :status, :openclaw_status, :install_command, :auth_url,
               :comm_level, :ext_receive_type, :ext_send_type)
            ON CONFLICT(id) DO UPDATE SET
              email = excluded.email, prefix = excluded.prefix, display_name = excluded.display_name,
              account_id = excluded.account_id, status = excluded.status, openclaw_status = excluded.openclaw_status,
              install_command = excluded.install_command, auth_url = excluded.auth_url, comm_level = excluded.comm_level,
              ext_receive_type = excluded.ext_receive_type, ext_send_type = excluded.ext_send_type,
              updated_at = CURRENT_TIMESTAMP
            ON CONFLICT(email) DO UPDATE SET
              id = excluded.id, prefix = excluded.prefix, display_name = excluded.display_name,
              account_id = excluded.account_id, status = excluded.status, openclaw_status = excluded.openclaw_status,
              install_command = excluded.install_command, auth_url = excluded.auth_url, comm_level = excluded.comm_level,
              ext_receive_type = excluded.ext_receive_type, ext_send_type = excluded.ext_send_type,
              updated_at = CURRENT_TIMESTAMP
            """,
            {
                "id": str(data["id"]),
                "email": data["email"].strip().lower(),
                "prefix": data.get("prefix") or data["email"].split("@")[0],
                "display_name": data.get("display_name") or data.get("displayName"),
                "account_id": data.get("account_id"),
                "status": data.get("status") or "active",
                "openclaw_status": data.get("openclaw_status") or data.get("openclawStatus"),
                "install_command": data.get("install_command") or data.get("installCommand"),
                "auth_url": data.get("auth_url") or data.get("authUrl"),
                "comm_level": data.get("comm_level") if data.get("comm_level") is not None else data.get("commLevel"),
                "ext_receive_type": data.get("ext_receive_type") if data.get("ext_receive_type") is not None else data.get("extReceiveType"),
                "ext_send_type": data.get("ext_send_type") if data.get("ext_send_type") is not None else data.get("extSendType"),
            },
        )
    return get_mailbox_by_id(str(data["id"]))  # type: ignore[return-value]


def list_mailboxes(include_deleted: bool = False, account_id: int | None = None) -> list[dict[str, Any]]:
    if not include_deleted:
        dedupe_mailboxes()
        cleanup_account_root_mailboxes()
    where = [] if include_deleted else ["status != 'deleted'"]
    params: list[Any] = []
    if not include_deleted:
        where.append("(account_id IS NULL OR account_id IN (SELECT id FROM accounts WHERE is_active = 1))")
    if account_id is not None:
        where.append("account_id = ?")
        params.append(account_id)
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    return rows_to_dicts(db.execute(f"SELECT * FROM mailboxes {clause} ORDER BY created_at DESC, email ASC", params).fetchall())


def list_active_mailboxes() -> list[dict[str, Any]]:
    return rows_to_dicts(db.execute(
        """
        SELECT * FROM mailboxes
        WHERE status = 'active'
          AND (account_id IS NULL OR account_id IN (SELECT id FROM accounts WHERE is_active = 1))
        ORDER BY email ASC
        """
    ).fetchall())


def get_mailbox_by_id(mailbox_id: str) -> dict[str, Any] | None:
    return row_to_dict(db.execute("SELECT * FROM mailboxes WHERE id = ?", (mailbox_id,)).fetchone())


def get_mailbox_by_email(email: str) -> dict[str, Any] | None:
    return row_to_dict(db.execute("SELECT * FROM mailboxes WHERE lower(email) = lower(?) AND status != 'deleted'", (email,)).fetchone())


def mark_mailbox_deleted(mailbox_id: str) -> None:
    with transaction():
        db.execute("UPDATE mailboxes SET status = 'deleted', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (mailbox_id,))


def update_mailbox_status(mailbox_id: str, status: str) -> dict[str, Any] | None:
    with transaction():
        db.execute("UPDATE mailboxes SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (status, mailbox_id))
    return get_mailbox_by_id(mailbox_id)


def update_mailbox_comm_settings(mailbox_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
    with transaction():
        db.execute(
            """
            UPDATE mailboxes
            SET comm_level = ?, ext_receive_type = ?, ext_send_type = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (data.get("comm_level"), data.get("ext_receive_type"), data.get("ext_send_type"), mailbox_id),
        )
    return get_mailbox_by_id(mailbox_id)


def mark_missing_mailboxes_deleted(account_id: int, remote_emails: list[str]) -> list[dict[str, Any]]:
    remote = {email.lower() for email in remote_emails}
    missing = [m for m in list_mailboxes(account_id=account_id) if m["email"].lower() not in remote]
    with transaction():
        for mailbox in missing:
            db.execute("UPDATE mailboxes SET status = 'deleted', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (mailbox["id"],))
    return missing


def save_mail(data: dict[str, Any]) -> dict[str, Any]:
    with transaction():
        db.execute(
            """
            INSERT INTO mails
              (provider_mail_id, mailbox_email, account_id, source, address, subject, text, html, raw_json,
               header_raw, has_attachments, received_at)
            VALUES
              (:provider_mail_id, :mailbox_email, :account_id, :source, :address, :subject, :text, :html, :raw_json,
               :header_raw, :has_attachments, :received_at)
            ON CONFLICT(mailbox_email, provider_mail_id) DO UPDATE SET
              account_id = excluded.account_id, source = excluded.source, address = excluded.address,
              subject = excluded.subject, text = excluded.text, html = excluded.html, raw_json = excluded.raw_json,
              header_raw = excluded.header_raw, has_attachments = excluded.has_attachments, received_at = excluded.received_at
            """,
            data,
        )
        row = db.execute(
            "SELECT * FROM mails WHERE mailbox_email = ? AND provider_mail_id = ?",
            (data["mailbox_email"], data["provider_mail_id"]),
        ).fetchone()
        db.execute("DELETE FROM attachments WHERE mail_id = ?", (row["id"],))
        for attachment in data.get("attachments", []):
            db.execute(
                "INSERT INTO attachments (mail_id, provider_part_id, filename, content_type, size) VALUES (?, ?, ?, ?, ?)",
                (row["id"], attachment["provider_part_id"], attachment.get("filename"), attachment.get("content_type"), attachment.get("size")),
            )
    return row_to_dict(row)  # type: ignore[return-value]


def mark_mail_notified(mail_id: int) -> None:
    with transaction():
        db.execute("UPDATE mails SET notified_at = CURRENT_TIMESTAMP WHERE id = ?", (mail_id,))


def list_mails(mailbox_email: str | None, account_id: int | None, limit: int, offset: int) -> dict[str, Any]:
    where: list[str] = []
    params: list[Any] = []
    if mailbox_email:
        where.append("mailbox_email = ?")
        params.append(mailbox_email)
    if account_id is not None:
        where.append("account_id = ?")
        params.append(account_id)
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    items = rows_to_dicts(db.execute(
        f"SELECT * FROM mails {clause} ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
        [*params, limit, offset],
    ).fetchall())
    count = db.execute(f"SELECT COUNT(*) AS count FROM mails {clause}", params).fetchone()["count"]
    return {"items": items, "count": count}


def list_mail_provider_ids(mailbox_email: str) -> list[str]:
    rows = db.execute("SELECT provider_mail_id FROM mails WHERE mailbox_email = ?", (mailbox_email,)).fetchall()
    return [row["provider_mail_id"] for row in rows]


def get_mail_by_id(mail_id: int) -> dict[str, Any] | None:
    return row_to_dict(db.execute("SELECT * FROM mails WHERE id = ?", (mail_id,)).fetchone())


def get_mail_by_provider_id(mailbox_email: str, provider_mail_id: str) -> dict[str, Any] | None:
    return row_to_dict(db.execute(
        "SELECT * FROM mails WHERE mailbox_email = ? AND provider_mail_id = ?",
        (mailbox_email, provider_mail_id),
    ).fetchone())


def delete_mail_by_id(mail_id: int) -> bool:
    with transaction():
        result = db.execute("DELETE FROM mails WHERE id = ?", (mail_id,))
    return result.rowcount > 0


def delete_mails_by_provider_ids(mailbox_email: str, provider_mail_ids: list[str]) -> int:
    count = 0
    with transaction():
        for provider_id in provider_mail_ids:
            count += db.execute(
                "DELETE FROM mails WHERE mailbox_email = ? AND provider_mail_id = ?",
                (mailbox_email, provider_id),
            ).rowcount
    return count


def list_attachments(mail_id: int) -> list[dict[str, Any]]:
    return rows_to_dicts(db.execute("SELECT * FROM attachments WHERE mail_id = ? ORDER BY id ASC", (mail_id,)).fetchall())


init_db()
