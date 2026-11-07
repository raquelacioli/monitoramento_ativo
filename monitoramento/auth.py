import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass

from monitoramento.tracking_store import database_path

PASSWORD_ITERATIONS = 600_000
SESSION_TTL_SECONDS = 60 * 60
LOGIN_FAILURE_LIMIT = 5
LOGIN_LOCK_SECONDS = 15 * 60
ROLES = ("unit", "surveillance", "admin")
COOKIE_NAME = "monitoramento_session"
_DUMMY_SALT = secrets.token_bytes(16)
_USERNAME = re.compile(r"^[A-Za-z0-9._@+-]{3,80}$")


@dataclass(frozen=True)
class User:
    id: int
    username: str
    role: str
    unit: str | None
    must_change_password: bool
    active: bool = True


def _connect() -> sqlite3.Connection:
    path = database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=5)
    connection.row_factory = sqlite3.Row
    return connection


def _initialize(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS auth_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash BLOB NOT NULL,
            password_salt BLOB NOT NULL,
            role TEXT NOT NULL CHECK (role IN ('unit', 'surveillance', 'admin')),
            unit TEXT,
            active INTEGER NOT NULL DEFAULT 1,
            must_change_password INTEGER NOT NULL DEFAULT 1,
            created_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS auth_sessions (
            token_hash TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES auth_users(id) ON DELETE CASCADE,
            csrf_token TEXT NOT NULL,
            expires_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS auth_login_attempts (
            username TEXT PRIMARY KEY,
            failures INTEGER NOT NULL,
            locked_until INTEGER NOT NULL DEFAULT 0
        );
        """
    )


def _password_hash(password: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS
    )


def _validate_account(username: str, role: str, unit: str | None) -> tuple[str, str | None]:
    normalized_username = username.strip().casefold()
    if not _USERNAME.fullmatch(username.strip()):
        raise ValueError("Usuário: use de 3 a 80 letras, números ou . _ @ + -.")
    if role not in ROLES:
        raise ValueError("Perfil de acesso inválido.")
    normalized_unit = unit.strip() if unit and unit.strip() else None
    if role == "unit" and not normalized_unit:
        raise ValueError("Informe a unidade vinculada ao profissional.")
    if role != "unit":
        normalized_unit = None
    if normalized_unit and len(normalized_unit) > 180:
        raise ValueError("O nome da unidade deve ter no máximo 180 caracteres.")
    return normalized_username, normalized_unit


def _validate_password(password: str) -> None:
    if len(password) < 12:
        raise ValueError("A senha deve ter pelo menos 12 caracteres.")
    if len(password) > 256:
        raise ValueError("A senha deve ter no máximo 256 caracteres.")


def create_first_admin(username: str, password: str) -> User:
    _validate_password(password)
    normalized_username, _ = _validate_account(username, "admin", None)
    salt = secrets.token_bytes(16)
    with closing(_connect()) as connection:
        _initialize(connection)
        if connection.execute(
            "SELECT 1 FROM auth_users WHERE role = 'admin' LIMIT 1"
        ).fetchone():
            raise ValueError("Já existe uma conta administradora.")
        cursor = connection.execute(
            """
            INSERT INTO auth_users (
                username, password_hash, password_salt, role, unit,
                active, must_change_password, created_at
            ) VALUES (?, ?, ?, 'admin', NULL, 1, 0, ?)
            """,
            (
                normalized_username,
                _password_hash(password, salt),
                salt,
                int(time.time()),
            ),
        )
        connection.commit()
        return User(cursor.lastrowid, normalized_username, "admin", None, False)


def create_user(
    username: str,
    password: str,
    role: str,
    unit: str | None,
) -> User:
    _validate_password(password)
    normalized_username, normalized_unit = _validate_account(username, role, unit)
    salt = secrets.token_bytes(16)
    try:
        with closing(_connect()) as connection:
            _initialize(connection)
            cursor = connection.execute(
                """
                INSERT INTO auth_users (
                    username, password_hash, password_salt, role, unit,
                    active, must_change_password, created_at
                ) VALUES (?, ?, ?, ?, ?, 1, 1, ?)
                """,
                (
                    normalized_username,
                    _password_hash(password, salt),
                    salt,
                    role,
                    normalized_unit,
                    int(time.time()),
                ),
            )
            connection.commit()
            return User(
                cursor.lastrowid,
                normalized_username,
                role,
                normalized_unit,
                True,
            )
    except sqlite3.IntegrityError as error:
        raise ValueError("Esse nome de usuário já está cadastrado.") from error


def authenticate(username: str, password: str) -> User | None:
    normalized_username = username.strip().casefold()
    now = int(time.time())
    with closing(_connect()) as connection:
        _initialize(connection)
        row = connection.execute(
            "SELECT * FROM auth_users WHERE username = ? AND active = 1",
            (normalized_username,),
        ).fetchone()
        attempt = connection.execute(
            "SELECT failures, locked_until FROM auth_login_attempts WHERE username = ?",
            (normalized_username,),
        ).fetchone()
        if attempt and attempt["locked_until"] > now:
            connection.commit()
            return None
        salt = bytes(row["password_salt"]) if row else _DUMMY_SALT
        expected = bytes(row["password_hash"]) if row else _password_hash(
            "not-a-real-password", _DUMMY_SALT
        )
        supplied = _password_hash(password[:256], salt)
        valid = hmac.compare_digest(supplied, expected)
        if not row or not valid:
            failures = (attempt["failures"] if attempt else 0) + 1
            locked_until = now + LOGIN_LOCK_SECONDS if failures >= LOGIN_FAILURE_LIMIT else 0
            connection.execute(
                """
                INSERT INTO auth_login_attempts (username, failures, locked_until)
                VALUES (?, ?, ?)
                ON CONFLICT(username) DO UPDATE SET
                    failures = excluded.failures,
                    locked_until = excluded.locked_until
                """,
                (normalized_username[:80], failures, locked_until),
            )
            connection.commit()
            return None

        connection.execute(
            "DELETE FROM auth_login_attempts WHERE username = ?",
            (normalized_username,),
        )
        connection.commit()
        return User(
            row["id"],
            row["username"],
            row["role"],
            row["unit"],
            bool(row["must_change_password"]),
        )


def create_session(user_id: int) -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(32)
    expires_at = int(time.time()) + SESSION_TTL_SECONDS
    with closing(_connect()) as connection:
        _initialize(connection)
        connection.execute(
            "INSERT INTO auth_sessions (token_hash, user_id, csrf_token, expires_at) "
            "VALUES (?, ?, ?, ?)",
            (hashlib.sha256(token.encode()).hexdigest(), user_id, csrf_token, expires_at),
        )
        connection.commit()
    return token, csrf_token


def get_session(token: str | None) -> tuple[User, str] | None:
    if not token or len(token) > 128:
        return None
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    now = int(time.time())
    with closing(_connect()) as connection:
        _initialize(connection)
        row = connection.execute(
            """
            SELECT s.csrf_token, u.*
            FROM auth_sessions AS s
            JOIN auth_users AS u ON u.id = s.user_id
            WHERE s.token_hash = ? AND s.expires_at > ? AND u.active = 1
            """,
            (token_hash, now),
        ).fetchone()
        connection.execute("DELETE FROM auth_sessions WHERE expires_at <= ?", (now,))
        connection.commit()
    if row is None:
        return None
    return (
        User(
            row["id"],
            row["username"],
            row["role"],
            row["unit"],
            bool(row["must_change_password"]),
        ),
        row["csrf_token"],
    )


def validate_csrf(token: str | None, expected: str | None) -> bool:
    return bool(token and expected and hmac.compare_digest(token, expected))


def revoke_session(token: str | None) -> None:
    if not token or len(token) > 128:
        return
    with closing(_connect()) as connection:
        _initialize(connection)
        connection.execute(
            "DELETE FROM auth_sessions WHERE token_hash = ?",
            (hashlib.sha256(token.encode()).hexdigest(),),
        )
        connection.commit()


def change_password(user_id: int, password: str) -> None:
    _validate_password(password)
    salt = secrets.token_bytes(16)
    with closing(_connect()) as connection:
        _initialize(connection)
        connection.execute(
            """
            UPDATE auth_users SET password_hash = ?, password_salt = ?,
                must_change_password = 0 WHERE id = ?
            """,
            (_password_hash(password, salt), salt, user_id),
        )
        connection.execute("DELETE FROM auth_sessions WHERE user_id = ?", (user_id,))
        connection.commit()


def list_users() -> tuple[User, ...]:
    with closing(_connect()) as connection:
        _initialize(connection)
        rows = connection.execute(
            "SELECT id, username, role, unit, must_change_password, active "
            "FROM auth_users ORDER BY username"
        ).fetchall()
    return tuple(
        User(
            row["id"],
            row["username"],
            row["role"],
            row["unit"],
            bool(row["must_change_password"]),
            bool(row["active"]),
        )
        for row in rows
    )


def deactivate_user(user_id: int, actor_id: int) -> None:
    if user_id == actor_id:
        raise ValueError("Não é possível desativar a própria conta.")
    with closing(_connect()) as connection:
        _initialize(connection)
        target = connection.execute(
            "SELECT role, active FROM auth_users WHERE id = ?", (user_id,)
        ).fetchone()
        if target is None or not target["active"]:
            raise ValueError("A conta já está desativada ou não existe.")
        if target["role"] == "admin":
            admin_count = connection.execute(
                "SELECT COUNT(*) FROM auth_users WHERE role = 'admin' AND active = 1"
            ).fetchone()[0]
            if admin_count <= 1:
                raise ValueError("Mantenha pelo menos um administrador ativo.")
        connection.execute("UPDATE auth_users SET active = 0 WHERE id = ?", (user_id,))
        connection.execute("DELETE FROM auth_sessions WHERE user_id = ?", (user_id,))
        connection.commit()
