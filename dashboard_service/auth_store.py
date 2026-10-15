from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DB_PATH = Path(
    os.getenv(
        "AUTH_DB_PATH",
        str(Path(__file__).resolve().parent / "data" / "airguard_users.db"),
    )
)
PBKDF2_ROUNDS = 260_000
DEFAULT_ADMIN_USERNAME = "admin"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _row_to_user(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "id": row["id"],
        "username": row["username"],
        "role": row["role"],
        "is_active": bool(row["is_active"]),
        "created_by_admin_id": row["created_by_admin_id"],
        "created_by_admin_username": row["created_by_admin_username"] if "created_by_admin_username" in row.keys() else None,
        "created_at": row["created_at"],
        "last_login_at": row["last_login_at"],
    }


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    derived_key = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PBKDF2_ROUNDS,
    )
    return "pbkdf2_sha256${rounds}${salt}${hash}".format(
        rounds=PBKDF2_ROUNDS,
        salt=base64.urlsafe_b64encode(salt).decode("ascii"),
        hash=base64.urlsafe_b64encode(derived_key).decode("ascii"),
    )


def verify_password(password: str, encoded_password: str) -> bool:
    try:
        algorithm, rounds_text, salt_text, hash_text = encoded_password.split("$", 3)
    except ValueError:
        return False

    if algorithm != "pbkdf2_sha256":
        return False

    try:
        rounds = int(rounds_text)
        salt = base64.urlsafe_b64decode(salt_text.encode("ascii"))
        expected_hash = base64.urlsafe_b64decode(hash_text.encode("ascii"))
    except Exception:
        return False

    derived_key = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        rounds,
    )
    return hmac.compare_digest(derived_key, expected_hash)


def initialize_database(admin_username: str = DEFAULT_ADMIN_USERNAME, admin_password: str = "password") -> None:
    connection = _connect()
    try:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('admin', 'user')),
                is_active INTEGER NOT NULL DEFAULT 1,
                created_by_admin_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
                created_at TEXT NOT NULL,
                last_login_at TEXT
            )
            """
        )
        connection.commit()

        admin_row = connection.execute(
            "SELECT id FROM users WHERE username = ? LIMIT 1",
            (admin_username,),
        ).fetchone()
        encoded_password = hash_password(admin_password)
        if admin_row is None:
            connection.execute(
                """
                INSERT INTO users (username, password_hash, role, is_active, created_at)
                VALUES (?, ?, 'admin', 1, ?)
                """,
                (admin_username, encoded_password, _utc_now()),
            )
        else:
            connection.execute(
                """
                UPDATE users
                SET password_hash = ?, role = 'admin', is_active = 1, created_by_admin_id = NULL
                WHERE id = ?
                """,
                (encoded_password, admin_row["id"]),
            )
        connection.commit()
    finally:
        connection.close()


def sync_admin_password(admin_username: str, admin_password: str) -> None:
    connection = _connect()
    try:
        row = connection.execute(
            "SELECT id FROM users WHERE username = ? AND role = 'admin' LIMIT 1",
            (admin_username,),
        ).fetchone()
        encoded_password = hash_password(admin_password)
        if row is None:
            connection.execute(
                """
                INSERT INTO users (username, password_hash, role, is_active, created_at)
                VALUES (?, ?, 'admin', 1, ?)
                """,
                (admin_username, encoded_password, _utc_now()),
            )
        else:
            connection.execute(
                "UPDATE users SET password_hash = ?, is_active = 1 WHERE id = ?",
                (encoded_password, row["id"]),
            )
        connection.commit()
    finally:
        connection.close()


def get_user_by_id(user_id: int) -> dict[str, Any] | None:
    connection = _connect()
    try:
        row = connection.execute(
            """
            SELECT u.id, u.username, u.role, u.is_active, u.created_by_admin_id,
                   a.username AS created_by_admin_username, u.created_at, u.last_login_at
            FROM users u
            LEFT JOIN users a ON a.id = u.created_by_admin_id
            WHERE u.id = ?
            LIMIT 1
            """,
            (user_id,),
        ).fetchone()
        return _row_to_user(row)
    finally:
        connection.close()


def get_user_by_username(username: str) -> dict[str, Any] | None:
    connection = _connect()
    try:
        row = connection.execute(
            """
            SELECT u.id, u.username, u.role, u.is_active, u.created_by_admin_id,
                   a.username AS created_by_admin_username, u.created_at, u.last_login_at,
                   u.password_hash
            FROM users u
            LEFT JOIN users a ON a.id = u.created_by_admin_id
            WHERE u.username = ?
            LIMIT 1
            """,
            (username,),
        ).fetchone()
        return _row_to_user(row)
    finally:
        connection.close()


def list_admins() -> list[dict[str, Any]]:
    connection = _connect()
    try:
        rows = connection.execute(
            """
            SELECT id, username, role, is_active, created_at, last_login_at
            FROM users
            WHERE role = 'admin' AND is_active = 1
            ORDER BY username
            """
        ).fetchall()
        return [
            {
                "id": row["id"],
                "username": row["username"],
                "role": row["role"],
                "is_active": bool(row["is_active"]),
                "created_at": row["created_at"],
                "last_login_at": row["last_login_at"],
            }
            for row in rows
        ]
    finally:
        connection.close()


def list_users_for_admin(admin_id: int) -> list[dict[str, Any]]:
    connection = _connect()
    try:
        rows = connection.execute(
            """
            SELECT u.id, u.username, u.role, u.is_active, u.created_by_admin_id,
                   a.username AS created_by_admin_username, u.created_at, u.last_login_at
            FROM users u
            LEFT JOIN users a ON a.id = u.created_by_admin_id
            WHERE u.role = 'user' AND u.created_by_admin_id = ?
            ORDER BY u.created_at DESC, u.username ASC
            """,
            (admin_id,),
        ).fetchall()
        return [_row_to_user(row) for row in rows if row is not None]
    finally:
        connection.close()


def authenticate_user(username: str, password: str) -> dict[str, Any] | None:
    connection = _connect()
    try:
        row = connection.execute(
            """
            SELECT u.id, u.username, u.role, u.is_active, u.created_by_admin_id,
                   a.username AS created_by_admin_username, u.created_at, u.last_login_at,
                   u.password_hash
            FROM users u
            LEFT JOIN users a ON a.id = u.created_by_admin_id
            WHERE u.username = ?
            LIMIT 1
            """,
            (username,),
        ).fetchone()
        if row is None or not row["is_active"]:
            return None
        if not verify_password(password, row["password_hash"]):
            return None
        connection.execute(
            "UPDATE users SET last_login_at = ? WHERE id = ?",
            (_utc_now(), row["id"]),
        )
        connection.commit()
        return _row_to_user(row)
    finally:
        connection.close()


def create_user(username: str, password: str, created_by_admin_id: int) -> dict[str, Any]:
    connection = _connect()
    try:
        admin_row = connection.execute(
            "SELECT id FROM users WHERE id = ? AND role = 'admin' AND is_active = 1 LIMIT 1",
            (created_by_admin_id,),
        ).fetchone()
        if admin_row is None:
            raise ValueError("Admin user not found or inactive")

        existing = connection.execute(
            "SELECT id FROM users WHERE username = ? LIMIT 1",
            (username,),
        ).fetchone()
        if existing is not None:
            raise ValueError("Username already exists")

        encoded_password = hash_password(password)
        connection.execute(
            """
            INSERT INTO users (username, password_hash, role, is_active, created_by_admin_id, created_at)
            VALUES (?, ?, 'user', 1, ?, ?)
            """,
            (username, encoded_password, created_by_admin_id, _utc_now()),
        )
        connection.commit()

        user = connection.execute(
            """
            SELECT u.id, u.username, u.role, u.is_active, u.created_by_admin_id,
                   a.username AS created_by_admin_username, u.created_at, u.last_login_at
            FROM users u
            LEFT JOIN users a ON a.id = u.created_by_admin_id
            WHERE u.username = ?
            LIMIT 1
            """,
            (username,),
        ).fetchone()
        return _row_to_user(user)
    finally:
        connection.close()


def set_user_active(user_id: int, is_active: bool, admin_id: int | None = None) -> dict[str, Any]:
    connection = _connect()
    try:
        row = connection.execute(
            """
            SELECT id, role, created_by_admin_id
            FROM users
            WHERE id = ?
            LIMIT 1
            """,
            (user_id,),
        ).fetchone()
        if row is None:
            raise ValueError("User not found")
        if row["role"] != "user":
            raise ValueError("Only normal users can be disabled or enabled")
        if admin_id is not None and row["created_by_admin_id"] != admin_id:
            raise ValueError("User is not owned by this admin")

        connection.execute(
            "UPDATE users SET is_active = ? WHERE id = ?",
            (1 if is_active else 0, user_id),
        )
        connection.commit()
        updated = connection.execute(
            """
            SELECT u.id, u.username, u.role, u.is_active, u.created_by_admin_id,
                   a.username AS created_by_admin_username, u.created_at, u.last_login_at
            FROM users u
            LEFT JOIN users a ON a.id = u.created_by_admin_id
            WHERE u.id = ?
            LIMIT 1
            """,
            (user_id,),
        ).fetchone()
        return _row_to_user(updated)
    finally:
        connection.close()


def delete_user(user_id: int, admin_id: int | None = None) -> None:
    connection = _connect()
    try:
        row = connection.execute(
            """
            SELECT id, role, created_by_admin_id
            FROM users
            WHERE id = ?
            LIMIT 1
            """,
            (user_id,),
        ).fetchone()
        if row is None:
            raise ValueError("User not found")
        if row["role"] != "user":
            raise ValueError("Only normal users can be deleted")
        if admin_id is not None and row["created_by_admin_id"] != admin_id:
            raise ValueError("User is not owned by this admin")

        connection.execute("DELETE FROM users WHERE id = ?", (user_id,))
        connection.commit()
    finally:
        connection.close()
