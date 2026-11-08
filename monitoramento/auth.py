import hashlib
import hmac
import re
import secrets
import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass
from email.utils import parseaddr

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
    email: str | None = None


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
            email TEXT,
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
        CREATE TABLE IF NOT EXISTS auth_password_reset_tokens (
            token_hash TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES auth_users(id) ON DELETE CASCADE,
            created_at INTEGER NOT NULL,
            expires_at INTEGER NOT NULL,
            used_at INTEGER
        );
        CREATE TABLE IF NOT EXISTS auth_password_reset_limits (
            bucket_hash TEXT PRIMARY KEY,
            attempts INTEGER NOT NULL,
            window_started_at INTEGER NOT NULL
        );
        """
    )
    columns = {
        row["name"] for row in connection.execute("PRAGMA table_info(auth_users)")
    }
    if "email" not in columns:
        connection.execute("ALTER TABLE auth_users ADD COLUMN email TEXT")
    connection.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_auth_users_email "
        "ON auth_users(email COLLATE NOCASE) WHERE email IS NOT NULL AND email != ''"
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


_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s.]+(?:\.[^@\s.]+)+$")


def _normalize_email(email: str | None) -> str | None:
    if email is None or not email.strip():
        return None
    normalized = email.strip().casefold()
    if len(normalized) > 254 or not _EMAIL.fullmatch(normalized):
        raise ValueError("Informe um endereço de e-mail válido.")
    try:
        display_name, parsed = parseaddr(normalized, strict=True)
    except ValueError as error:
        raise ValueError("Informe um endereço de e-mail válido.") from error
    if display_name or parsed.casefold() != normalized:
        raise ValueError("Informe um endereço de e-mail válido.")
    return normalized


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
    email: str | None = None,
) -> User:
    _validate_password(password)
    normalized_username, normalized_unit = _validate_account(username, role, unit)
    normalized_email = _normalize_email(email)
    salt = secrets.token_bytes(16)
    try:
        with closing(_connect()) as connection:
            _initialize(connection)
            cursor = connection.execute(
                """
                INSERT INTO auth_users (
                    username, password_hash, password_salt, role, unit,
                    active, must_change_password, email, created_at
                ) VALUES (?, ?, ?, ?, ?, 1, 1, ?, ?)
                """,
                (
                    normalized_username,
                    _password_hash(password, salt),
                    salt,
                    role,
                    normalized_unit,
                    normalized_email,
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
                True,
                normalized_email,
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
            True,
            row["email"],
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
            True,
            row["email"],
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


def admin_reset_user_password(user_id: int, password: str) -> None:
    _validate_password(password)
    salt = secrets.token_bytes(16)
    with closing(_connect()) as connection:
        _initialize(connection)
        target = connection.execute(
            "SELECT username FROM auth_users WHERE id = ? AND active = 1",
            (user_id,),
        ).fetchone()
        if target is None:
            raise ValueError("A conta ativa não foi encontrada.")
        connection.execute(
            """
            UPDATE auth_users SET password_hash = ?, password_salt = ?,
                must_change_password = 1 WHERE id = ?
            """,
            (_password_hash(password, salt), salt, user_id),
        )
        connection.execute("DELETE FROM auth_sessions WHERE user_id = ?", (user_id,))
        connection.execute(
            "DELETE FROM auth_password_reset_tokens WHERE user_id = ?", (user_id,)
        )
        connection.execute(
            "DELETE FROM auth_login_attempts WHERE username = ?",
            (target["username"],),
        )
        connection.commit()


def set_user_recovery_email(user_id: int, email: str | None) -> None:
    normalized_email = _normalize_email(email)
    with closing(_connect()) as connection:
        _initialize(connection)
        try:
            cursor = connection.execute(
                "UPDATE auth_users SET email = ? WHERE id = ?",
                (normalized_email, user_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("Conta não encontrada.")
            connection.execute(
                "DELETE FROM auth_password_reset_tokens WHERE user_id = ?",
                (user_id,),
            )
            connection.commit()
        except sqlite3.IntegrityError as error:
            raise ValueError("Esse e-mail já está associado a outra conta.") from error


def issue_password_reset_token(email: str, requester: str) -> tuple[str, str] | None:
    normalized_email = _normalize_email(email)
    if normalized_email is None:
        return None

    now = int(time.time())
    ip_bucket = hashlib.sha256(f"ip:{requester}".encode()).hexdigest()
    email_bucket = hashlib.sha256(f"email:{normalized_email}".encode()).hexdigest()
    limits = ((ip_bucket, 5), (email_bucket, 3))
    with closing(_connect()) as connection:
        _initialize(connection)
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """
            DELETE FROM auth_password_reset_tokens
            WHERE expires_at <= ? OR (used_at IS NOT NULL AND used_at <= ?)
            """,
            (now, now - 86400),
        )
        connection.execute(
            "DELETE FROM auth_password_reset_limits WHERE window_started_at <= ?",
            (now - 86400,),
        )
        for bucket_hash, limit in limits:
            row = connection.execute(
                "SELECT attempts, window_started_at FROM auth_password_reset_limits "
                "WHERE bucket_hash = ?",
                (bucket_hash,),
            ).fetchone()
            if row and row["window_started_at"] > now - 3600 and row["attempts"] >= limit:
                for limited_hash, _ in limits:
                    connection.execute(
                        """
                        INSERT INTO auth_password_reset_limits
                            (bucket_hash, attempts, window_started_at)
                        VALUES (?, 1, ?)
                        ON CONFLICT(bucket_hash) DO UPDATE SET
                            attempts = CASE
                                WHEN auth_password_reset_limits.window_started_at <= ?
                                THEN 1 ELSE auth_password_reset_limits.attempts + 1
                            END,
                            window_started_at = CASE
                                WHEN auth_password_reset_limits.window_started_at <= ?
                                THEN excluded.window_started_at
                                ELSE auth_password_reset_limits.window_started_at
                            END
                        """,
                        (limited_hash, now, now - 3600, now - 3600),
                    )
                connection.commit()
                return None

        for bucket_hash, _ in limits:
            connection.execute(
                """
                INSERT INTO auth_password_reset_limits
                    (bucket_hash, attempts, window_started_at)
                VALUES (?, 1, ?)
                ON CONFLICT(bucket_hash) DO UPDATE SET
                    attempts = CASE
                        WHEN auth_password_reset_limits.window_started_at <= ?
                        THEN 1 ELSE auth_password_reset_limits.attempts + 1
                    END,
                    window_started_at = CASE
                        WHEN auth_password_reset_limits.window_started_at <= ?
                        THEN excluded.window_started_at
                        ELSE auth_password_reset_limits.window_started_at
                    END
                """,
                (bucket_hash, now, now - 3600, now - 3600),
            )

        user = connection.execute(
            "SELECT id, email FROM auth_users WHERE email = ? COLLATE NOCASE AND active = 1",
            (normalized_email,),
        ).fetchone()
        if user is None:
            connection.commit()
            return None

        connection.execute(
            "DELETE FROM auth_password_reset_tokens WHERE user_id = ?",
            (user["id"],),
        )
        token = secrets.token_urlsafe(32)
        connection.execute(
            """
            INSERT INTO auth_password_reset_tokens (
                token_hash, user_id, created_at, expires_at
            ) VALUES (?, ?, ?, ?)
            """,
            (
                hashlib.sha256(token.encode()).hexdigest(),
                user["id"],
                now,
                now + 30 * 60,
            ),
        )
        connection.commit()
    return token, user["email"]


def allow_password_reset_attempt(requester: str) -> bool:
    now = int(time.time())
    bucket_hash = hashlib.sha256(f"reset-ip:{requester}".encode()).hexdigest()
    with closing(_connect()) as connection:
        _initialize(connection)
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "DELETE FROM auth_password_reset_limits WHERE window_started_at <= ?",
            (now - 86400,),
        )
        row = connection.execute(
            "SELECT attempts, window_started_at FROM auth_password_reset_limits "
            "WHERE bucket_hash = ?",
            (bucket_hash,),
        ).fetchone()
        if row and row["window_started_at"] > now - 3600 and row["attempts"] >= 10:
            connection.commit()
            return False
        connection.execute(
            """
            INSERT INTO auth_password_reset_limits
                (bucket_hash, attempts, window_started_at)
            VALUES (?, 1, ?)
            ON CONFLICT(bucket_hash) DO UPDATE SET
                attempts = CASE
                    WHEN auth_password_reset_limits.window_started_at <= ?
                    THEN 1 ELSE auth_password_reset_limits.attempts + 1
                END,
                window_started_at = CASE
                    WHEN auth_password_reset_limits.window_started_at <= ?
                    THEN excluded.window_started_at
                    ELSE auth_password_reset_limits.window_started_at
                END
            """,
            (bucket_hash, now, now - 3600, now - 3600),
        )
        connection.commit()
    return True


def invalidate_password_reset_token(token: str) -> None:
    if not token or len(token) > 128:
        return
    with closing(_connect()) as connection:
        _initialize(connection)
        connection.execute(
            "DELETE FROM auth_password_reset_tokens WHERE token_hash = ?",
            (hashlib.sha256(token.encode()).hexdigest(),),
        )
        connection.commit()


def reset_password_with_token(token: str, password: str) -> bool:
    _validate_password(password)
    if not token or len(token) > 128:
        return False
    now = int(time.time())
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    salt = secrets.token_bytes(16)
    password_hash = _password_hash(password, salt)
    with closing(_connect()) as connection:
        _initialize(connection)
        connection.execute("BEGIN IMMEDIATE")
        reset = connection.execute(
            """
            SELECT t.user_id FROM auth_password_reset_tokens AS t
            JOIN auth_users AS u ON u.id = t.user_id
            WHERE t.token_hash = ? AND t.used_at IS NULL
                AND t.expires_at > ? AND u.active = 1
            """,
            (token_hash, now),
        ).fetchone()
        if reset is None:
            connection.commit()
            return False
        connection.execute(
            """
            UPDATE auth_users SET password_hash = ?, password_salt = ?,
                must_change_password = 0 WHERE id = ?
            """,
            (password_hash, salt, reset["user_id"]),
        )
        connection.execute(
            "UPDATE auth_password_reset_tokens SET used_at = ? WHERE token_hash = ?",
            (now, token_hash),
        )
        connection.execute(
            "DELETE FROM auth_sessions WHERE user_id = ?", (reset["user_id"],)
        )
        connection.commit()
    return True


def list_users() -> tuple[User, ...]:
    with closing(_connect()) as connection:
        _initialize(connection)
        rows = connection.execute(
            "SELECT id, username, role, unit, must_change_password, active, email "
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
            row["email"],
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
        connection.execute(
            "DELETE FROM auth_password_reset_tokens WHERE user_id = ?", (user_id,)
        )
        connection.commit()


def delete_user(user_id: int, actor_id: int) -> None:
    if user_id == actor_id:
        raise ValueError("Não é possível excluir a própria conta.")
    with closing(_connect()) as connection:
        _initialize(connection)
        target = connection.execute(
            "SELECT username, role, active FROM auth_users WHERE id = ?",
            (user_id,),
        ).fetchone()
        if target is None:
            raise ValueError("A conta não existe.")
        if target["role"] == "admin" and target["active"]:
            admin_count = connection.execute(
                "SELECT COUNT(*) FROM auth_users WHERE role = 'admin' AND active = 1"
            ).fetchone()[0]
            if admin_count <= 1:
                raise ValueError("Mantenha pelo menos um administrador ativo.")
        connection.execute("DELETE FROM auth_sessions WHERE user_id = ?", (user_id,))
        connection.execute(
            "DELETE FROM auth_password_reset_tokens WHERE user_id = ?", (user_id,)
        )
        connection.execute(
            "DELETE FROM auth_login_attempts WHERE username = ?",
            (target["username"],),
        )
        connection.execute("DELETE FROM auth_users WHERE id = ?", (user_id,))
        connection.commit()
