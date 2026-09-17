"""
OSAP Authentication Module
===========================
Provides simple token-based authentication for the Web Dashboard.

- Passwords stored as SHA-256 hashes (no extra deps)
- Session tokens: random 64-hex strings stored in SQLite
- Token expiry: 30 days
- Admin flag: first account (id=1) is always admin
"""

from __future__ import annotations

import hashlib
import os
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from osap.utils.logger import get_logger

_log = get_logger(__name__)

TOKEN_EXPIRY_DAYS = 30


# ---------------------------------------------------------------------------
# Password helpers
# ---------------------------------------------------------------------------

def hash_password(password: str) -> str:
    """Return SHA-256 hex digest of the password."""
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def verify_password(password: str, hashed: str) -> bool:
    """Compare plain-text password against its stored hash."""
    return hashlib.sha256(password.encode("utf-8")).hexdigest() == hashed


# ---------------------------------------------------------------------------
# Session token helpers
# ---------------------------------------------------------------------------

def generate_token() -> str:
    """Generate a cryptographically random 64-hex session token."""
    return secrets.token_hex(32)


def token_expiry() -> str:
    """Return ISO-8601 string for expiry timestamp (now + TOKEN_EXPIRY_DAYS)."""
    return (datetime.utcnow() + timedelta(days=TOKEN_EXPIRY_DAYS)).isoformat()


# ---------------------------------------------------------------------------
# DB helpers (auth schema migration)
# ---------------------------------------------------------------------------

AUTH_SCHEMA = """
-- Users table stores login credentials for each OSAP account
CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id      INTEGER NOT NULL UNIQUE REFERENCES accounts(id) ON DELETE CASCADE,
    username        TEXT    NOT NULL UNIQUE COLLATE NOCASE,
    password_hash   TEXT    NOT NULL,
    is_admin        INTEGER DEFAULT 0,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Sessions stores active bearer tokens
CREATE TABLE IF NOT EXISTS sessions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    account_id  INTEGER NOT NULL,
    token       TEXT    NOT NULL UNIQUE,
    expires_at  DATETIME NOT NULL,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_sessions_token ON sessions(token);
CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at);

-- Audit logs track employee activities (upload, delete, post, settings)
CREATE TABLE IF NOT EXISTS audit_logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER,
    username    TEXT,
    account_id  INTEGER,
    action      TEXT NOT NULL,
    details     TEXT DEFAULT '',
    ip_address  TEXT DEFAULT '',
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_audit_logs_created ON audit_logs(created_at DESC);
"""


def init_auth_schema(db_path: str | Path) -> None:
    """Apply auth schema migrations (idempotent — uses IF NOT EXISTS)."""
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    try:
        conn.executescript(AUTH_SCHEMA)
        conn.commit()
        _log.info("Auth schema initialized.")
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# User management
# ---------------------------------------------------------------------------

def create_user(
    db_path: str | Path,
    username: str,
    password: str,
    account_id: int,
    is_admin: bool = False,
) -> dict:
    """
    Create a new user linked to an existing account.
    Raises ValueError if username already exists.
    """
    from osap.db.models import db_session

    pw_hash = hash_password(password)
    with db_session(db_path) as conn:
        try:
            conn.execute(
                "INSERT INTO users (account_id, username, password_hash, is_admin) VALUES (?, ?, ?, ?)",
                (account_id, username.strip(), pw_hash, 1 if is_admin else 0),
            )
        except sqlite3.IntegrityError as e:
            raise ValueError(f"Username '{username}' sudah ada atau account_id tidak valid: {e}")

        row = conn.execute(
            "SELECT id, account_id, username, is_admin, created_at FROM users WHERE username = ? COLLATE NOCASE",
            (username.strip(),),
        ).fetchone()
        return dict(row)


def get_user_by_username(db_path: str | Path, username: str) -> Optional[dict]:
    """Return user row dict (including password_hash) or None."""
    from osap.db.models import get_conn

    conn = get_conn(db_path)
    try:
        row = conn.execute(
            "SELECT id, account_id, username, password_hash, is_admin FROM users WHERE username = ? COLLATE NOCASE",
            (username.strip(),),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def list_users(db_path: str | Path) -> list[dict]:
    """Return all users (without password_hash)."""
    from osap.db.models import get_conn

    conn = get_conn(db_path)
    try:
        rows = conn.execute(
            "SELECT u.id, u.account_id, u.username, u.is_admin, u.created_at, a.name as account_name "
            "FROM users u JOIN accounts a ON u.account_id = a.id ORDER BY u.id"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def delete_user(db_path: str | Path, user_id: int) -> bool:
    """Delete user by id, revoke sessions, delete associated account profile and reset autoincrement sequence."""
    from osap.db.models import db_session

    with db_session(db_path) as conn:
        user_row = conn.execute("SELECT account_id FROM users WHERE id = ?", (user_id,)).fetchone()
        if not user_row:
            return False
        account_id = user_row["account_id"]

        cur = conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))

        # Delete linked account profile if not default account 1
        if account_id and account_id != 1:
            conn.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
            try:
                conn.execute("DELETE FROM account_settings WHERE account_id = ?", (account_id,))
            except Exception:
                pass
            conn.execute("DELETE FROM videos WHERE account_id = ?", (account_id,))

        # Reset sqlite autoincrement sequence so next ID starts cleanly
        try:
            conn.execute("UPDATE sqlite_sequence SET seq = (SELECT COALESCE(MAX(id), 0) FROM users) WHERE name = 'users'")
            conn.execute("UPDATE sqlite_sequence SET seq = (SELECT COALESCE(MAX(id), 0) FROM accounts) WHERE name = 'accounts'")
        except Exception:
            pass

        return cur.rowcount > 0


def update_user_password(db_path: str | Path, user_id: int, new_password: str) -> bool:
    """Update a user's password hash. Returns True on success."""
    from osap.db.models import db_session

    pw_hash = hash_password(new_password)
    with db_session(db_path) as conn:
        cur = conn.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (pw_hash, user_id),
        )
        return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------

def create_session(db_path: str | Path, user_id: int, account_id: int) -> str:
    """Create a new session for a user. Returns the raw token string."""
    from osap.db.models import db_session

    token = generate_token()
    expires = token_expiry()
    with db_session(db_path) as conn:
        conn.execute(
            "INSERT INTO sessions (user_id, account_id, token, expires_at) VALUES (?, ?, ?, ?)",
            (user_id, account_id, token, expires),
        )
    return token


def validate_token(db_path: str | Path, token: str) -> Optional[dict]:
    """
    Validate a session token.
    Returns a dict with {user_id, account_id, username, is_admin} if valid, else None.
    Automatically deletes expired tokens.
    """
    from osap.db.models import get_conn

    if not token:
        return None

    conn = get_conn(db_path)
    try:
        now = datetime.utcnow().isoformat()
        # Clean expired sessions opportunistically
        conn.execute("DELETE FROM sessions WHERE expires_at < ?", (now,))
        conn.commit()

        row = conn.execute(
            """
            SELECT s.user_id, s.account_id, u.username, u.is_admin
            FROM sessions s
            JOIN users u ON s.user_id = u.id
            WHERE s.token = ? AND s.expires_at > ?
            """,
            (token, now),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def revoke_token(db_path: str | Path, token: str) -> None:
    """Delete a specific session token (logout)."""
    from osap.db.models import db_session

    with db_session(db_path) as conn:
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))


def revoke_all_user_sessions(db_path: str | Path, user_id: int) -> None:
    """Revoke all active sessions for a given user."""
    from osap.db.models import db_session

    with db_session(db_path) as conn:
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))


# ---------------------------------------------------------------------------
# Bootstrap: ensure default admin exists
# ---------------------------------------------------------------------------

def ensure_default_admin(db_path: str | Path, default_password: str = "admin123") -> None:
    """
    If no users exist at all, create a default admin user tied to account id=1.
    This runs on server startup so the system is never locked out.
    """
    from osap.db.models import get_conn

    conn = get_conn(db_path)
    try:
        count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    finally:
        conn.close()

    if count == 0:
        try:
            create_user(
                db_path=db_path,
                username="admin",
                password=default_password,
                account_id=1,
                is_admin=True,
            )
            _log.warning(
                "⚠️  Default admin user created: username='admin' password='admin123'. "
                "PLEASE CHANGE THIS PASSWORD immediately via Settings!"
            )
        except Exception as e:
            _log.error(f"Failed to create default admin: {e}")


def log_audit_event(
    db_path: str | Path,
    action: str,
    details: str = "",
    user_id: int | None = None,
    username: str = "",
    account_id: int | None = None,
    ip_address: str = "",
) -> None:
    """Record an operational action to the audit_logs table."""
    from osap.db.models import db_session
    try:
        with db_session(db_path) as conn:
            conn.execute(
                """
                INSERT INTO audit_logs (user_id, username, account_id, action, details, ip_address)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (user_id, username, account_id, action, details, ip_address),
            )
    except Exception as e:
        _log.debug("Audit log recording error: %s", e)


def get_audit_logs(
    db_path: str | Path,
    limit: int = 100,
    offset: int = 0,
    account_id: int | None = None,
) -> list[dict[str, Any]]:
    """Fetch recent audit log entries."""
    from osap.db.models import db_session
    with db_session(db_path) as conn:
        if account_id is not None:
            rows = conn.execute(
                """
                SELECT id, user_id, username, account_id, action, details, ip_address, created_at
                FROM audit_logs
                WHERE account_id = ?
                ORDER BY id DESC LIMIT ? OFFSET ?
                """,
                (account_id, limit, offset),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT id, user_id, username, account_id, action, details, ip_address, created_at
                FROM audit_logs
                ORDER BY id DESC LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()
        return [dict(r) for r in rows]

