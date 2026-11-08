import os
import tempfile
import unittest
from pathlib import Path

from monitoramento.auth import (
    authenticate,
    create_first_admin,
    create_session,
    create_user,
    get_session,
)
from monitoramento.reset_admin_password import reset_admin_password


class AdminPasswordResetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        self.original_database_path = os.environ.get("MONITORAMENTO_DB_PATH")
        os.environ["MONITORAMENTO_DB_PATH"] = str(
            Path(self.temp_directory.name) / "auth.sqlite3"
        )
        self.admin = create_first_admin("admin-local", "SenhaAntigaSegura#2026")

    def tearDown(self) -> None:
        if self.original_database_path is None:
            os.environ.pop("MONITORAMENTO_DB_PATH", None)
        else:
            os.environ["MONITORAMENTO_DB_PATH"] = self.original_database_path
        self.temp_directory.cleanup()

    def test_reset_changes_only_active_admin_password_and_revokes_sessions(self) -> None:
        session_token, _ = create_session(self.admin.id)

        reset_admin_password(" ADMIN-LOCAL ", "SenhaNovaSegura#2026")

        self.assertIsNone(authenticate("admin-local", "SenhaAntigaSegura#2026"))
        self.assertEqual(
            authenticate("admin-local", "SenhaNovaSegura#2026").role,
            "admin",
        )
        self.assertIsNone(get_session(session_token))

    def test_reset_rejects_non_admin_without_changing_their_password(self) -> None:
        unit = create_user(
            "unit-local",
            "SenhaUnidadeSegura#2026",
            "unit",
            "Unidade fictícia",
        )

        with self.assertRaisesRegex(ValueError, "Administradora ativa"):
            reset_admin_password("unit-local", "SenhaNovaSegura#2026")

        self.assertIsNotNone(authenticate("unit-local", "SenhaUnidadeSegura#2026"))
        self.assertIsNotNone(unit)


if __name__ == "__main__":
    unittest.main()
