import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from monitoramento.auth import (
    allow_password_reset_attempt,
    authenticate,
    create_session,
    create_user,
    get_session,
    issue_password_reset_token,
    reset_password_with_token,
    set_user_recovery_email,
)
from monitoramento.recovery_mail import send_password_reset_email


class PasswordRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        self.original_database_path = os.environ.get("MONITORAMENTO_DB_PATH")
        os.environ["MONITORAMENTO_DB_PATH"] = str(
            Path(self.temp_directory.name) / "auth.sqlite3"
        )
        self.user = create_user(
            "recovery-user",
            "SenhaAntigaSegura#2026",
            "unit",
            "Unidade fictícia",
            "profissional@example.test",
        )

    def tearDown(self) -> None:
        if self.original_database_path is None:
            os.environ.pop("MONITORAMENTO_DB_PATH", None)
        else:
            os.environ["MONITORAMENTO_DB_PATH"] = self.original_database_path
        self.temp_directory.cleanup()

    def test_reset_token_is_hashed_single_use_revokes_sessions_and_keeps_role(self) -> None:
        session_token, _ = create_session(self.user.id)
        issued = issue_password_reset_token("PROFISSIONAL@example.test", "192.0.2.1")
        self.assertIsNotNone(issued)
        token, recipient = issued
        self.assertEqual(recipient, "profissional@example.test")
        with closing(sqlite3.connect(os.environ["MONITORAMENTO_DB_PATH"])) as connection:
            stored_hash = connection.execute(
                "SELECT token_hash FROM auth_password_reset_tokens"
            ).fetchone()[0]
        self.assertNotEqual(stored_hash, token)

        self.assertTrue(reset_password_with_token(token, "SenhaNovaSegura#2026"))
        self.assertFalse(reset_password_with_token(token, "OutraSenhaSegura#2026"))
        self.assertIsNone(get_session(session_token))
        self.assertIsNone(authenticate("recovery-user", "SenhaAntigaSegura#2026"))
        authenticated = authenticate("recovery-user", "SenhaNovaSegura#2026")
        self.assertIsNotNone(authenticated)
        self.assertEqual(authenticated.role, "unit")
        self.assertEqual(authenticated.unit, "Unidade fictícia")

    def test_expired_token_is_rejected(self) -> None:
        with patch("monitoramento.auth.time.time", return_value=1_800_000_000):
            token, _ = issue_password_reset_token(
                "profissional@example.test", "192.0.2.2"
            )
        with patch("monitoramento.auth.time.time", return_value=1_800_001_801):
            self.assertFalse(reset_password_with_token(token, "SenhaNovaSegura#2026"))

    def test_unknown_email_is_ineligible_and_request_limits_apply(self) -> None:
        self.assertIsNone(
            issue_password_reset_token("nao-cadastrado@example.test", "192.0.2.3")
        )
        for _ in range(10):
            self.assertTrue(allow_password_reset_attempt("192.0.2.4"))
        self.assertFalse(allow_password_reset_attempt("192.0.2.4"))
        for _ in range(3):
            self.assertIsNotNone(
                issue_password_reset_token(
                    "profissional@example.test", "192.0.2.5"
                )
            )
        self.assertIsNone(
            issue_password_reset_token("profissional@example.test", "192.0.2.5")
        )

    def test_admin_managed_email_can_be_cleared_and_reassigned(self) -> None:
        set_user_recovery_email(self.user.id, None)
        self.assertIsNone(
            issue_password_reset_token("profissional@example.test", "192.0.2.6")
        )
        set_user_recovery_email(self.user.id, "novo@example.test")
        self.assertIsNotNone(
            issue_password_reset_token("novo@example.test", "192.0.2.6")
        )

    def test_mail_uses_configured_https_origin_and_never_relies_on_request_host(self) -> None:
        with patch.dict(
            os.environ,
            {
                "SMTP_HOST": "smtp.example.test",
                "SMTP_PORT": "587",
                "SMTP_USERNAME": "test-user",
                "SMTP_PASSWORD": "fake-secret-for-test",
                "SMTP_FROM": "noreply@example.test",
                "APP_BASE_URL": "https://monitoramento.example.test",
            },
        ), patch("monitoramento.recovery_mail.smtplib.SMTP") as smtp_factory:
            send_password_reset_email("profissional@example.test", "token-ficticio")
        smtp = smtp_factory.return_value.__enter__.return_value
        smtp.starttls.assert_called_once()
        message = smtp.send_message.call_args.args[0]
        self.assertEqual(
            message["Subject"],
            "Monitoramento Ativo — Recuperação de senha",
        )
        self.assertIn(
            "https://monitoramento.example.test/redefinir-senha#token=token-ficticio",
            message.get_content(),
        )
        self.assertNotIn("fake-secret-for-test", message.as_string())

    def test_existing_auth_database_is_migrated_without_assigning_an_email(self) -> None:
        legacy_path = Path(self.temp_directory.name) / "legacy.sqlite3"
        with closing(sqlite3.connect(legacy_path)) as connection:
            connection.execute(
                """
                CREATE TABLE auth_users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE,
                    password_hash BLOB NOT NULL,
                    password_salt BLOB NOT NULL,
                    role TEXT NOT NULL,
                    unit TEXT,
                    active INTEGER NOT NULL DEFAULT 1,
                    must_change_password INTEGER NOT NULL DEFAULT 1,
                    created_at INTEGER NOT NULL
                )
                """
            )
            connection.execute(
                """
                INSERT INTO auth_users (
                    username, password_hash, password_salt, role, unit,
                    active, must_change_password, created_at
                ) VALUES ('legacy', X'01', X'02', 'unit', 'Unidade fictícia', 1, 0, 1)
                """
            )
            connection.commit()

        os.environ["MONITORAMENTO_DB_PATH"] = str(legacy_path)
        try:
            from monitoramento.auth import list_users

            users = list_users()
            self.assertEqual(len(users), 1)
            self.assertIsNone(users[0].email)
            with closing(sqlite3.connect(legacy_path)) as connection:
                columns = {
                    row[1] for row in connection.execute("PRAGMA table_info(auth_users)")
                }
            self.assertIn("email", columns)
        finally:
            os.environ["MONITORAMENTO_DB_PATH"] = str(
                Path(self.temp_directory.name) / "auth.sqlite3"
            )


if __name__ == "__main__":
    unittest.main()
