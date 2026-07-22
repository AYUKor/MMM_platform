from __future__ import annotations

import json
import sqlite3
import stat
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from dataclasses import replace
from datetime import timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any, Mapping
from unittest.mock import patch


WEB_APP_DIR = Path(__file__).resolve().parents[1]
if str(WEB_APP_DIR) not in sys.path:
    sys.path.insert(0, str(WEB_APP_DIR))

from api.http_smoke import HttpSmokeApplication, HttpSmokeSettings, make_handler  # noqa: E402
from contracts.admin_audit_log_v1 import validate_admin_audit_log  # noqa: E402
from contracts.admin_role_catalog_v1 import validate_admin_role_catalog  # noqa: E402
from contracts.admin_system_status_v1 import validate_admin_system_status  # noqa: E402
from contracts.admin_user_detail_v1 import validate_admin_user_detail  # noqa: E402
from contracts.admin_user_list_v1 import validate_admin_user_list  # noqa: E402
from contracts.auth_contract_utils import AuthContractError  # noqa: E402
from contracts.auth_session_v1 import validate_auth_session  # noqa: E402
from services.auth_admin import (  # noqa: E402
    AuthAdminError,
    Argon2idPasswordHasher,
    LocalAuthSettings,
    SessionResolution,
    authenticated_session_payload,
    build_local_auth_stack,
    opaque_id,
    permission_ids,
    utc_iso,
    utc_now,
)


TEST_SECRET = "phase-e-auth-admin-test-session-secret"
ADMIN_PASSWORD = "Phase-e-admin-2026"
PASSPORT_FIXTURE = WEB_APP_DIR / "tests" / "fixtures" / "model_passport_v1_synthetic.json"
_NO_BODY = object()


def _settings(root: Path, *, max_attempts: int = 3) -> LocalAuthSettings:
    return LocalAuthSettings(
        database_path=root / "auth.sqlite3",
        session_secret=TEST_SECRET,
        session_ttl_seconds=3_600,
        idle_timeout_seconds=300,
        login_window_seconds=900,
        login_max_attempts=max_attempts,
        login_cooldown_seconds=900,
        argon2_time_cost=2,
        argon2_memory_cost_kib=19_456,
        argon2_parallelism=1,
    )


class AuthAdminServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.stack = build_local_auth_stack(_settings(self.root))
        bootstrap = self.stack.identity_provider.bootstrap_admin(
            email="admin@example.org",
            password=ADMIN_PASSWORD,
            display_name="Тестовый администратор",
            update_existing=False,
        )
        self.admin_id = str(bootstrap["user_id"])
        self.admin_context, self.admin_token = self.stack.identity_provider.authenticate(
            "admin@example.org",
            ADMIN_PASSWORD,
            request_id=opaque_id("req"),
            client_key="127.0.0.1",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_argon2id_hash_verification_and_rebootstrap_safety(self) -> None:
        user = self.stack.users.get(self.admin_id)
        self.assertIsNotNone(user)
        assert user is not None
        self.assertEqual(user["password_algorithm"], "argon2id-v1")
        self.assertTrue(str(user["password_hash"]).startswith("$argon2id$"))
        self.assertNotIn(ADMIN_PASSWORD, str(user["password_hash"]))
        self.assertEqual(
            stat.S_IMODE(self.stack.database.path.stat().st_mode),
            0o600,
        )
        with self.stack.database.connection() as connection:
            stored_digest = connection.execute(
                "SELECT token_digest FROM sessions WHERE session_id = ?",
                (self.admin_context.session_id,),
            ).fetchone()[0]
        self.assertNotEqual(stored_digest, self.admin_token)
        self.assertNotIn(self.admin_token, self.stack.database.path.read_bytes().decode("latin1"))
        verified, _ = self.stack.hasher.verify_password(user["password_hash"], ADMIN_PASSWORD)
        self.assertTrue(verified)

        unchanged = self.stack.identity_provider.bootstrap_admin(
            email="admin@example.org",
            password="Different-admin-2026",
            display_name="Другое имя",
            update_existing=False,
        )
        self.assertEqual(unchanged["status"], "already_exists")
        after = self.stack.users.get(self.admin_id)
        assert after is not None
        self.assertEqual(after["display_name"], "Тестовый администратор")

        weak_hasher = Argon2idPasswordHasher(
            time_cost=2,
            memory_cost_kib=19_456,
            parallelism=1,
        )
        weak_hash = weak_hasher.hash_password(ADMIN_PASSWORD)
        with self.stack.database.transaction() as connection:
            self.stack.users.update_fields(
                self.admin_id,
                {"password_hash": weak_hash, "password_algorithm": "argon2id-v1"},
                now=utc_now(),
                connection=connection,
            )
        stronger_stack = build_local_auth_stack(
            LocalAuthSettings(
                database_path=self.root / "auth.sqlite3",
                session_secret=TEST_SECRET,
                session_ttl_seconds=3_600,
                idle_timeout_seconds=300,
                login_max_attempts=3,
                argon2_time_cost=3,
                argon2_memory_cost_kib=32_768,
                argon2_parallelism=1,
            )
        )
        stronger_stack.identity_provider.authenticate(
            "admin@example.org",
            ADMIN_PASSWORD,
            request_id=opaque_id("req"),
            client_key="127.0.0.1",
        )
        rehashed = stronger_stack.users.get(self.admin_id)
        assert rehashed is not None
        self.assertNotEqual(rehashed["password_hash"], weak_hash)

    def test_wrong_password_and_unknown_email_share_one_response(self) -> None:
        failures = []
        for email, password in (
            ("admin@example.org", "Wrong-password-2026"),
            ("missing@example.org", "Wrong-password-2026"),
        ):
            with self.assertRaises(AuthAdminError) as captured:
                self.stack.identity_provider.authenticate(
                    email,
                    password,
                    request_id=opaque_id("req"),
                    client_key="10.0.0.1",
                )
            failures.append((captured.exception.code, captured.exception.display_text))
        self.assertEqual(failures[0], failures[1])
        self.assertEqual(failures[0][0], "AUTH_INVALID_CREDENTIALS")
        with self.stack.database.connection() as connection:
            audit_text = json.dumps(
                [dict(row) for row in connection.execute("SELECT * FROM audit_events")],
                ensure_ascii=False,
            )
        self.assertNotIn("missing@example.org", audit_text)
        self.assertNotIn("Wrong-password-2026", audit_text)

    def test_login_rate_limit_has_cooldown(self) -> None:
        limited_stack = build_local_auth_stack(_settings(self.root / "limited", max_attempts=2))
        for _ in range(2):
            with self.assertRaises(AuthAdminError) as captured:
                limited_stack.identity_provider.authenticate(
                    "missing@example.org",
                    "Wrong-password-2026",
                    request_id=opaque_id("req"),
                    client_key="10.0.0.2",
                )
            self.assertEqual(captured.exception.code, "AUTH_INVALID_CREDENTIALS")
        with self.assertRaises(AuthAdminError) as captured:
            limited_stack.identity_provider.authenticate(
                "missing@example.org",
                "Wrong-password-2026",
                request_id=opaque_id("req"),
                client_key="10.0.0.2",
            )
        self.assertEqual(captured.exception.code, "AUTH_RATE_LIMITED")

    def test_self_registration_creates_analyst_session_and_audit_event(self) -> None:
        context, token = self.stack.identity_provider.register(
            "New-Analyst@Example.org",
            "Self-registered-2026",
            "Новый аналитик",
            request_id=opaque_id("req"),
            client_key="10.10.0.1",
        )
        self.assertEqual(context.role_id, "analyst")
        self.assertNotIn("admin.users.read", context.permissions)
        self.assertNotIn("admin.roles.write", context.permissions)
        self.assertEqual(
            self.stack.identity_provider.resolve_session(
                token,
                request_id=opaque_id("req"),
            ).state,
            "authenticated",
        )
        user = self.stack.users.find_by_email("new-analyst@example.org")
        assert user is not None
        self.assertEqual(user["role_id"], "analyst")
        self.assertEqual(user["status"], "active")
        self.assertIsNone(user["created_by_user_id"])
        self.assertTrue(str(user["password_hash"]).startswith("$argon2id$"))
        self.assertNotIn("Self-registered-2026", str(user["password_hash"]))

        events, total = self.stack.audit.query(
            page=1,
            page_size=10,
            actor_user_id=None,
            event_type="user_self_registered",
            occurred_from=None,
            occurred_to=None,
            sort="occurred_desc",
        )
        self.assertEqual(total, 1)
        self.assertEqual(events[0]["target_id"], user["user_id"])
        self.assertEqual(events[0]["result"], "succeeded")
        serialized = json.dumps(events, ensure_ascii=False).casefold()
        self.assertNotIn("new-analyst@example.org", serialized)
        self.assertNotIn("self-registered-2026", serialized)

        derived, _ = self.stack.identity_provider.register(
            "derived@example.org",
            "Derived-password-2026",
            None,
            request_id=opaque_id("req"),
            client_key="10.10.0.2",
        )
        self.assertEqual(derived.display_name, "derived")
        blank, _ = self.stack.identity_provider.register(
            "blank-name@example.org",
            "Blank-name-password-2026",
            "   ",
            request_id=opaque_id("req"),
            client_key="10.10.0.3",
        )
        self.assertEqual(blank.display_name, "blank-name")

    def test_self_registration_duplicate_email_is_non_disclosing(self) -> None:
        with self.assertRaises(AuthAdminError) as captured:
            self.stack.identity_provider.register(
                "ADMIN@example.org",
                "Duplicate-password-2026",
                None,
                request_id=opaque_id("req"),
                client_key="10.10.0.4",
            )
        self.assertEqual(captured.exception.code, "AUTH_REGISTRATION_FAILED")
        self.assertEqual(captured.exception.http_status, 409)
        self.assertNotIn("admin@example.org", captured.exception.display_text.casefold())
        events, total = self.stack.audit.query(
            page=1,
            page_size=10,
            actor_user_id=None,
            event_type="user_self_registered",
            occurred_from=None,
            occurred_to=None,
            sort="occurred_desc",
        )
        self.assertEqual((events, total), ([], 0))
        original = self.stack.users.find_by_email("admin@example.org")
        assert original is not None
        self.assertEqual(original["role_id"], "admin")

    def test_self_registration_validation_and_rate_limit(self) -> None:
        for email, password in (
            ("weak@example.org", "short"),
            ("weak@example.org", "no-digits-inside-this-password"),
            ("not-an-email", "Valid-password-2026"),
        ):
            with self.assertRaises(AuthAdminError) as captured:
                self.stack.identity_provider.register(
                    email,
                    password,
                    None,
                    request_id=opaque_id("req"),
                    client_key="10.10.0.5",
                )
            self.assertEqual(captured.exception.code, "AUTH_REGISTRATION_INVALID")
            self.assertEqual(captured.exception.http_status, 422)
        self.assertIsNone(self.stack.users.find_by_email("weak@example.org"))

        limited = build_local_auth_stack(_settings(self.root / "reglimit", max_attempts=2))
        for _ in range(2):
            with self.assertRaises(AuthAdminError) as failed:
                limited.identity_provider.register(
                    "invalid-email",
                    "short",
                    None,
                    request_id=opaque_id("req"),
                    client_key="10.10.0.6",
                )
            self.assertEqual(failed.exception.code, "AUTH_REGISTRATION_INVALID")
        with self.assertRaises(AuthAdminError) as throttled:
            limited.identity_provider.register(
                "still-invalid",
                "Throttled-password-2026",
                None,
                request_id=opaque_id("req"),
                client_key="10.10.0.6",
            )
        self.assertEqual(throttled.exception.code, "AUTH_RATE_LIMITED")

    def test_session_expiry_revoke_and_disabled_user(self) -> None:
        resolution = self.stack.identity_provider.resolve_session(
            self.admin_token,
            request_id=opaque_id("req"),
        )
        self.assertEqual(resolution.state, "authenticated")
        with self.stack.database.transaction() as connection:
            connection.execute(
                "UPDATE sessions SET expires_at_utc = ? WHERE session_id = ?",
                (
                    utc_iso(utc_now() - timedelta(seconds=1)),
                    self.admin_context.session_id,
                ),
            )
        self.assertEqual(
            self.stack.identity_provider.resolve_session(
                self.admin_token,
                request_id=opaque_id("req"),
            ).state,
            "expired",
        )

        detail = self.stack.admin.create_user(
            {
                "email": "analyst@example.org",
                "display_name": "Тестовый аналитик",
                "password": "Analyst-password-2026",
                "role_id": "analyst",
            },
            actor=self.admin_context,
        )
        analyst_id = detail["user"]["user_id"]
        _, analyst_token = self.stack.identity_provider.authenticate(
            "analyst@example.org",
            "Analyst-password-2026",
            request_id=opaque_id("req"),
            client_key="127.0.0.1",
        )
        self.stack.admin.set_user_enabled(
            analyst_id,
            enabled=False,
            actor=self.admin_context,
        )
        self.assertEqual(
            self.stack.identity_provider.resolve_session(
                analyst_token,
                request_id=opaque_id("req"),
            ).state,
            "expired",
        )

    def test_permissions_last_admin_and_self_disable_guards(self) -> None:
        self.assertEqual(set(self.admin_context.permissions), set(permission_ids()))
        with self.assertRaises(AuthAdminError) as downgrade:
            self.stack.admin.update_user(
                self.admin_id,
                {"role_id": "viewer"},
                actor=self.admin_context,
            )
        self.assertEqual(downgrade.exception.code, "ADMIN_LAST_ADMIN_PROTECTED")
        with self.assertRaises(AuthAdminError) as disable:
            self.stack.admin.set_user_enabled(
                self.admin_id,
                enabled=False,
                actor=self.admin_context,
            )
        self.assertEqual(disable.exception.code, "ADMIN_LAST_ADMIN_PROTECTED")

    def test_admin_service_enforces_write_permissions_by_action(self) -> None:
        target = self.stack.admin.create_user(
            {
                "email": "permission-target@example.org",
                "display_name": "Проверка разрешений",
                "password": "Permission-target-2026",
                "role_id": "viewer",
            },
            actor=self.admin_context,
        )
        target_id = target["user"]["user_id"]
        users_writer = replace(
            self.admin_context,
            permissions=("admin.users.write",),
        )
        roles_writer = replace(
            self.admin_context,
            permissions=("admin.roles.write",),
        )
        sessions_writer = replace(
            self.admin_context,
            permissions=("admin.sessions.write",),
        )

        renamed = self.stack.admin.update_user(
            target_id,
            {"display_name": "Новое имя"},
            actor=users_writer,
        )
        self.assertEqual(renamed["user"]["display_name"], "Новое имя")
        disabled = self.stack.admin.set_user_enabled(
            target_id,
            enabled=False,
            actor=users_writer,
        )
        self.assertEqual(disabled["user"]["status"], "disabled")

        with self.assertRaises(AuthAdminError) as create_denied:
            self.stack.admin.create_user(
                {
                    "email": "permission-denied@example.org",
                    "display_name": "Нет назначения роли",
                    "password": "Permission-denied-2026",
                    "role_id": "viewer",
                },
                actor=users_writer,
            )
        self.assertEqual(create_denied.exception.code, "PERMISSION_DENIED")
        with self.assertRaises(AuthAdminError) as role_denied:
            self.stack.admin.update_user(
                target_id,
                {"role_id": "analyst"},
                actor=users_writer,
            )
        self.assertEqual(role_denied.exception.code, "PERMISSION_DENIED")
        with self.assertRaises(AuthAdminError) as session_denied:
            self.stack.admin.revoke_user_sessions(
                target_id,
                actor=users_writer,
            )
        self.assertEqual(session_denied.exception.code, "PERMISSION_DENIED")

        role_updated = self.stack.admin.update_user(
            target_id,
            {"role_id": "analyst"},
            actor=roles_writer,
        )
        self.assertEqual(role_updated["user"]["role"]["role_id"], "analyst")
        revoked = self.stack.admin.revoke_user_sessions(
            target_id,
            actor=sessions_writer,
        )
        self.assertEqual(revoked["user_id"], target_id)

    def test_contracts_audit_pagination_and_append_only_storage(self) -> None:
        session_payload = authenticated_session_payload(self.admin_context)
        self.assertEqual(validate_auth_session(session_payload), session_payload)
        roles = self.stack.admin.role_catalog_payload()
        self.assertEqual(validate_admin_role_catalog(roles), roles)
        detail = self.stack.admin.user_detail(self.admin_id)
        self.assertEqual(validate_admin_user_detail(detail), detail)
        listing = self.stack.admin.list_users(
            page=1,
            page_size=10,
            search="администратор",
            role_id="admin",
            status="active",
            sort="created_desc",
        )
        self.assertEqual(validate_admin_user_list(listing), listing)
        log = self.stack.admin.audit_log(
            page=1,
            page_size=50,
            actor_user_id=None,
            event_type=None,
            occurred_from=None,
            occurred_to=None,
            sort="occurred_desc",
        )
        self.assertEqual(validate_admin_audit_log(log), log)
        try:
            import jsonschema
        except ImportError:
            jsonschema = None
        if jsonschema is not None:
            for schema_name, contract_payload in (
                ("auth_session_v1", session_payload),
                ("admin_role_catalog_v1", roles),
                ("admin_user_detail_v1", detail),
                ("admin_user_list_v1", listing),
                ("admin_audit_log_v1", log),
            ):
                schema = json.loads(
                    (WEB_APP_DIR / "contracts" / f"{schema_name}.schema.json").read_text(
                        encoding="utf-8"
                    )
                )
                jsonschema.Draft202012Validator(
                    schema,
                    format_checker=jsonschema.FormatChecker(),
                ).validate(contract_payload)
        serialized = json.dumps(log, ensure_ascii=False).casefold()
        for forbidden in ("password", "token", "cookie", TEST_SECRET.casefold(), "/users/"):
            self.assertNotIn(forbidden, serialized)
        with self.stack.database.transaction() as connection:
            with self.assertRaises(sqlite3.DatabaseError):
                connection.execute("DELETE FROM audit_events")

        invalid = json.loads(json.dumps(session_payload))
        invalid["user"]["permissions"] = ["workspace.read"]
        with self.assertRaises(AuthContractError):
            validate_auth_session(invalid)
        wrong_version = json.loads(json.dumps(session_payload))
        wrong_version["schema_version"] = "2.0.0"
        with self.assertRaises(AuthContractError):
            validate_auth_session(wrong_version)
        extra_key = json.loads(json.dumps(session_payload))
        extra_key["session_token"] = "must-not-exist"
        with self.assertRaises(AuthContractError):
            validate_auth_session(extra_key)
        invalid_user = json.loads(json.dumps(detail))
        invalid_user["user"]["user_id"] = "usr_invalid"
        with self.assertRaises(AuthContractError):
            validate_admin_user_detail(invalid_user)
        unsafe_audit = json.loads(json.dumps(log))
        unsafe_audit["items"][0]["browser_safe_summary"] = "/Users/private/audit.log"
        with self.assertRaises(AuthContractError):
            validate_admin_audit_log(unsafe_audit)
        duplicate_audit = json.loads(json.dumps(log))
        duplicate_audit["items"].append(dict(duplicate_audit["items"][0]))
        with self.assertRaises(AuthContractError):
            validate_admin_audit_log(duplicate_audit)


class AuthAdminHttpTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        passport = json.loads(PASSPORT_FIXTURE.read_text(encoding="utf-8"))
        self.application = HttpSmokeApplication(
            HttpSmokeSettings(
                state_root=root / "state",
                runtime_root=root / "runtime",
                artifact_root=root / "artifacts",
                project_root=WEB_APP_DIR.parent,
                auth_database_path=root / "auth.sqlite3",
                auth_session_secret=TEST_SECRET,
                auth_session_ttl_seconds=3_600,
                auth_idle_timeout_seconds=300,
                auth_login_max_attempts=3,
                auth_argon2_time_cost=2,
                auth_argon2_memory_cost_kib=19_456,
                auth_argon2_parallelism=1,
            ),
            model_passport=passport,
        )
        self.application.auth.identity_provider.bootstrap_admin(
            email="admin@example.org",
            password=ADMIN_PASSWORD,
            display_name="Тестовый администратор",
            update_existing=False,
        )
        admin_context, admin_token = self.application.auth.identity_provider.authenticate(
            "admin@example.org",
            ADMIN_PASSWORD,
            request_id=opaque_id("req"),
            client_key="127.0.0.1",
        )
        self.admin_context = admin_context
        self.admin_id = admin_context.user_id
        viewer = self.application.auth.admin.create_user(
            {
                "email": "viewer@example.org",
                "display_name": "Тестовый наблюдатель",
                "password": "Viewer-password-2026",
                "role_id": "viewer",
            },
            actor=admin_context,
        )
        analyst = self.application.auth.admin.create_user(
            {
                "email": "analyst@example.org",
                "display_name": "Тестовый аналитик",
                "password": "Analyst-password-2026",
                "role_id": "analyst",
            },
            actor=admin_context,
        )
        self.viewer_id = viewer["user"]["user_id"]
        self.analyst_id = analyst["user"]["user_id"]
        _, viewer_token = self.application.auth.identity_provider.authenticate(
            "viewer@example.org",
            "Viewer-password-2026",
            request_id=opaque_id("req"),
            client_key="127.0.0.1",
        )
        _, analyst_token = self.application.auth.identity_provider.authenticate(
            "analyst@example.org",
            "Analyst-password-2026",
            request_id=opaque_id("req"),
            client_key="127.0.0.1",
        )
        self.cookies = {
            "admin": f"mmm_session={admin_token}",
            "viewer": f"mmm_session={viewer_token}",
            "analyst": f"mmm_session={analyst_token}",
        }
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.application))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.application.close()
        self.temporary.cleanup()

    def request(
        self,
        method: str,
        path: str,
        *,
        payload: Any = _NO_BODY,
        cookie: str | None = None,
        origin: str | None = "http://localhost:4173",
    ) -> tuple[int, Any, Mapping[str, str]]:
        body = None
        headers: dict[str, str] = {}
        if payload is not _NO_BODY:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if cookie:
            headers["Cookie"] = cookie
        if method in {"POST", "PATCH"} and origin is not None:
            headers["Origin"] = origin
        request = urllib.request.Request(
            self.base_url + path,
            data=body,
            headers=headers,
            method=method,
        )
        try:
            response = urllib.request.urlopen(request, timeout=3)
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read()), dict(exc.headers)
        with response:
            raw = response.read()
            content_type = response.headers.get("Content-Type", "")
            parsed = json.loads(raw) if content_type.startswith("application/json") else raw
            return response.status, parsed, dict(response.headers)

    def assert_security_headers(self, headers: Mapping[str, str]) -> None:
        self.assertEqual(headers.get("Cache-Control"), "no-store")
        self.assertEqual(headers.get("Pragma"), "no-cache")
        self.assertEqual(headers.get("X-Content-Type-Options"), "nosniff")

    def request_with_permissions(
        self,
        method: str,
        path: str,
        *,
        permissions: tuple[str, ...],
        payload: Any = _NO_BODY,
    ) -> tuple[int, Any, Mapping[str, str]]:
        controlled_token = "controlled-permission-context"
        controlled_context = replace(
            self.admin_context,
            permissions=permissions,
        )
        original_resolver = self.application.auth.identity_provider.resolve_session

        def resolve_session(token: str | None, *, request_id: str) -> SessionResolution:
            if token == controlled_token:
                return SessionResolution(
                    "authenticated",
                    replace(controlled_context, request_id=request_id),
                )
            return original_resolver(token, request_id=request_id)

        with patch.object(
            self.application.auth.identity_provider,
            "resolve_session",
            side_effect=resolve_session,
        ):
            return self.request(
                method,
                path,
                payload=payload,
                cookie=f"mmm_session={controlled_token}",
            )

    def test_login_session_logout_cookie_and_generic_failure(self) -> None:
        status, anonymous, headers = self.request("GET", "/api/v1/auth/session")
        self.assertEqual(status, 200)
        self.assertFalse(anonymous["authenticated"])
        self.assert_security_headers(headers)

        failures = []
        for email in ("admin@example.org", "missing@example.org"):
            status, error, headers = self.request(
                "POST",
                "/api/v1/auth/login",
                payload={"email": email, "password": "Wrong-password-2026"},
            )
            self.assert_security_headers(headers)
            failures.append((status, error["error"]["code"], error["error"]["display_text"]))
        self.assertEqual(failures[0], failures[1])

        status, session, headers = self.request(
            "POST",
            "/api/v1/auth/login",
            payload={"email": "admin@example.org", "password": ADMIN_PASSWORD},
        )
        self.assertEqual(status, 200)
        self.assertTrue(session["authenticated"])
        self.assert_security_headers(headers)
        self.assertNotIn("token", json.dumps(session).casefold())
        set_cookie = headers["Set-Cookie"]
        for flag in ("HttpOnly", "SameSite=Lax", "Path=/api/v1"):
            self.assertIn(flag, set_cookie)
        browser_cookie = set_cookie.split(";", 1)[0]
        status, current, headers = self.request(
            "GET", "/api/v1/auth/session", cookie=browser_cookie
        )
        self.assertEqual(status, 200)
        self.assertTrue(current["authenticated"])
        self.assert_security_headers(headers)
        status, logged_out, headers = self.request(
            "POST", "/api/v1/auth/logout", cookie=browser_cookie
        )
        self.assertEqual(status, 200)
        self.assertFalse(logged_out["authenticated"])
        self.assertIn("Max-Age=0", headers["Set-Cookie"])

    def test_central_permissions_distinguish_401_and_403(self) -> None:
        status, error, headers = self.request("GET", "/api/v1/admin/users")
        self.assertEqual((status, error["error"]["code"]), (401, "AUTH_REQUIRED"))
        self.assert_security_headers(headers)

        status, home, _ = self.request(
            "GET", "/api/v1/workspace/home", cookie=self.cookies["viewer"]
        )
        self.assertEqual(status, 200)
        self.assertEqual(home["contract_name"], "workspace_home_v1")
        status, error, _ = self.request(
            "POST",
            "/api/v1/jobs",
            payload={},
            cookie=self.cookies["viewer"],
        )
        self.assertEqual((status, error["error"]["code"]), (403, "PERMISSION_DENIED"))
        status, error, _ = self.request(
            "POST",
            "/api/v1/jobs",
            payload={},
            cookie=self.cookies["analyst"],
        )
        self.assertEqual((status, error["error"]["code"]), (422, "INVALID_JOB"))
        status, error, headers = self.request(
            "GET", "/api/v1/admin/users", cookie=self.cookies["analyst"]
        )
        self.assertEqual((status, error["error"]["code"]), (403, "PERMISSION_DENIED"))
        self.assert_security_headers(headers)

    def test_http_permissions_separate_user_role_and_session_writes(self) -> None:
        users_write = ("admin.users.write",)
        users_and_roles_write = ("admin.users.write", "admin.roles.write")

        status, renamed, _ = self.request_with_permissions(
            "PATCH",
            f"/api/v1/admin/users/{self.viewer_id}",
            permissions=users_write,
            payload={"display_name": "Наблюдатель с новым именем"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(renamed["user"]["display_name"], "Наблюдатель с новым именем")

        status, error, _ = self.request_with_permissions(
            "POST",
            "/api/v1/admin/users",
            permissions=users_write,
            payload={
                "email": "http-role-denied@example.org",
                "display_name": "Нет права роли",
                "password": "Http-role-denied-2026",
                "role_id": "viewer",
            },
        )
        self.assertEqual((status, error["error"]["code"]), (403, "PERMISSION_DENIED"))
        status, error, _ = self.request_with_permissions(
            "PATCH",
            f"/api/v1/admin/users/{self.viewer_id}",
            permissions=users_write,
            payload={"role_id": "analyst"},
        )
        self.assertEqual((status, error["error"]["code"]), (403, "PERMISSION_DENIED"))

        status, created, _ = self.request_with_permissions(
            "POST",
            "/api/v1/admin/users",
            permissions=users_and_roles_write,
            payload={
                "email": "http-role-allowed@example.org",
                "display_name": "Разрешено назначить роль",
                "password": "Http-role-allowed-2026",
                "role_id": "viewer",
            },
        )
        self.assertEqual(status, 201)
        status, updated, _ = self.request_with_permissions(
            "PATCH",
            f"/api/v1/admin/users/{created['user']['user_id']}",
            permissions=users_and_roles_write,
            payload={"role_id": "analyst"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(updated["user"]["role"]["role_id"], "analyst")

        status, error, _ = self.request_with_permissions(
            "POST",
            f"/api/v1/admin/users/{self.analyst_id}/sessions/revoke",
            permissions=users_write,
        )
        self.assertEqual((status, error["error"]["code"]), (403, "PERMISSION_DENIED"))
        status, revoked, _ = self.request_with_permissions(
            "POST",
            f"/api/v1/admin/users/{self.analyst_id}/sessions/revoke",
            permissions=("admin.sessions.write",),
        )
        self.assertEqual(status, 200)
        self.assertGreaterEqual(revoked["revoked_sessions_n"], 1)

    def test_admin_users_roles_revoke_system_audit_and_schema_discovery(self) -> None:
        status, users, headers = self.request(
            "GET",
            "/api/v1/admin/users?role=analyst&status=active&page=1&page_size=10",
            cookie=self.cookies["admin"],
        )
        self.assertEqual(status, 200)
        self.assert_security_headers(headers)
        self.assertEqual(users["items"][0]["user_id"], self.analyst_id)
        status, created, _ = self.request(
            "POST",
            "/api/v1/admin/users",
            payload={
                "email": "operator@example.org",
                "display_name": "Новый пользователь",
                "password": "Operator-password-2026",
                "role_id": "viewer",
            },
            cookie=self.cookies["admin"],
        )
        self.assertEqual(status, 201)
        operator_id = created["user"]["user_id"]
        status, updated, _ = self.request(
            "PATCH",
            f"/api/v1/admin/users/{operator_id}",
            payload={"display_name": "Пользователь отчетов", "role_id": "analyst"},
            cookie=self.cookies["admin"],
        )
        self.assertEqual(status, 200)
        self.assertEqual(updated["user"]["role"]["role_id"], "analyst")
        status, disabled, _ = self.request(
            "POST",
            f"/api/v1/admin/users/{operator_id}/disable",
            cookie=self.cookies["admin"],
        )
        self.assertEqual(status, 200)
        self.assertEqual(disabled["user"]["status"], "disabled")
        status, _, _ = self.request(
            "POST",
            f"/api/v1/admin/users/{operator_id}/enable",
            cookie=self.cookies["admin"],
        )
        self.assertEqual(status, 200)

        status, revoked, _ = self.request(
            "POST",
            f"/api/v1/admin/users/{self.analyst_id}/sessions/revoke",
            cookie=self.cookies["admin"],
        )
        self.assertEqual(status, 200)
        self.assertGreaterEqual(revoked["revoked_sessions_n"], 1)
        status, error, _ = self.request(
            "GET", "/api/v1/workspace/home", cookie=self.cookies["analyst"]
        )
        self.assertEqual((status, error["error"]["code"]), (401, "AUTH_SESSION_EXPIRED"))

        system_payload = None
        for path, contract in (
            ("/api/v1/admin/roles", "admin_role_catalog_v1"),
            ("/api/v1/admin/system/status", "admin_system_status_v1"),
            ("/api/v1/admin/audit?page_size=100", "admin_audit_log_v1"),
        ):
            status, payload, headers = self.request("GET", path, cookie=self.cookies["admin"])
            self.assertEqual(status, 200)
            self.assert_security_headers(headers)
            self.assertEqual(payload["contract_name"], contract)
            if contract == "admin_system_status_v1":
                system_payload = payload
            serialized = json.dumps(payload, ensure_ascii=False).casefold()
            for forbidden in ("password", "token", "cookie", "/users/", TEST_SECRET.casefold()):
                self.assertNotIn(forbidden, serialized)
        assert system_payload is not None
        invalid_system = json.loads(json.dumps(system_payload))
        invalid_system["overall_status"] = (
            "healthy" if system_payload["overall_status"] != "healthy" else "degraded"
        )
        with self.assertRaises(AuthContractError):
            validate_admin_system_status(invalid_system)
        for contract_name in (
            "auth-session-v1",
            "auth-registration-v1",
            "admin-user-list-v1",
            "admin-user-detail-v1",
            "admin-user-mutation-v1",
            "admin-role-catalog-v1",
            "admin-system-status-v1",
            "admin-audit-log-v1",
        ):
            status, schema, _ = self.request(
                "GET",
                f"/api/v1/contracts/{contract_name}.json",
                cookie=self.cookies["admin"],
            )
            self.assertEqual(status, 200)
            self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")

    def test_self_registration_http_flow_issues_analyst_session(self) -> None:
        status, session, headers = self.request(
            "POST",
            "/api/v1/auth/register",
            payload={
                "email": "self@example.org",
                "password": "Self-registered-2026",
                "display_name": "Самостоятельный аналитик",
            },
        )
        self.assertEqual(status, 201)
        self.assertTrue(session["authenticated"])
        self.assertEqual(session["user"]["role"]["role_id"], "analyst")
        self.assertNotIn("admin.users.read", session["user"]["permissions"])
        self.assertEqual(validate_auth_session(session), session)
        self.assert_security_headers(headers)
        self.assertNotIn("token", json.dumps(session).casefold())
        set_cookie = headers["Set-Cookie"]
        for flag in ("HttpOnly", "SameSite=Lax", "Path=/api/v1"):
            self.assertIn(flag, set_cookie)
        browser_cookie = set_cookie.split(";", 1)[0]
        status, current, _ = self.request(
            "GET", "/api/v1/auth/session", cookie=browser_cookie
        )
        self.assertEqual(status, 200)
        self.assertTrue(current["authenticated"])
        status, error, _ = self.request(
            "GET", "/api/v1/admin/users", cookie=browser_cookie
        )
        self.assertEqual((status, error["error"]["code"]), (403, "PERMISSION_DENIED"))

        status, audit, _ = self.request(
            "GET",
            "/api/v1/admin/audit?event_type=user_self_registered",
            cookie=self.cookies["admin"],
        )
        self.assertEqual(status, 200)
        self.assertGreaterEqual(audit["pagination"]["total_items"], 1)
        serialized = json.dumps(audit, ensure_ascii=False).casefold()
        self.assertNotIn("self@example.org", serialized)

    def test_self_registration_http_failures_stay_generic(self) -> None:
        status, error, headers = self.request(
            "POST",
            "/api/v1/auth/register",
            payload={"email": "analyst@example.org", "password": "Another-password-2026"},
        )
        self.assertEqual(status, 409)
        self.assertEqual(error["error"]["code"], "AUTH_REGISTRATION_FAILED")
        self.assertNotIn("analyst@example.org", json.dumps(error))
        self.assert_security_headers(headers)

        for payload in (
            {"email": "new@example.org", "password": "short"},
            {"email": "new@example.org", "password": "no-digits-inside-this-password"},
            {"email": "invalid", "password": "Valid-password-2026"},
            {"email": "new@example.org", "password": "Valid-password-2026", "role_id": "admin"},
        ):
            status, error, _ = self.request(
                "POST",
                "/api/v1/auth/register",
                payload=payload,
            )
            self.assertEqual((status, error["error"]["code"]), (422, "AUTH_REGISTRATION_INVALID"))
        self.assertIsNone(self.application.auth.users.find_by_email("new@example.org"))

        status, error, _ = self.request(
            "POST",
            "/api/v1/auth/register",
            payload={"email": "csrf@example.org", "password": "Csrf-password-2026"},
            origin=None,
        )
        self.assertEqual((status, error["error"]["code"]), (403, "PERMISSION_DENIED"))
        status, error, _ = self.request(
            "POST",
            "/api/v1/auth/register",
            payload={"email": "csrf@example.org", "password": "Csrf-password-2026"},
            origin="https://evil.example.org",
        )
        self.assertEqual((status, error["error"]["code"]), (403, "PERMISSION_DENIED"))

    def test_csrf_origin_and_last_admin_are_enforced(self) -> None:
        status, error, _ = self.request(
            "POST",
            "/api/v1/auth/login",
            payload={"email": "admin@example.org", "password": ADMIN_PASSWORD},
            origin=None,
        )
        self.assertEqual((status, error["error"]["code"]), (403, "PERMISSION_DENIED"))
        status, error, _ = self.request(
            "POST",
            "/api/v1/auth/login",
            payload={"email": "admin@example.org", "password": ADMIN_PASSWORD},
            origin="https://evil.example.org",
        )
        self.assertEqual((status, error["error"]["code"]), (403, "PERMISSION_DENIED"))
        status, error, _ = self.request(
            "POST",
            f"/api/v1/admin/users/{self.admin_id}/disable",
            cookie=self.cookies["admin"],
        )
        self.assertEqual(
            (status, error["error"]["code"]),
            (409, "ADMIN_LAST_ADMIN_PROTECTED"),
        )


if __name__ == "__main__":
    unittest.main()
