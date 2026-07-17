"""Local pilot identity, authorization, administration and audit services.

The module intentionally contains no MMM, forecast or optimizer logic.  It is
the replaceable application-security boundary: the HTTP layer talks to the
``IdentityProvider`` protocol, while the current pilot implementation stores
users, opaque server-side sessions and append-only audit events in SQLite.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import sqlite3
import threading
import unicodedata
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping, Protocol, Sequence


AUTH_CONTRACT_VERSION = "1.0.0"
PERMISSION_CATALOG_VERSION = "1.0.0"
USER_STATUSES = {"active", "disabled"}
ROLE_IDS = {"viewer", "analyst", "admin"}
AUDIT_EVENT_TYPES = {
    "login_succeeded",
    "login_failed",
    "logout",
    "session_revoked",
    "user_created",
    "user_updated",
    "user_enabled",
    "user_disabled",
    "role_changed",
    "admin_viewed_system_status",
    "admin_viewed_audit_log",
}

_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_USER_ID_RE = re.compile(r"^usr_[0-9a-f]{24}$")
_SESSION_ID_RE = re.compile(r"^ses_[0-9a-f]{24}$")
_REQUEST_ID_RE = re.compile(r"^req_[0-9a-f]{24}$")


PERMISSION_CATALOG: tuple[dict[str, str], ...] = (
    {
        "permission_id": "workspace.read",
        "title": "Просмотр главной",
        "description": "Просматривать рабочее пространство и сводку расчетов.",
    },
    {
        "permission_id": "calculation.read",
        "title": "Просмотр расчетов",
        "description": "Просматривать историю, состояние и ход расчетов.",
    },
    {
        "permission_id": "calculation.create",
        "title": "Создание расчетов",
        "description": "Загружать кампании, проверять их и запускать расчет.",
    },
    {
        "permission_id": "calculation.cancel",
        "title": "Отмена расчетов",
        "description": "Запрашивать отмену незавершенного расчета.",
    },
    {
        "permission_id": "result.read",
        "title": "Просмотр результатов",
        "description": "Просматривать опубликованные результаты и медиапланы.",
    },
    {
        "permission_id": "report.download",
        "title": "Скачивание отчетов",
        "description": "Скачивать опубликованные файлы результата.",
    },
    {
        "permission_id": "model.read",
        "title": "Просмотр модели",
        "description": "Просматривать паспорт и ограничения активной модели.",
    },
    {
        "permission_id": "help.read",
        "title": "Просмотр справки",
        "description": "Просматривать справку и опубликованные контракты.",
    },
    {
        "permission_id": "admin.users.read",
        "title": "Просмотр пользователей",
        "description": "Просматривать учетные записи и каталог ролей.",
    },
    {
        "permission_id": "admin.users.write",
        "title": "Изменение пользователей",
        "description": "Создавать и изменять локальные учетные записи.",
    },
    {
        "permission_id": "admin.roles.write",
        "title": "Управление ролями",
        "description": "Изменять назначения ролей в пределах каталога.",
    },
    {
        "permission_id": "admin.sessions.write",
        "title": "Отзыв сессий",
        "description": "Завершать активные пользовательские сессии.",
    },
    {
        "permission_id": "admin.system.read",
        "title": "Состояние системы",
        "description": "Просматривать безопасную техническую сводку.",
    },
    {
        "permission_id": "admin.audit.read",
        "title": "Журнал действий",
        "description": "Просматривать административный журнал действий.",
    },
)

_VIEWER_PERMISSIONS = (
    "workspace.read",
    "calculation.read",
    "result.read",
    "model.read",
    "help.read",
)
_ANALYST_PERMISSIONS = (
    *_VIEWER_PERMISSIONS,
    "calculation.create",
    "calculation.cancel",
    "report.download",
)
_ADMIN_PERMISSIONS = (
    *_ANALYST_PERMISSIONS,
    "admin.users.read",
    "admin.users.write",
    "admin.roles.write",
    "admin.sessions.write",
    "admin.system.read",
    "admin.audit.read",
)

ROLE_CATALOG: dict[str, dict[str, Any]] = {
    "viewer": {
        "role_id": "viewer",
        "title": "Наблюдатель",
        "description": "Может читать рабочие сведения и опубликованные результаты.",
        "permissions": list(_VIEWER_PERMISSIONS),
    },
    "analyst": {
        "role_id": "analyst",
        "title": "Аналитик",
        "description": "Может готовить, запускать и отменять расчеты, а также скачивать отчеты.",
        "permissions": list(_ANALYST_PERMISSIONS),
    },
    "admin": {
        "role_id": "admin",
        "title": "Администратор",
        "description": "Управляет пользователями, сессиями и просмотром состояния системы.",
        "permissions": list(_ADMIN_PERMISSIONS),
    },
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_iso(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("Timezone-aware datetime is required")
    return value.astimezone(timezone.utc).isoformat()


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("Timezone-aware timestamp is required")
    return parsed.astimezone(timezone.utc)


def opaque_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(12)}"


def normalize_email(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip().casefold()
    if not normalized or len(normalized) > 254 or not _EMAIL_RE.fullmatch(normalized):
        raise ValueError("Email заполнен некорректно.")
    return normalized


def validate_display_name(value: str) -> str:
    normalized = " ".join(unicodedata.normalize("NFKC", value).split())
    if not 2 <= len(normalized) <= 120:
        raise ValueError("Имя пользователя заполнено некорректно.")
    return normalized


def validate_password_policy(password: str) -> None:
    if not isinstance(password, str) or not 12 <= len(password) <= 256:
        raise ValueError("Пароль должен содержать от 12 до 256 символов.")
    if password.isspace() or not any(character.isalpha() for character in password):
        raise ValueError("Пароль должен содержать буквы и не состоять из пробелов.")
    if not any(character.isdigit() for character in password):
        raise ValueError("Пароль должен содержать хотя бы одну цифру.")


class AuthAdminError(RuntimeError):
    """Controlled service error that maps to one browser-safe API error."""

    def __init__(self, code: str, http_status: int, display_text: str) -> None:
        super().__init__(display_text)
        self.code = code
        self.http_status = http_status
        self.display_text = display_text


def auth_error(code: str) -> AuthAdminError:
    definitions = {
        "AUTH_REQUIRED": (401, "Войдите в систему, чтобы продолжить."),
        "AUTH_INVALID_CREDENTIALS": (
            401,
            "Не удалось войти. Проверьте данные и повторите попытку.",
        ),
        "AUTH_SESSION_EXPIRED": (401, "Сессия завершена. Войдите в систему повторно."),
        "AUTH_ACCOUNT_DISABLED": (
            401,
            "Учетная запись отключена. Обратитесь к администратору.",
        ),
        "AUTH_RATE_LIMITED": (
            429,
            "Слишком много попыток входа. Повторите попытку немного позже.",
        ),
        "PERMISSION_DENIED": (403, "Недостаточно прав для выполнения этого действия."),
        "ADMIN_USER_NOT_FOUND": (404, "Пользователь не найден."),
        "ADMIN_LAST_ADMIN_PROTECTED": (
            409,
            "Нельзя отключить или понизить роль последнего активного администратора.",
        ),
        "ADMIN_QUERY_INVALID": (422, "Параметры просмотра заполнены некорректно."),
        "ADMIN_STATE_INCONSISTENT": (
            409,
            "Не удалось применить изменение из-за текущего состояния учетных записей.",
        ),
        "ADMIN_SERVICE_UNAVAILABLE": (
            503,
            "Управление пользователями временно недоступно.",
        ),
    }
    status, text = definitions[code]
    return AuthAdminError(code, status, text)


class PasswordHasher(Protocol):
    algorithm_version: str

    def hash_password(self, password: str) -> str: ...

    def verify_password(self, password_hash: str, password: str) -> tuple[bool, bool]: ...


class Argon2idPasswordHasher:
    """Argon2id wrapper with versioned, configurable parameters."""

    algorithm_version = "argon2id-v1"

    def __init__(
        self,
        *,
        time_cost: int = 3,
        memory_cost_kib: int = 65536,
        parallelism: int = 4,
    ) -> None:
        if time_cost < 2 or memory_cost_kib < 19456 or parallelism < 1:
            raise ValueError("Argon2id parameters are below the pilot security floor")
        try:
            from argon2 import PasswordHasher as NativePasswordHasher
            from argon2.low_level import Type
        except ImportError as exc:  # pragma: no cover - exercised by runtime preflight
            raise RuntimeError(
                "argon2-cffi is required for local pilot authentication"
            ) from exc
        self._native = NativePasswordHasher(
            time_cost=time_cost,
            memory_cost=memory_cost_kib,
            parallelism=parallelism,
            hash_len=32,
            salt_len=16,
            type=Type.ID,
        )

    def hash_password(self, password: str) -> str:
        validate_password_policy(password)
        return self._native.hash(password)

    def verify_password(self, password_hash: str, password: str) -> tuple[bool, bool]:
        try:
            verified = bool(self._native.verify(password_hash, password))
        except Exception as exc:  # argon2 deliberately has several invalid-hash errors
            if exc.__class__.__module__.startswith("argon2"):
                return False, False
            raise
        return verified, bool(verified and self._native.check_needs_rehash(password_hash))


@dataclass(frozen=True)
class LocalAuthSettings:
    database_path: Path
    session_secret: str
    session_ttl_seconds: int = 28_800
    idle_timeout_seconds: int = 3_600
    login_window_seconds: int = 900
    login_max_attempts: int = 5
    login_cooldown_seconds: int = 900
    argon2_time_cost: int = 3
    argon2_memory_cost_kib: int = 65_536
    argon2_parallelism: int = 4

    def validate(self) -> None:
        if len(self.session_secret) < 32:
            raise ValueError("MMM_AUTH_SESSION_SECRET must contain at least 32 characters")
        if self.session_ttl_seconds < 900:
            raise ValueError("Session lifetime must be at least 15 minutes")
        if not 60 <= self.idle_timeout_seconds <= self.session_ttl_seconds:
            raise ValueError("Session idle timeout is outside the allowed range")
        if self.login_window_seconds <= 0 or self.login_cooldown_seconds <= 0:
            raise ValueError("Login rate-limit intervals must be positive")
        if not 2 <= self.login_max_attempts <= 20:
            raise ValueError("login_max_attempts is outside the allowed range")


class SQLiteAuthDatabase:
    """Connection and transaction boundary for the pilot auth database."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path.parent.chmod(0o700)
        self._initialization_lock = threading.RLock()
        self._initialize()
        self.path.chmod(0o600)

    def _new_connection(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._new_connection()
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
            except Exception:
                connection.rollback()
                raise
            else:
                connection.commit()

    def _initialize(self) -> None:
        with self._initialization_lock, self.connection() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS auth_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    email_normalized TEXT NOT NULL UNIQUE,
                    display_name TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    password_algorithm TEXT NOT NULL,
                    role_id TEXT NOT NULL CHECK (role_id IN ('viewer', 'analyst', 'admin')),
                    status TEXT NOT NULL CHECK (status IN ('active', 'disabled')),
                    created_at_utc TEXT NOT NULL,
                    updated_at_utc TEXT NOT NULL,
                    last_login_at_utc TEXT,
                    created_by_user_id TEXT
                );

                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(user_id),
                    token_digest TEXT NOT NULL UNIQUE,
                    created_at_utc TEXT NOT NULL,
                    expires_at_utc TEXT NOT NULL,
                    last_seen_at_utc TEXT NOT NULL,
                    idle_timeout_seconds INTEGER NOT NULL,
                    revoked_at_utc TEXT,
                    revoke_reason TEXT
                );
                CREATE INDEX IF NOT EXISTS sessions_user_idx ON sessions(user_id);
                CREATE INDEX IF NOT EXISTS sessions_token_idx ON sessions(token_digest);

                CREATE TABLE IF NOT EXISTS login_attempts (
                    attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    subject_digest TEXT NOT NULL,
                    occurred_at_utc TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS login_attempts_subject_idx
                    ON login_attempts(subject_digest, occurred_at_utc);

                CREATE TABLE IF NOT EXISTS audit_events (
                    event_id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    occurred_at_utc TEXT NOT NULL,
                    actor_user_id TEXT,
                    actor_display_name TEXT,
                    target_type TEXT NOT NULL,
                    target_id TEXT,
                    result TEXT NOT NULL,
                    browser_safe_summary TEXT NOT NULL,
                    request_id TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS audit_occurred_idx
                    ON audit_events(occurred_at_utc, event_id);
                CREATE INDEX IF NOT EXISTS audit_actor_idx
                    ON audit_events(actor_user_id, occurred_at_utc);
                CREATE INDEX IF NOT EXISTS audit_type_idx
                    ON audit_events(event_type, occurred_at_utc);

                CREATE TRIGGER IF NOT EXISTS audit_events_no_update
                BEFORE UPDATE ON audit_events
                BEGIN
                    SELECT RAISE(ABORT, 'audit events are append-only');
                END;

                CREATE TRIGGER IF NOT EXISTS audit_events_no_delete
                BEFORE DELETE ON audit_events
                BEGIN
                    SELECT RAISE(ABORT, 'audit events are append-only');
                END;
                """
            )
            connection.execute(
                "INSERT OR IGNORE INTO auth_meta(key, value) VALUES('schema_version', '1.0.0')"
            )
            integrity = connection.execute("PRAGMA quick_check").fetchone()[0]
            if integrity != "ok":
                raise RuntimeError("Auth storage integrity check failed")

    def health(self) -> tuple[bool, str]:
        try:
            with self.connection() as connection:
                result = connection.execute("PRAGMA quick_check").fetchone()[0]
            return result == "ok", "ok" if result == "ok" else "integrity_failed"
        except sqlite3.Error:
            return False, "unavailable"


class UserRepository(Protocol):
    def get(self, user_id: str) -> dict[str, Any] | None: ...

    def find_by_email(self, email_normalized: str) -> dict[str, Any] | None: ...


class SessionRepository(Protocol):
    def resolve(self, token_digest: str) -> dict[str, Any] | None: ...


class AuditRepository(Protocol):
    def append(self, event: Mapping[str, Any]) -> None: ...


class SQLiteUserRepository:
    def __init__(self, database: SQLiteAuthDatabase) -> None:
        self.database = database

    @staticmethod
    def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        return dict(row) if row is not None else None

    def get(
        self,
        user_id: str,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> dict[str, Any] | None:
        if connection is not None:
            return self._row(connection.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone())
        with self.database.connection() as owned:
            return self.get(user_id, connection=owned)

    def find_by_email(
        self,
        email_normalized: str,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> dict[str, Any] | None:
        if connection is not None:
            return self._row(
                connection.execute(
                    "SELECT * FROM users WHERE email_normalized = ?",
                    (email_normalized,),
                ).fetchone()
            )
        with self.database.connection() as owned:
            return self.find_by_email(email_normalized, connection=owned)

    def create(
        self,
        *,
        email_normalized: str,
        display_name: str,
        password_hash: str,
        password_algorithm: str,
        role_id: str,
        created_by_user_id: str | None,
        now: datetime,
        connection: sqlite3.Connection,
    ) -> dict[str, Any]:
        user_id = opaque_id("usr")
        timestamp = utc_iso(now)
        try:
            connection.execute(
                """
                INSERT INTO users(
                    user_id, email_normalized, display_name, password_hash,
                    password_algorithm, role_id, status, created_at_utc,
                    updated_at_utc, last_login_at_utc, created_by_user_id
                ) VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?, NULL, ?)
                """,
                (
                    user_id,
                    email_normalized,
                    display_name,
                    password_hash,
                    password_algorithm,
                    role_id,
                    timestamp,
                    timestamp,
                    created_by_user_id,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise auth_error("ADMIN_STATE_INCONSISTENT") from exc
        record = self.get(user_id, connection=connection)
        if record is None:
            raise auth_error("ADMIN_STATE_INCONSISTENT")
        return record

    def update_fields(
        self,
        user_id: str,
        changes: Mapping[str, Any],
        *,
        now: datetime,
        connection: sqlite3.Connection,
    ) -> dict[str, Any]:
        allowed = {
            "display_name",
            "password_hash",
            "password_algorithm",
            "role_id",
            "status",
            "last_login_at_utc",
        }
        if not changes or set(changes) - allowed:
            raise ValueError("Unsupported user fields")
        assignments = [f"{field} = ?" for field in changes]
        values = list(changes.values())
        assignments.append("updated_at_utc = ?")
        values.append(utc_iso(now))
        values.append(user_id)
        cursor = connection.execute(
            f"UPDATE users SET {', '.join(assignments)} WHERE user_id = ?",
            values,
        )
        if cursor.rowcount != 1:
            raise auth_error("ADMIN_USER_NOT_FOUND")
        record = self.get(user_id, connection=connection)
        if record is None:
            raise auth_error("ADMIN_USER_NOT_FOUND")
        return record

    def all(self) -> list[dict[str, Any]]:
        with self.database.connection() as connection:
            rows = connection.execute("SELECT * FROM users").fetchall()
        return [dict(row) for row in rows]

    def active_admins(
        self,
        *,
        connection: sqlite3.Connection,
    ) -> list[dict[str, Any]]:
        return [
            dict(row)
            for row in connection.execute(
                "SELECT * FROM users WHERE role_id = 'admin' AND status = 'active'"
            ).fetchall()
        ]


class SQLiteSessionRepository:
    def __init__(self, database: SQLiteAuthDatabase) -> None:
        self.database = database

    def create(
        self,
        *,
        user_id: str,
        token_digest: str,
        created_at: datetime,
        expires_at: datetime,
        idle_timeout_seconds: int,
        connection: sqlite3.Connection,
    ) -> dict[str, Any]:
        session_id = opaque_id("ses")
        timestamp = utc_iso(created_at)
        connection.execute(
            """
            INSERT INTO sessions(
                session_id, user_id, token_digest, created_at_utc,
                expires_at_utc, last_seen_at_utc, idle_timeout_seconds,
                revoked_at_utc, revoke_reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL)
            """,
            (
                session_id,
                user_id,
                token_digest,
                timestamp,
                utc_iso(expires_at),
                timestamp,
                idle_timeout_seconds,
            ),
        )
        row = connection.execute(
            "SELECT * FROM sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if row is None:
            raise auth_error("ADMIN_STATE_INCONSISTENT")
        return dict(row)

    def resolve(
        self,
        token_digest: str,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> dict[str, Any] | None:
        query = """
            SELECT
                sessions.*,
                users.email_normalized,
                users.display_name,
                users.role_id,
                users.status AS user_status
            FROM sessions
            JOIN users ON users.user_id = sessions.user_id
            WHERE sessions.token_digest = ?
        """
        if connection is not None:
            row = connection.execute(query, (token_digest,)).fetchone()
            return dict(row) if row is not None else None
        with self.database.connection() as owned:
            return self.resolve(token_digest, connection=owned)

    def touch(
        self,
        session_id: str,
        *,
        now: datetime,
        connection: sqlite3.Connection,
    ) -> None:
        connection.execute(
            "UPDATE sessions SET last_seen_at_utc = ? WHERE session_id = ? AND revoked_at_utc IS NULL",
            (utc_iso(now), session_id),
        )

    def revoke(
        self,
        session_id: str,
        *,
        reason: str,
        now: datetime,
        connection: sqlite3.Connection,
    ) -> int:
        cursor = connection.execute(
            """
            UPDATE sessions
            SET revoked_at_utc = ?, revoke_reason = ?
            WHERE session_id = ? AND revoked_at_utc IS NULL
            """,
            (utc_iso(now), reason, session_id),
        )
        return int(cursor.rowcount)

    def revoke_for_user(
        self,
        user_id: str,
        *,
        reason: str,
        now: datetime,
        connection: sqlite3.Connection,
    ) -> int:
        cursor = connection.execute(
            """
            UPDATE sessions
            SET revoked_at_utc = ?, revoke_reason = ?
            WHERE user_id = ? AND revoked_at_utc IS NULL
            """,
            (utc_iso(now), reason, user_id),
        )
        return int(cursor.rowcount)

    def active_count(self, user_id: str, *, now: datetime) -> int:
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM sessions WHERE user_id = ? AND revoked_at_utc IS NULL",
                (user_id,),
            ).fetchall()
        return sum(self._is_active(dict(row), now) for row in rows)

    @staticmethod
    def _is_active(record: Mapping[str, Any], now: datetime) -> bool:
        if record.get("revoked_at_utc") is not None:
            return False
        if parse_utc(str(record["expires_at_utc"])) <= now:
            return False
        idle_deadline = parse_utc(str(record["last_seen_at_utc"])) + timedelta(
            seconds=int(record["idle_timeout_seconds"])
        )
        return idle_deadline > now


class SQLiteLoginAttemptRepository:
    def __init__(self, database: SQLiteAuthDatabase) -> None:
        self.database = database

    def recent_count_and_latest(
        self,
        subject_digest: str,
        *,
        since: datetime,
    ) -> tuple[int, datetime | None]:
        with self.database.connection() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS attempts, MAX(occurred_at_utc) AS latest
                FROM login_attempts
                WHERE subject_digest = ? AND occurred_at_utc >= ?
                """,
                (subject_digest, utc_iso(since)),
            ).fetchone()
        latest = parse_utc(row["latest"]) if row["latest"] else None
        return int(row["attempts"]), latest

    def record(
        self,
        subject_digest: str,
        *,
        now: datetime,
        connection: sqlite3.Connection,
    ) -> None:
        connection.execute(
            "INSERT INTO login_attempts(subject_digest, occurred_at_utc) VALUES(?, ?)",
            (subject_digest, utc_iso(now)),
        )

    def clear(
        self,
        subject_digest: str,
        *,
        connection: sqlite3.Connection,
    ) -> None:
        connection.execute(
            "DELETE FROM login_attempts WHERE subject_digest = ?",
            (subject_digest,),
        )


class SQLiteAuditRepository:
    def __init__(self, database: SQLiteAuthDatabase) -> None:
        self.database = database

    def append(
        self,
        event: Mapping[str, Any],
        *,
        connection: sqlite3.Connection | None = None,
    ) -> None:
        if str(event.get("event_type")) not in AUDIT_EVENT_TYPES:
            raise ValueError("Unknown audit event type")
        values = (
            event["event_id"],
            event["event_type"],
            event["occurred_at_utc"],
            event.get("actor_user_id"),
            event.get("actor_display_name"),
            event["target_type"],
            event.get("target_id"),
            event["result"],
            event["browser_safe_summary"],
            event["request_id"],
        )
        statement = """
            INSERT INTO audit_events(
                event_id, event_type, occurred_at_utc, actor_user_id,
                actor_display_name, target_type, target_id, result,
                browser_safe_summary, request_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        if connection is not None:
            connection.execute(statement, values)
            return
        with self.database.transaction() as owned:
            self.append(event, connection=owned)

    def query(
        self,
        *,
        page: int,
        page_size: int,
        actor_user_id: str | None,
        event_type: str | None,
        occurred_from: datetime | None,
        occurred_to: datetime | None,
        sort: str,
    ) -> tuple[list[dict[str, Any]], int]:
        clauses: list[str] = []
        parameters: list[Any] = []
        if actor_user_id is not None:
            clauses.append("actor_user_id = ?")
            parameters.append(actor_user_id)
        if event_type is not None:
            clauses.append("event_type = ?")
            parameters.append(event_type)
        if occurred_from is not None:
            clauses.append("occurred_at_utc >= ?")
            parameters.append(utc_iso(occurred_from))
        if occurred_to is not None:
            clauses.append("occurred_at_utc <= ?")
            parameters.append(utc_iso(occurred_to))
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        direction = "ASC" if sort == "occurred_asc" else "DESC"
        offset = (page - 1) * page_size
        with self.database.connection() as connection:
            total = int(
                connection.execute(
                    f"SELECT COUNT(*) FROM audit_events{where}",
                    parameters,
                ).fetchone()[0]
            )
            rows = connection.execute(
                f"""
                SELECT * FROM audit_events{where}
                ORDER BY occurred_at_utc {direction}, event_id {direction}
                LIMIT ? OFFSET ?
                """,
                [*parameters, page_size, offset],
            ).fetchall()
        return [dict(row) for row in rows], total


@dataclass(frozen=True)
class RequestContext:
    request_id: str
    user_id: str
    display_name: str
    email: str
    role_id: str
    permissions: tuple[str, ...]
    user_status: str
    session_id: str
    session_created_at_utc: str
    session_expires_at_utc: str
    session_last_seen_at_utc: str
    idle_timeout_seconds: int


@dataclass(frozen=True)
class SessionResolution:
    state: str
    context: RequestContext | None


class IdentityProvider(Protocol):
    """Replaceable identity boundary; a future SSO adapter must implement this."""

    def authenticate(
        self,
        email: str,
        password: str,
        *,
        request_id: str,
        client_key: str,
    ) -> tuple[RequestContext, str]: ...

    def resolve_session(self, token: str | None, *, request_id: str) -> SessionResolution: ...

    def logout(self, token: str | None, *, request_id: str) -> None: ...


class FutureCorporateSSOProvider(IdentityProvider, Protocol):
    """Marker contract for a future approved SSO adapter; no implementation exists."""


class LocalPilotIdentityProvider:
    """SQLite-backed identity provider used only by the local research pilot."""

    def __init__(
        self,
        settings: LocalAuthSettings,
        database: SQLiteAuthDatabase,
        users: SQLiteUserRepository,
        sessions: SQLiteSessionRepository,
        attempts: SQLiteLoginAttemptRepository,
        audit: SQLiteAuditRepository,
        hasher: PasswordHasher,
    ) -> None:
        settings.validate()
        self.settings = settings
        self.database = database
        self.users = users
        self.sessions = sessions
        self.attempts = attempts
        self.audit = audit
        self.hasher = hasher
        self._secret = settings.session_secret.encode("utf-8")
        self._dummy_hash = hasher.hash_password("Unknown-account-2026")

    def _digest(self, namespace: str, value: str) -> str:
        return hmac.new(
            self._secret,
            f"{namespace}|{value}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def token_digest(self, token: str) -> str:
        return self._digest("session", token)

    def _login_subject(self, email: str, client_key: str) -> str:
        try:
            normalized = normalize_email(email)
        except ValueError:
            normalized = "invalid"
        return self._digest("login", f"{normalized}|{client_key}")

    def _audit_event(
        self,
        *,
        event_type: str,
        now: datetime,
        request_id: str,
        actor: Mapping[str, Any] | None,
        target_type: str,
        target_id: str | None,
        result: str,
        summary: str,
    ) -> dict[str, Any]:
        return {
            "event_id": opaque_id("evt"),
            "event_type": event_type,
            "occurred_at_utc": utc_iso(now),
            "actor_user_id": actor.get("user_id") if actor else None,
            "actor_display_name": actor.get("display_name") if actor else None,
            "target_type": target_type,
            "target_id": target_id,
            "result": result,
            "browser_safe_summary": summary,
            "request_id": request_id,
        }

    def authenticate(
        self,
        email: str,
        password: str,
        *,
        request_id: str,
        client_key: str,
    ) -> tuple[RequestContext, str]:
        now = utc_now()
        subject = self._login_subject(email, client_key)
        attempts, latest = self.attempts.recent_count_and_latest(
            subject,
            since=now - timedelta(seconds=self.settings.login_window_seconds),
        )
        if (
            attempts >= self.settings.login_max_attempts
            and latest is not None
            and latest + timedelta(seconds=self.settings.login_cooldown_seconds) > now
        ):
            self.audit.append(
                self._audit_event(
                    event_type="login_failed",
                    now=now,
                    request_id=request_id,
                    actor=None,
                    target_type="authentication",
                    target_id=f"identity_{subject[:16]}",
                    result="rate_limited",
                    summary="Попытка входа временно ограничена.",
                )
            )
            raise auth_error("AUTH_RATE_LIMITED")

        try:
            normalized_email = normalize_email(email)
        except ValueError:
            normalized_email = ""
        user = self.users.find_by_email(normalized_email) if normalized_email else None
        password_hash = str(user["password_hash"]) if user else self._dummy_hash
        verified, needs_rehash = self.hasher.verify_password(password_hash, password)
        if user is None or not verified:
            with self.database.transaction() as connection:
                self.attempts.record(subject, now=now, connection=connection)
                self.audit.append(
                    self._audit_event(
                        event_type="login_failed",
                        now=now,
                        request_id=request_id,
                        actor=None,
                        target_type="authentication",
                        target_id=f"identity_{subject[:16]}",
                        result="denied",
                        summary="Неуспешная попытка входа.",
                    ),
                    connection=connection,
                )
            raise auth_error("AUTH_INVALID_CREDENTIALS")

        if user["status"] != "active":
            with self.database.transaction() as connection:
                self.attempts.record(subject, now=now, connection=connection)
                self.audit.append(
                    self._audit_event(
                        event_type="login_failed",
                        now=now,
                        request_id=request_id,
                        actor=None,
                        target_type="authentication",
                        target_id=f"identity_{subject[:16]}",
                        result="account_disabled",
                        summary="Вход отклонен для отключенной учетной записи.",
                    ),
                    connection=connection,
                )
            raise auth_error("AUTH_ACCOUNT_DISABLED")

        token = secrets.token_urlsafe(32)
        token_digest = self.token_digest(token)
        expires_at = now + timedelta(seconds=self.settings.session_ttl_seconds)
        with self.database.transaction() as connection:
            if needs_rehash:
                user = self.users.update_fields(
                    str(user["user_id"]),
                    {
                        "password_hash": self.hasher.hash_password(password),
                        "password_algorithm": self.hasher.algorithm_version,
                    },
                    now=now,
                    connection=connection,
                )
            user = self.users.update_fields(
                str(user["user_id"]),
                {"last_login_at_utc": utc_iso(now)},
                now=now,
                connection=connection,
            )
            session = self.sessions.create(
                user_id=str(user["user_id"]),
                token_digest=token_digest,
                created_at=now,
                expires_at=expires_at,
                idle_timeout_seconds=self.settings.idle_timeout_seconds,
                connection=connection,
            )
            self.attempts.clear(subject, connection=connection)
            self.audit.append(
                self._audit_event(
                    event_type="login_succeeded",
                    now=now,
                    request_id=request_id,
                    actor=user,
                    target_type="session",
                    target_id=str(session["session_id"]),
                    result="succeeded",
                    summary="Вход выполнен успешно.",
                ),
                connection=connection,
            )
        return self._context(user, session, request_id=request_id), token

    def resolve_session(self, token: str | None, *, request_id: str) -> SessionResolution:
        if not token:
            return SessionResolution("anonymous", None)
        record = self.sessions.resolve(self.token_digest(token))
        if record is None or record.get("revoked_at_utc") is not None:
            return SessionResolution("expired", None)
        now = utc_now()
        if parse_utc(str(record["expires_at_utc"])) <= now:
            with self.database.transaction() as connection:
                self.sessions.revoke(
                    str(record["session_id"]),
                    reason="absolute_expiry",
                    now=now,
                    connection=connection,
                )
            return SessionResolution("expired", None)
        idle_deadline = parse_utc(str(record["last_seen_at_utc"])) + timedelta(
            seconds=int(record["idle_timeout_seconds"])
        )
        if idle_deadline <= now:
            with self.database.transaction() as connection:
                self.sessions.revoke(
                    str(record["session_id"]),
                    reason="idle_expiry",
                    now=now,
                    connection=connection,
                )
            return SessionResolution("expired", None)
        if record["user_status"] != "active":
            with self.database.transaction() as connection:
                self.sessions.revoke_for_user(
                    str(record["user_id"]),
                    reason="account_disabled",
                    now=now,
                    connection=connection,
                )
            return SessionResolution("disabled", None)

        last_seen = parse_utc(str(record["last_seen_at_utc"]))
        if (now - last_seen).total_seconds() >= 60:
            with self.database.transaction() as connection:
                self.sessions.touch(
                    str(record["session_id"]),
                    now=now,
                    connection=connection,
                )
            record["last_seen_at_utc"] = utc_iso(now)
        return SessionResolution(
            "authenticated",
            self._context(record, record, request_id=request_id),
        )

    def logout(self, token: str | None, *, request_id: str) -> None:
        if not token:
            return
        record = self.sessions.resolve(self.token_digest(token))
        if record is None:
            return
        now = utc_now()
        with self.database.transaction() as connection:
            changed = self.sessions.revoke(
                str(record["session_id"]),
                reason="logout",
                now=now,
                connection=connection,
            )
            if changed:
                self.audit.append(
                    self._audit_event(
                        event_type="logout",
                        now=now,
                        request_id=request_id,
                        actor=record,
                        target_type="session",
                        target_id=str(record["session_id"]),
                        result="succeeded",
                        summary="Сессия завершена пользователем.",
                    ),
                    connection=connection,
                )

    def bootstrap_admin(
        self,
        *,
        email: str,
        password: str,
        display_name: str,
        update_existing: bool,
    ) -> dict[str, Any]:
        normalized_email = normalize_email(email)
        display_name = validate_display_name(display_name)
        password_hash = self.hasher.hash_password(password)
        now = utc_now()
        request_id = opaque_id("req")
        with self.database.transaction() as connection:
            existing = self.users.find_by_email(normalized_email, connection=connection)
            active_admins = self.users.active_admins(connection=connection)
            if existing is not None and not update_existing:
                return {
                    "status": "already_exists",
                    "user_id": existing["user_id"],
                    "updated": False,
                }
            if existing is None and active_admins:
                return {
                    "status": "already_initialized",
                    "user_id": active_admins[0]["user_id"],
                    "updated": False,
                }
            if existing is None:
                user = self.users.create(
                    email_normalized=normalized_email,
                    display_name=display_name,
                    password_hash=password_hash,
                    password_algorithm=self.hasher.algorithm_version,
                    role_id="admin",
                    created_by_user_id=None,
                    now=now,
                    connection=connection,
                )
                event_type = "user_created"
                summary = "Создан первый локальный администратор."
                status = "created"
            else:
                user = self.users.update_fields(
                    str(existing["user_id"]),
                    {
                        "display_name": display_name,
                        "password_hash": password_hash,
                        "password_algorithm": self.hasher.algorithm_version,
                        "role_id": "admin",
                        "status": "active",
                    },
                    now=now,
                    connection=connection,
                )
                self.sessions.revoke_for_user(
                    str(user["user_id"]),
                    reason="bootstrap_update",
                    now=now,
                    connection=connection,
                )
                event_type = "user_updated"
                summary = "Локальный администратор обновлен через bootstrap-команду."
                status = "updated"
            self.audit.append(
                self._audit_event(
                    event_type=event_type,
                    now=now,
                    request_id=request_id,
                    actor=None,
                    target_type="user",
                    target_id=str(user["user_id"]),
                    result="succeeded",
                    summary=summary,
                ),
                connection=connection,
            )
        return {"status": status, "user_id": user["user_id"], "updated": status == "updated"}

    @staticmethod
    def _context(
        user: Mapping[str, Any],
        session: Mapping[str, Any],
        *,
        request_id: str,
    ) -> RequestContext:
        role_id = str(user["role_id"])
        role = ROLE_CATALOG[role_id]
        return RequestContext(
            request_id=request_id,
            user_id=str(user["user_id"]),
            display_name=str(user["display_name"]),
            email=str(user["email_normalized"]),
            role_id=role_id,
            permissions=tuple(str(value) for value in role["permissions"]),
            user_status=str(user.get("user_status") or user.get("status") or "active"),
            session_id=str(session["session_id"]),
            session_created_at_utc=str(session["created_at_utc"]),
            session_expires_at_utc=str(session["expires_at_utc"]),
            session_last_seen_at_utc=str(session["last_seen_at_utc"]),
            idle_timeout_seconds=int(session["idle_timeout_seconds"]),
        )


class AuthorizationGuard:
    """Role-agnostic permission checks used by the centralized route policy."""

    @staticmethod
    def require_authenticated(resolution: SessionResolution) -> RequestContext:
        if resolution.context is not None:
            return resolution.context
        if resolution.state == "expired":
            raise auth_error("AUTH_SESSION_EXPIRED")
        if resolution.state == "disabled":
            raise auth_error("AUTH_ACCOUNT_DISABLED")
        raise auth_error("AUTH_REQUIRED")

    def require_permission(
        self,
        resolution: SessionResolution,
        permission: str,
    ) -> RequestContext:
        context = self.require_authenticated(resolution)
        if permission not in context.permissions:
            raise auth_error("PERMISSION_DENIED")
        return context


def anonymous_session_payload() -> dict[str, Any]:
    return {
        "contract_name": "auth_session_v1",
        "schema_version": AUTH_CONTRACT_VERSION,
        "authenticated": False,
        "user": None,
        "session": None,
    }


def authenticated_session_payload(context: RequestContext) -> dict[str, Any]:
    role = ROLE_CATALOG[context.role_id]
    return {
        "contract_name": "auth_session_v1",
        "schema_version": AUTH_CONTRACT_VERSION,
        "authenticated": True,
        "user": {
            "user_id": context.user_id,
            "display_name": context.display_name,
            "email": context.email,
            "role": {"role_id": context.role_id, "title": role["title"]},
            "permissions": list(context.permissions),
            "status": context.user_status,
        },
        "session": {
            "session_id": context.session_id,
            "created_at_utc": context.session_created_at_utc,
            "expires_at_utc": context.session_expires_at_utc,
            "last_seen_at_utc": context.session_last_seen_at_utc,
            "idle_timeout_seconds": context.idle_timeout_seconds,
        },
    }


class AdminService:
    """Administrative use cases with atomic safety invariants and audit."""

    def __init__(
        self,
        database: SQLiteAuthDatabase,
        users: SQLiteUserRepository,
        sessions: SQLiteSessionRepository,
        audit: SQLiteAuditRepository,
        hasher: PasswordHasher,
    ) -> None:
        self.database = database
        self.users = users
        self.sessions = sessions
        self.audit = audit
        self.hasher = hasher

    @staticmethod
    def _role(role_id: str) -> dict[str, str]:
        role = ROLE_CATALOG[role_id]
        return {"role_id": role_id, "title": str(role["title"])}

    def _user_item(self, user: Mapping[str, Any], *, now: datetime) -> dict[str, Any]:
        return {
            "user_id": str(user["user_id"]),
            "display_name": str(user["display_name"]),
            "email": str(user["email_normalized"]),
            "role": self._role(str(user["role_id"])),
            "status": str(user["status"]),
            "created_at_utc": str(user["created_at_utc"]),
            "updated_at_utc": str(user["updated_at_utc"]),
            "last_login_at_utc": user.get("last_login_at_utc"),
            "created_by_user_id": user.get("created_by_user_id"),
            "active_sessions_n": self.sessions.active_count(str(user["user_id"]), now=now),
        }

    def user_detail(self, user_id: str) -> dict[str, Any]:
        if not _USER_ID_RE.fullmatch(user_id):
            raise auth_error("ADMIN_USER_NOT_FOUND")
        user = self.users.get(user_id)
        if user is None:
            raise auth_error("ADMIN_USER_NOT_FOUND")
        return {
            "contract_name": "admin_user_detail_v1",
            "schema_version": AUTH_CONTRACT_VERSION,
            "user": self._user_item(user, now=utc_now()),
        }

    def list_users(
        self,
        *,
        page: int,
        page_size: int,
        search: str | None,
        role_id: str | None,
        status: str | None,
        sort: str,
    ) -> dict[str, Any]:
        now = utc_now()
        records = self.users.all()
        if search is not None:
            needle = search.casefold()
            records = [
                row
                for row in records
                if needle in str(row["display_name"]).casefold()
                or needle in str(row["email_normalized"]).casefold()
            ]
        if role_id is not None:
            records = [row for row in records if row["role_id"] == role_id]
        if status is not None:
            records = [row for row in records if row["status"] == status]
        sorters = {
            "created_desc": (lambda row: (row["created_at_utc"], row["user_id"]), True),
            "created_asc": (lambda row: (row["created_at_utc"], row["user_id"]), False),
            "name_asc": (lambda row: (str(row["display_name"]).casefold(), row["user_id"]), False),
            "email_asc": (lambda row: (row["email_normalized"], row["user_id"]), False),
            "last_login_desc": (
                lambda row: (row.get("last_login_at_utc") or "", row["user_id"]),
                True,
            ),
        }
        key, reverse = sorters[sort]
        records.sort(key=key, reverse=reverse)
        total = len(records)
        start = (page - 1) * page_size
        items = [self._user_item(row, now=now) for row in records[start : start + page_size]]
        return {
            "contract_name": "admin_user_list_v1",
            "schema_version": AUTH_CONTRACT_VERSION,
            "items": items,
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total_items": total,
                "total_pages": (total + page_size - 1) // page_size,
            },
            "applied_filters": {
                "search": search,
                "role": role_id,
                "status": status,
                "sort": sort,
            },
        }

    def create_user(
        self,
        payload: Mapping[str, Any],
        *,
        actor: RequestContext,
    ) -> dict[str, Any]:
        expected = {"email", "display_name", "password", "role_id"}
        if set(payload) != expected:
            raise auth_error("ADMIN_STATE_INCONSISTENT")
        try:
            if not all(isinstance(payload[key], str) for key in expected):
                raise ValueError("Поля пользователя заполнены некорректно.")
            email = normalize_email(payload["email"])
            display_name = validate_display_name(payload["display_name"])
            password = payload["password"]
            validate_password_policy(password)
            role_id = payload["role_id"]
            if role_id not in ROLE_IDS:
                raise ValueError("Unknown role")
        except ValueError as exc:
            raise AuthAdminError("ADMIN_STATE_INCONSISTENT", 409, str(exc)) from exc
        password_hash = self.hasher.hash_password(password)
        now = utc_now()
        with self.database.transaction() as connection:
            if self.users.find_by_email(email, connection=connection) is not None:
                raise AuthAdminError(
                    "ADMIN_STATE_INCONSISTENT",
                    409,
                    "Пользователь с таким адресом уже существует.",
                )
            user = self.users.create(
                email_normalized=email,
                display_name=display_name,
                password_hash=password_hash,
                password_algorithm=self.hasher.algorithm_version,
                role_id=role_id,
                created_by_user_id=actor.user_id,
                now=now,
                connection=connection,
            )
            self.audit.append(
                self._event(
                    "user_created",
                    actor,
                    user,
                    "succeeded",
                    "Создана локальная учетная запись.",
                    now,
                ),
                connection=connection,
            )
        return self.user_detail(str(user["user_id"]))

    def update_user(
        self,
        user_id: str,
        payload: Mapping[str, Any],
        *,
        actor: RequestContext,
    ) -> dict[str, Any]:
        if not payload or set(payload) - {"display_name", "role_id"}:
            raise auth_error("ADMIN_STATE_INCONSISTENT")
        changes: dict[str, Any] = {}
        try:
            if "display_name" in payload:
                if not isinstance(payload["display_name"], str):
                    raise ValueError("Имя пользователя заполнено некорректно.")
                changes["display_name"] = validate_display_name(payload["display_name"])
            if "role_id" in payload:
                if not isinstance(payload["role_id"], str):
                    raise ValueError("Роль пользователя заполнена некорректно.")
                role_id = payload["role_id"]
                if role_id not in ROLE_IDS:
                    raise ValueError("Роль пользователя заполнена некорректно.")
                changes["role_id"] = role_id
        except ValueError as exc:
            raise AuthAdminError("ADMIN_STATE_INCONSISTENT", 409, str(exc)) from exc
        now = utc_now()
        with self.database.transaction() as connection:
            current = self.users.get(user_id, connection=connection)
            if current is None:
                raise auth_error("ADMIN_USER_NOT_FOUND")
            if (
                current["role_id"] == "admin"
                and current["status"] == "active"
                and changes.get("role_id", "admin") != "admin"
                and len(self.users.active_admins(connection=connection)) <= 1
            ):
                raise auth_error("ADMIN_LAST_ADMIN_PROTECTED")
            updated = self.users.update_fields(
                user_id,
                changes,
                now=now,
                connection=connection,
            )
            event_type = "role_changed" if "role_id" in changes else "user_updated"
            summary = (
                "Роль пользователя изменена."
                if event_type == "role_changed"
                else "Имя пользователя изменено."
            )
            self.audit.append(
                self._event(event_type, actor, updated, "succeeded", summary, now),
                connection=connection,
            )
        return self.user_detail(user_id)

    def set_user_enabled(
        self,
        user_id: str,
        *,
        enabled: bool,
        actor: RequestContext,
    ) -> dict[str, Any]:
        now = utc_now()
        with self.database.transaction() as connection:
            current = self.users.get(user_id, connection=connection)
            if current is None:
                raise auth_error("ADMIN_USER_NOT_FOUND")
            if (
                not enabled
                and current["role_id"] == "admin"
                and current["status"] == "active"
                and len(self.users.active_admins(connection=connection)) <= 1
            ):
                raise auth_error("ADMIN_LAST_ADMIN_PROTECTED")
            if not enabled and actor.user_id == user_id:
                raise AuthAdminError(
                    "ADMIN_STATE_INCONSISTENT",
                    409,
                    "Нельзя отключить собственную учетную запись.",
                )
            new_status = "active" if enabled else "disabled"
            updated = self.users.update_fields(
                user_id,
                {"status": new_status},
                now=now,
                connection=connection,
            )
            if not enabled:
                self.sessions.revoke_for_user(
                    user_id,
                    reason="account_disabled",
                    now=now,
                    connection=connection,
                )
            event_type = "user_enabled" if enabled else "user_disabled"
            summary = "Учетная запись включена." if enabled else "Учетная запись отключена, ее сессии завершены."
            self.audit.append(
                self._event(event_type, actor, updated, "succeeded", summary, now),
                connection=connection,
            )
        return self.user_detail(user_id)

    def revoke_user_sessions(
        self,
        user_id: str,
        *,
        actor: RequestContext,
    ) -> dict[str, Any]:
        now = utc_now()
        with self.database.transaction() as connection:
            user = self.users.get(user_id, connection=connection)
            if user is None:
                raise auth_error("ADMIN_USER_NOT_FOUND")
            revoked = self.sessions.revoke_for_user(
                user_id,
                reason="admin_revoked",
                now=now,
                connection=connection,
            )
            self.audit.append(
                self._event(
                    "session_revoked",
                    actor,
                    user,
                    "succeeded",
                    f"Завершено активных сессий: {revoked}.",
                    now,
                ),
                connection=connection,
            )
        return {"user_id": user_id, "revoked_sessions_n": revoked}

    @staticmethod
    def role_catalog_payload() -> dict[str, Any]:
        return {
            "contract_name": "admin_role_catalog_v1",
            "schema_version": AUTH_CONTRACT_VERSION,
            "catalog_version": PERMISSION_CATALOG_VERSION,
            "permissions": [dict(permission) for permission in PERMISSION_CATALOG],
            "roles": [dict(ROLE_CATALOG[role_id]) for role_id in ("viewer", "analyst", "admin")],
        }

    def append_view_event(
        self,
        event_type: str,
        *,
        actor: RequestContext,
        summary: str,
    ) -> None:
        now = utc_now()
        self.audit.append(
            self._event(
                event_type,
                actor,
                {"user_id": actor.user_id},
                "succeeded",
                summary,
                now,
                target_type="administration",
            )
        )

    def audit_log(
        self,
        *,
        page: int,
        page_size: int,
        actor_user_id: str | None,
        event_type: str | None,
        occurred_from: datetime | None,
        occurred_to: datetime | None,
        sort: str,
    ) -> dict[str, Any]:
        items, total = self.audit.query(
            page=page,
            page_size=page_size,
            actor_user_id=actor_user_id,
            event_type=event_type,
            occurred_from=occurred_from,
            occurred_to=occurred_to,
            sort=sort,
        )
        return {
            "contract_name": "admin_audit_log_v1",
            "schema_version": AUTH_CONTRACT_VERSION,
            "items": items,
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total_items": total,
                "total_pages": (total + page_size - 1) // page_size,
            },
            "applied_filters": {
                "actor_user_id": actor_user_id,
                "event_type": event_type,
                "occurred_from_utc": utc_iso(occurred_from) if occurred_from else None,
                "occurred_to_utc": utc_iso(occurred_to) if occurred_to else None,
                "sort": sort,
            },
        }

    @staticmethod
    def _event(
        event_type: str,
        actor: RequestContext,
        target: Mapping[str, Any],
        result: str,
        summary: str,
        now: datetime,
        *,
        target_type: str = "user",
    ) -> dict[str, Any]:
        return {
            "event_id": opaque_id("evt"),
            "event_type": event_type,
            "occurred_at_utc": utc_iso(now),
            "actor_user_id": actor.user_id,
            "actor_display_name": actor.display_name,
            "target_type": target_type,
            "target_id": str(target.get("user_id")) if target.get("user_id") else None,
            "result": result,
            "browser_safe_summary": summary,
            "request_id": actor.request_id,
        }


@dataclass(frozen=True)
class LocalAuthStack:
    database: SQLiteAuthDatabase
    users: SQLiteUserRepository
    sessions: SQLiteSessionRepository
    attempts: SQLiteLoginAttemptRepository
    audit: SQLiteAuditRepository
    hasher: Argon2idPasswordHasher
    identity_provider: LocalPilotIdentityProvider
    authorization: AuthorizationGuard
    admin: AdminService


def build_local_auth_stack(settings: LocalAuthSettings) -> LocalAuthStack:
    settings.validate()
    database = SQLiteAuthDatabase(settings.database_path)
    users = SQLiteUserRepository(database)
    sessions = SQLiteSessionRepository(database)
    attempts = SQLiteLoginAttemptRepository(database)
    audit = SQLiteAuditRepository(database)
    hasher = Argon2idPasswordHasher(
        time_cost=settings.argon2_time_cost,
        memory_cost_kib=settings.argon2_memory_cost_kib,
        parallelism=settings.argon2_parallelism,
    )
    identity = LocalPilotIdentityProvider(
        settings,
        database,
        users,
        sessions,
        attempts,
        audit,
        hasher,
    )
    return LocalAuthStack(
        database=database,
        users=users,
        sessions=sessions,
        attempts=attempts,
        audit=audit,
        hasher=hasher,
        identity_provider=identity,
        authorization=AuthorizationGuard(),
        admin=AdminService(database, users, sessions, audit, hasher),
    )


def validate_user_id(value: str) -> str:
    if not _USER_ID_RE.fullmatch(value):
        raise auth_error("ADMIN_USER_NOT_FOUND")
    return value


def validate_request_id(value: str) -> str:
    if not _REQUEST_ID_RE.fullmatch(value):
        raise ValueError("Invalid request id")
    return value


def permission_ids() -> Sequence[str]:
    return tuple(str(item["permission_id"]) for item in PERMISSION_CATALOG)
