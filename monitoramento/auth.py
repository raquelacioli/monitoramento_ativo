import hashlib
import hmac
import re
import secrets
import time
from dataclasses import dataclass
from email.utils import parseaddr

from monitoramento.firestore_store import get_store, key, snapshot_read

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


def _user(row):
    return User(row['id'], row['username'], row['role'], row.get('unit'),
                bool(row['must_change_password']), bool(row.get('active', True)), row.get('email'))


def _run(callback):
    return get_store().run(callback, guard='auth')


def _create(username, password, role, unit, email=None, first=False):
    _validate_password(password)
    username, unit = _validate_account(username, role, unit)
    email = _normalize_email(email)
    salt = secrets.token_bytes(16)
    password_hash = _password_hash(password, salt)
    def create(tx):
        if first and tx.query('auth_users', [('role', '==', 'admin')]):
            raise ValueError('Já existe uma conta administradora.')
        if tx.get('auth_names', key(username)):
            raise ValueError('Esse nome de usuário já está cadastrado.')
        if email and tx.get('auth_emails', key(email)):
            raise ValueError('Esse e-mail já está associado a outra conta.')
        user_id = tx.next_id('auth_users')
        row = dict(id=user_id, username=username, role=role, unit=unit, email=email,
                   password_hash=password_hash, password_salt=salt, active=True,
                   must_change_password=not first, created_at=int(time.time()),
                   session_version=0, reset_version=0)
        tx.set('auth_users', key(user_id), row)
        tx.set('auth_names', key(username), {'user_id': user_id})
        if email: tx.set('auth_emails', key(email), {'user_id': user_id})
        return _user(row)
    return _run(create)


def create_first_admin(username: str, password: str) -> User:
    return _create(username, password, 'admin', None, first=True)


def create_user(username: str, password: str, role: str, unit: str | None,
                email: str | None = None) -> User:
    return _create(username, password, role, unit, email)


def authenticate(username: str, password: str) -> User | None:
    username = username.strip().casefold()
    if len(username) > 80: return None
    now = int(time.time())
    def authenticate_user(tx):
        reserved = tx.get('auth_names', key(username))
        row = tx.get('auth_users', key(reserved['user_id'])) if reserved else None
        attempt = tx.get('auth_login_attempts', key(username)) or {}
        if attempt.get('locked_until', 0) > now: return None
        salt = bytes(row['password_salt']) if row else _DUMMY_SALT
        expected = bytes(row['password_hash']) if row else _password_hash('not-a-real-password', salt)
        valid = hmac.compare_digest(_password_hash(password[:256], salt), expected)
        if not row or not row['active'] or not valid:
            failures = attempt.get('failures', 0) + 1
            tx.set('auth_login_attempts', key(username), dict(username=username, failures=failures,
                locked_until=now + LOGIN_LOCK_SECONDS if failures >= LOGIN_FAILURE_LIMIT else 0))
            return None
        tx.delete('auth_login_attempts', key(username))
        return _user(row)
    return _run(authenticate_user)


def create_session(user_id: int) -> tuple[str, str]:
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    def create(tx):
        user = tx.get('auth_users', key(user_id))
        if not user or not user['active']: raise ValueError('Conta ativa não encontrada.')
        tx.set('auth_sessions', token_hash, dict(token_hash=token_hash, user_id=user_id,
            csrf_token=csrf, expires_at=int(time.time()) + SESSION_TTL_SECONDS,
            session_version=user.get('session_version', 0)))
    _run(create)
    return token, csrf


def get_session(token: str | None) -> tuple[User, str] | None:
    if not token or len(token) > 128: return None
    def read(tx):
        session = tx.get('auth_sessions', hashlib.sha256(token.encode()).hexdigest())
        if not session or session['expires_at'] <= int(time.time()): return None
        user = tx.get('auth_users', key(session['user_id']))
        if (not user or not user['active'] or
                session.get('session_version', 0) != user.get('session_version', 0)): return None
        return _user(user), session['csrf_token']
    # A transaction makes session and account generation one consistent read.
    return get_store().read(read)


def validate_csrf(token: str | None, expected: str | None) -> bool:
    return bool(token and expected and hmac.compare_digest(token, expected))


def revoke_session(token: str | None) -> None:
    if token and len(token) <= 128:
        _run(lambda tx: tx.delete('auth_sessions', hashlib.sha256(token.encode()).hexdigest()))


def _set_password(tx, row, password_hash, salt, must_change=False):
    row.update(password_hash=password_hash, password_salt=salt, must_change_password=must_change,
               session_version=row.get('session_version', 0) + 1,
               reset_version=row.get('reset_version', 0) + 1)
    tx.set('auth_users', key(row['id']), row)


def change_password(user_id: int, password: str) -> None:
    _validate_password(password)
    salt = secrets.token_bytes(16)
    hashed = _password_hash(password, salt)
    def change(tx):
        row = tx.get('auth_users', key(user_id))
        if not row or not row['active']: raise ValueError('A conta ativa não foi encontrada.')
        _set_password(tx, row, hashed, salt)
    _run(change)


def admin_reset_user_password(user_id: int, password: str) -> None:
    _validate_password(password)
    salt = secrets.token_bytes(16)
    hashed = _password_hash(password, salt)
    def change(tx):
        row = tx.get('auth_users', key(user_id))
        if not row or not row['active']: raise ValueError('A conta ativa não foi encontrada.')
        _set_password(tx, row, hashed, salt, True)
        tx.delete('auth_login_attempts', key(row['username']))
    _run(change)


def set_user_recovery_email(user_id: int, email: str | None) -> None:
    email = _normalize_email(email)
    def update(tx):
        row = tx.get('auth_users', key(user_id))
        if not row: raise ValueError('Conta não encontrada.')
        reserved = tx.get('auth_emails', key(email)) if email else None
        if reserved and reserved['user_id'] != user_id:
            raise ValueError('Esse e-mail já está associado a outra conta.')
        if row.get('email'): tx.delete('auth_emails', key(row['email']))
        if email: tx.set('auth_emails', key(email), {'user_id': user_id})
        row.update(email=email, reset_version=row.get('reset_version', 0) + 1)
        tx.set('auth_users', key(user_id), row)
    _run(update)


def _attempt(tx, bucket_hash, now, limit, increment_blocked=True):
    row = tx.get('auth_password_reset_limits', bucket_hash) or {}
    fresh = row.get('window_started_at', 0) <= now - 3600
    attempts = 0 if fresh else row.get('attempts', 0)
    allowed = attempts < limit
    if allowed or increment_blocked:
        tx.set('auth_password_reset_limits', bucket_hash, dict(bucket_hash=bucket_hash,
            attempts=attempts + 1, window_started_at=now if fresh else row['window_started_at']))
    return allowed


def issue_password_reset_token(email: str, requester: str) -> tuple[str, str] | None:
    email = _normalize_email(email)
    if email is None: return None
    now, token = int(time.time()), secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    def issue(tx):
        a = _attempt(tx, hashlib.sha256(f'ip:{requester}'.encode()).hexdigest(), now, 5)
        b = _attempt(tx, hashlib.sha256(f'email:{email}'.encode()).hexdigest(), now, 3)
        if not (a and b): return None
        reserved = tx.get('auth_emails', key(email))
        row = tx.get('auth_users', key(reserved['user_id'])) if reserved else None
        if not row or not row['active']: return None
        row['reset_version'] = row.get('reset_version', 0) + 1
        tx.set('auth_users', key(row['id']), row)
        tx.set('auth_password_reset_tokens', token_hash, dict(token_hash=token_hash,
            user_id=row['id'], created_at=now, expires_at=now + 1800,
            used_at=None, reset_version=row['reset_version']))
        return token, row['email']
    return _run(issue)


def allow_password_reset_attempt(requester: str) -> bool:
    bucket = hashlib.sha256(f'reset-ip:{requester}'.encode()).hexdigest()
    return _run(lambda tx: _attempt(tx, bucket, int(time.time()), 10, False))


def invalidate_password_reset_token(token: str) -> None:
    if token and len(token) <= 128:
        _run(lambda tx: tx.delete('auth_password_reset_tokens', hashlib.sha256(token.encode()).hexdigest()))


def reset_password_with_token(token: str, password: str) -> bool:
    _validate_password(password)
    if not token or len(token) > 128: return False
    now = int(time.time())
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    salt = secrets.token_bytes(16)
    hashed = _password_hash(password, salt)
    def reset(tx):
        reset = tx.get('auth_password_reset_tokens', token_hash)
        if not reset or reset.get('used_at') is not None or reset['expires_at'] <= now: return False
        user = tx.get('auth_users', key(reset['user_id']))
        if (not user or not user['active'] or
                reset.get('reset_version', 0) != user.get('reset_version', 0)): return False
        _set_password(tx, user, hashed, salt)
        reset['used_at'] = now
        tx.set('auth_password_reset_tokens', token_hash, reset)
        return True
    return _run(reset)


@snapshot_read
def list_users() -> tuple[User, ...]:
    return tuple(_user(row) for row in sorted(get_store().query('auth_users'), key=lambda r: r['username']))


def _remove_user(user_id, actor_id, delete=False):
    if user_id == actor_id:
        raise ValueError('Não é possível excluir a própria conta.' if delete else
                         'Não é possível desativar a própria conta.')
    def remove(tx):
        row = tx.get('auth_users', key(user_id))
        if not row or (not delete and not row['active']):
            raise ValueError('A conta já está desativada ou não existe.')
        if row['role'] == 'admin' and row['active']:
            admins = tx.query('auth_users', [('role', '==', 'admin'), ('active', '==', True)])
            if len(admins) <= 1: raise ValueError('Mantenha pelo menos um administrador ativo.')
        if delete:
            tx.delete('auth_users', key(user_id))
            tx.delete('auth_names', key(row['username']))
            if row.get('email'): tx.delete('auth_emails', key(row['email']))
            tx.delete('auth_login_attempts', key(row['username']))
        else:
            row.update(active=False, session_version=row.get('session_version', 0) + 1,
                       reset_version=row.get('reset_version', 0) + 1)
            tx.set('auth_users', key(user_id), row)
    _run(remove)


def deactivate_user(user_id: int, actor_id: int) -> None:
    _remove_user(user_id, actor_id)


def delete_user(user_id: int, actor_id: int) -> None:
    _remove_user(user_id, actor_id, True)
