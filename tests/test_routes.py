import os
import re
import secrets
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

import pymupdf
from fastapi.testclient import TestClient

from main import app
from monitoramento.routes import router
from monitoramento.auth import _password_hash, create_first_admin, create_user
from monitoramento.bulletin_forms import BULLETIN_FIELDS
from monitoramento.data import MODULES
from monitoramento.pdf_analysis import PdfAnalysisError, analyze_bulletin
from monitoramento.tracking_store import load_module_updates


class MonitoringRoutesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.clients: list[TestClient] = []
        cls.temp_directory = tempfile.TemporaryDirectory()
        cls.database_path = Path(cls.temp_directory.name) / "monitoramento.sqlite3"
        cls.original_database_path = os.environ.get("MONITORAMENTO_DB_PATH")
        os.environ["MONITORAMENTO_DB_PATH"] = str(cls.database_path)
        admin = create_first_admin("admin", "AdminSenhaSegura#2026")
        for username, role, unit in (
            ("vera", "unit", "Unidade de Saúde de Vera (demonstração)"),
            ("outra", "unit", "Unidade de Saúde Diferente (demonstração)"),
            ("vigilancia", "surveillance", None),
        ):
            account = create_user(username, "SenhaTemporaria#2026", role, unit)
            salt = secrets.token_bytes(16)
            with closing(sqlite3.connect(cls.database_path)) as connection:
                connection.execute(
                    "UPDATE auth_users SET password_hash=?, password_salt=?, "
                    "must_change_password=0 WHERE id=?",
                    (
                        _password_hash("SenhaDeTesteForte#2026", salt),
                        salt,
                        account.id,
                    ),
                )
                connection.commit()
        cls.admin_id = admin.id
        load_module_updates(MODULES["tuberculose"])

    @classmethod
    def tearDownClass(cls) -> None:
        for client in cls.clients:
            client.close()
        if cls.original_database_path is None:
            os.environ.pop("MONITORAMENTO_DB_PATH", None)
        else:
            os.environ["MONITORAMENTO_DB_PATH"] = cls.original_database_path
        cls.temp_directory.cleanup()

    def setUp(self) -> None:
        with closing(sqlite3.connect(self.database_path)) as connection:
            connection.execute("DELETE FROM tracking_updates")
            connection.execute("DELETE FROM auth_sessions")
            connection.execute("DELETE FROM auth_login_attempts")
            connection.commit()
        self.client = TestClient(app, follow_redirects=False)
        self.clients.append(self.client)
        self._login("vera", "SenhaDeTesteForte#2026")

    def _switch_role(
        self,
        username: str,
        password: str = "SenhaDeTesteForte#2026",
    ) -> None:
        self.client.close()
        self.client = TestClient(app, follow_redirects=False)
        self.clients.append(self.client)
        self._login(username, password)

    def _login(self, username: str, password: str) -> None:
        response = self.client.get("/login")
        self.assertEqual(response.status_code, 200)
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', response.text)
        self.assertIsNotNone(csrf)
        response = self.client.post(
            "/login",
            data={
                "username": username,
                "password": password,
                "csrf_token": csrf.group(1),
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)

    def _form_csrf(self, path: str = "/tuberculose") -> str:
        response = self.client.get(path)
        self.assertEqual(response.status_code, 200)
        match = re.search(r'name="csrf_token" value="([^"]+)"', response.text)
        self.assertIsNotNone(match)
        return match.group(1)

    def test_home_and_legacy_panel_link_to_all_dashboards(self) -> None:
        for path in ("/", "/painel"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertIn('href="/tuberculose"', response.text)
                self.assertIn('href="/hanseniase"', response.text)
                self.assertIn('href="/vigilancia"', response.text)

    def test_module_requires_login_and_role_is_scoped_to_its_unit(self) -> None:
        self.client.close()
        self.client = TestClient(app, follow_redirects=False)
        self.clients.append(self.client)
        unauthenticated = self.client.get("/tuberculose")
        self.assertEqual(unauthenticated.status_code, 303)
        self.assertEqual(unauthenticated.headers["location"], "/login")

        self._login("vera", "SenhaDeTesteForte#2026")
        response = self.client.get(
            "/tuberculose",
            params={"unit": "Unidade Demonstrativa Norte"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("DEMO-TB-001", response.text)
        self.assertNotIn("DEMO-TB-003", response.text)
        self.assertIn("Ficha completa", response.text)
        self.assertIn("bac_apos_6_mes", response.text)

        denied = self.client.get("/vigilancia")
        self.assertEqual(denied.status_code, 403)

    def test_admin_can_create_account_with_forced_password_change(self) -> None:
        self._switch_role("admin", "AdminSenhaSegura#2026")
        page = self.client.get("/admin/usuarios")
        self.assertEqual(page.status_code, 200)
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
        self.assertIsNotNone(csrf)
        response = self.client.post(
            "/admin/usuarios",
            data={
                "csrf_token": csrf.group(1),
                "username": "nova-unidade",
                "role": "unit",
                "unit": "Unidade de Saúde de Vera (demonstração)",
                "password": "SenhaTemporaria#2026",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("Troca de senha obrigatória", response.text)

        self._switch_role("nova-unidade", "SenhaTemporaria#2026")
        restricted = self.client.get("/tuberculose")
        self.assertEqual(restricted.status_code, 303)
        self.assertEqual(restricted.headers["location"], "/trocar-senha")
        self.assertEqual(self.client.get("/trocar-senha").status_code, 200)

    def test_unit_can_change_initial_password(self) -> None:
        password = "SenhaInicialProvisorio#2026"
        create_user(
            "temporario",
            password,
            "unit",
            "Unidade de Saúde de Vera (demonstração)",
        )
        self._switch_role("temporario", password)
        restricted = self.client.get("/tuberculose")
        self.assertEqual(restricted.status_code, 303)
        self.assertEqual(restricted.headers["location"], "/trocar-senha")
        page = self.client.get("/trocar-senha")
        self.assertEqual(page.status_code, 200)
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
        self.assertIsNotNone(csrf)
        response = self.client.post(
            "/trocar-senha",
            data={
                "csrf_token": csrf.group(1),
                "password": "SenhaNovaSegura#2026",
                "confirmation": "SenhaNovaSegura#2026",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/tuberculose")
        self.assertEqual(self.client.get("/tuberculose").status_code, 200)

    def test_module_dashboards_contain_fictional_indicators_and_editable_notes(self) -> None:
        for path, identifier in (
            ("/tuberculose", "DEMO-TB-"),
            ("/hanseniase", "DEMO-HAN-"),
        ):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertIn(identifier, response.text)
                self.assertIn("Dados fictícios", response.text)
                self.assertIn('name="followup_status"', response.text)
                self.assertIn('name="contatos_identificados"', response.text)
                self.assertIn('name="contatos_examinados"', response.text)
                self.assertGreaterEqual(
                    response.text.count('name="data_ultimo_comparecimento"'),
                    1,
                )
                self.assertIn("<th>Data do último comparecimento</th>", response.text)
                self.assertIn('name="observation"', response.text)
                self.assertIn("Salvar alterações", response.text)
                self.assertIn("não possui login nem", response.text)
                self.assertIn("modelo reconstruído, não oficial", response.text)
                self.assertIn("A ausência de um registro", response.text)
                self.assertIn("Alertas demonstrativos", response.text)
                self.assertIn('action="/api/boletins/analisar"', response.text)
                self.assertIn('type="file" name="boletim"', response.text)
                self.assertIn("Importar boletim de", response.text)
                self.assertNotIn(
                    "DEMO-TB-003" if path == "/tuberculose" else "DEMO-HAN-003",
                    response.text,
                )

    def test_search_unit_status_and_month_filters(self) -> None:
        response = self.client.get(
            "/tuberculose",
            params={
                "search": "DEMO-TB-001",
                "unit": "Unidade Demonstrativa Norte",
                "followup_status": "Em acompanhamento",
                "month": "Novembro/2026",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("DEMO-TB-001", response.text)
        self.assertNotIn("DEMO-TB-002", response.text)

        no_match = self.client.get(
            "/tuberculose",
            params={"search": "registro-inexistente"},
        )
        self.assertEqual(no_match.status_code, 200)
        self.assertIn("Nenhum registro corresponde aos filtros", no_match.text)

    def test_vigilance_consolidates_units_and_pending_items(self) -> None:
        self._switch_role("vigilancia")
        response = self.client.get("/vigilancia")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Painel geral da Vigilância", response.text)
        self.assertIn("Unidade de Saúde de Vera (demonstração)", response.text)
        self.assertIn("Distrito Demonstrativo de Vera", response.text)
        self.assertIn("Alertas demonstrativos", response.text)
        self.assertIn("Unidades sem atualização mensal", response.text)
        self.assertIn("ausências apenas indicam necessidade", response.text)

    def test_status_and_routes(self) -> None:
        response = self.client.get("/api/status")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "Funcionando")
        routes = [(route.path, route.methods or set()) for route in router.routes]
        for path in (
            "/",
            "/painel",
            "/tuberculose",
            "/hanseniase",
            "/vigilancia",
            "/api/status",
        ):
            with self.subTest(path=path):
                self.assertEqual(sum(route_path == path for route_path, _ in routes), 1)
        for path, method in (
            ("/login", "GET"),
            ("/login", "POST"),
            ("/trocar-senha", "GET"),
            ("/trocar-senha", "POST"),
            ("/admin/usuarios", "GET"),
            ("/admin/usuarios", "POST"),
            ("/logout", "POST"),
            ("/api/acompanhamento/{agravo}/{record_id}", "POST"),
            ("/api/boletins/analisar", "POST"),
        ):
            with self.subTest(path=path, method=method):
                self.assertEqual(
                    sum(route_path == path and method in methods for route_path, methods in routes),
                    1,
                )

    def test_unit_can_save_and_reload_demo_followup_information(self) -> None:
        form_data = {
            field.key: ""
            for field in BULLETIN_FIELDS["tuberculose"]
        }
        form_data["contatos_identificados"] = "5"
        form_data["contatos_examinados"] = "4"
        response = self.client.post(
            "/api/acompanhamento/tuberculose/DEMO-TB-001",
            data={
                "csrf_token": self._form_csrf(),
                "followup_status": "Acompanhamento pendente",
                "pending_items": "Confirmar retorno (teste)",
                "observation": "Observação fictícia salva para teste.",
                **form_data,
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/tuberculose?saved=1")

        updated_page = self.client.get("/tuberculose")
        self.assertIn("Observação fictícia salva para teste.", updated_page.text)
        self.assertIn("Confirmar retorno (teste)", updated_page.text)
        self.assertIn('value="5" maxlength="250" min="0"', updated_page.text)
        self.assertIn('value="4" maxlength="250" min="0"', updated_page.text)

    def test_unit_can_save_last_attendance_date_for_both_conditions(self) -> None:
        for agravo, record_id in (
            ("tuberculose", "DEMO-TB-001"),
            ("hanseniase", "DEMO-HAN-001"),
        ):
            with self.subTest(agravo=agravo):
                form_values = {
                    field.key: ""
                    for field in BULLETIN_FIELDS[agravo]
                }
                form_values["data_ultimo_comparecimento"] = "2026-10-25"
                response = self.client.post(
                    f"/api/acompanhamento/{agravo}/{record_id}",
                    data={
                        "csrf_token": self._form_csrf(f"/{agravo}"),
                        "followup_status": "Em acompanhamento",
                        "pending_items": "",
                        "observation": "",
                        **form_values,
                    },
                    follow_redirects=False,
                )
                self.assertEqual(response.status_code, 303)

                page = self.client.get(f"/{agravo}")
                self.assertIn('name="data_ultimo_comparecimento"', page.text)
                self.assertIn('value="2026-10-25" maxlength="250"', page.text)

    def test_unit_cannot_save_inconsistent_contact_counts(self) -> None:
        form_data = {
            field.key: ""
            for field in BULLETIN_FIELDS["tuberculose"]
        }
        form_data["contatos_identificados"] = "1"
        form_data["contatos_examinados"] = "2"
        response = self.client.post(
            "/api/acompanhamento/tuberculose/DEMO-TB-001",
            data={
                "csrf_token": self._form_csrf(),
                "followup_status": "Em acompanhamento",
                "pending_items": "",
                "observation": "",
                **form_data,
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn("superar", response.json()["detail"])

    def test_unit_cannot_update_other_unit_records(self) -> None:
        form_data = {
            field.key: ""
            for field in BULLETIN_FIELDS["tuberculose"]
        }
        response = self.client.post(
            "/api/acompanhamento/tuberculose/DEMO-TB-003",
            data={
                "csrf_token": self._form_csrf(),
                "followup_status": "Em acompanhamento",
                **form_data,
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 403)

    def test_pdf_upload_returns_aggregate_without_patient_identifiers(self) -> None:
        self._switch_role("vigilancia")
        content = self.make_pdf(multirow_header=True)
        report = analyze_bulletin(content, "tuberculose")
        self.assertTrue(report.contact_columns_found)
        self.assertEqual(report.units[0].contacts_registered, 4)
        self.assertEqual(report.units[0].contacts_examined, 3)
        self.assertEqual(report.units[0].pending_contact_records, 1)
        response = self.client.post(
            "/api/boletins/analisar",
            data={"agravo": "tuberculose", "csrf_token": self._form_csrf()},
            files={"boletim": ("boletim.pdf", content, "application/pdf")},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("US Demonstrativa Central", response.text)
        self.assertIn("<td>2</td>", response.text)
        self.assertIn("<td>1</td>", response.text)
        self.assertIn("Contatos registrados", response.text)
        self.assertNotIn("Não identificado", response.text)
        self.assertIn("textarea", response.text)
        self.assertIn("localStorage.setItem", response.text)
        self.assertNotIn("123456", response.text)
        self.assertNotIn("123457", response.text)

    def test_blank_bulletin_is_a_valid_zero_case_summary(self) -> None:
        content = self.make_blank_bulletin_pdf()
        report = analyze_bulletin(content, "tuberculose")
        self.assertTrue(report.empty_bulletin)
        self.assertTrue(report.agravo_confirmed)
        self.assertTrue(report.contact_columns_found)
        self.assertEqual(report.units, ())
        self.assertEqual(report.records_without_unit, 0)

        response = self.client.post(
            "/api/boletins/analisar",
            data={"agravo": "tuberculose", "csrf_token": self._form_csrf()},
            files={"boletim": ("boletim-em-branco.pdf", content, "application/pdf")},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("Boletim em branco reconhecido", response.text)
        self.assertIn("nenhum registro foi listado nesta competência", response.text)
        self.assertIn("não altera nem encerra registros anteriores", response.text)

    def test_pdf_with_title_but_without_bulletin_headers_is_rejected(self) -> None:
        document = pymupdf.open()
        page = document.new_page()
        page.insert_text((50, 50), "Boletim de Acompanhamento de Tuberculose")
        content = document.tobytes()
        document.close()

        with self.assertRaisesRegex(PdfAnalysisError, "linhas"):
            analyze_bulletin(content, "tuberculose")

    def test_pdf_upload_rejects_non_pdf(self) -> None:
        self._switch_role("vigilancia")
        response = self.client.post(
            "/api/boletins/analisar",
            data={"agravo": "tuberculose", "csrf_token": self._form_csrf()},
            files={"boletim": ("fake.pdf", b"not a pdf", "application/pdf")},
        )
        self.assertEqual(response.status_code, 400)

    def test_pdf_upload_rejects_wrong_module(self) -> None:
        self._switch_role("vigilancia")
        response = self.client.post(
            "/api/boletins/analisar",
            data={"agravo": "hanseniase", "csrf_token": self._form_csrf()},
            files={"boletim": ("boletim.pdf", self.make_pdf(), "application/pdf")},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("outro agravo", response.json()["detail"])

    @staticmethod
    def make_blank_bulletin_pdf() -> bytes:
        document = pymupdf.open()
        page = document.new_page()
        page.insert_text((50, 50), "Boletim de Acompanhamento de Tuberculose")
        page.insert_text((50, 80), "Unidade: ________")
        page.insert_text(
            (50, 120),
            "Nº da Notificação Atual  Data da Notificação Atual  Nome  "
            "Total contatos identificados  Total contatos examinados",
            fontsize=8,
        )
        content = document.tobytes()
        document.close()
        return content

    @staticmethod
    def make_pdf(multirow_header: bool = False) -> bytes:
        document = pymupdf.open()
        page = document.new_page()
        page.insert_text((50, 50), "Boletim de Acompanhamento de Tuberculose")
        page.insert_text((50, 80), "Unidade: US Demonstrativa Central")
        columns = [30, 180, 300, 420, 540]
        rows = [200, 220, 240, 260, 280] if multirow_header else [200, 230, 260]
        for y in rows:
            page.draw_line((columns[0], y), (columns[-1], y), width=0.7)
        for x in columns:
            page.draw_line((x, rows[0]), (x, rows[-1]), width=0.7)

        if multirow_header:
            header_lines = (
                ("Nº Notificação", "Data Notificação", "Total", "Total"),
                ("", "", "Contatos identificados", "Contatos examinados"),
            )
            for row_index, header in enumerate(header_lines):
                for index, value in enumerate(header):
                    if value:
                        page.insert_text(
                            (columns[index] + 4, rows[row_index] + 15),
                            value,
                            fontsize=7,
                        )
        else:
            headers = (
                "Nº Notificação",
                "Data Notificação",
                "Contatos identificados",
                "Contatos examinados",
            )
            for index, value in enumerate(headers):
                page.insert_text((columns[index] + 4, rows[0] + 18), value, fontsize=8)
        data_rows = (
            ("123456", "01/11/2026", "3", "2"),
            ("123457", "02/11/2026", "1", "1"),
        )
        data_start = 2 if multirow_header else 1
        for row_index, values in enumerate(data_rows, start=data_start):
            for column_index, value in enumerate(values):
                page.insert_text(
                    (columns[column_index] + 4, rows[row_index] + 15),
                    value,
                    fontsize=8,
                )
        content = document.tobytes()
        document.close()
        return content


if __name__ == "__main__":
    unittest.main()
