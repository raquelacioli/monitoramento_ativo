from firestore_support import FirestoreTestCase
from monitoramento.firestore_store import get_store, key
import os
import re
import secrets
import unittest
from unittest.mock import patch

import pymupdf
from fastapi.testclient import TestClient

from main import app
from monitoramento.routes import router
from monitoramento.auth import (
    _password_hash,
    authenticate,
    change_password,
    create_first_admin,
    create_session,
    create_user,
    delete_user,
    get_session,
    list_users,
    reset_password_with_token,
    COOKIE_NAME,
    set_user_recovery_email,
)
from monitoramento.bulletin_forms import BULLETIN_FIELDS
from monitoramento.data import MODULES
from monitoramento.monthly_store import (
    get_monthly_followup,
    list_monthly_followups,
    get_monthly_record,
    import_monthly_records,
    create_manual_followup,
)
from monitoramento.pdf_analysis import PdfAnalysisError, analyze_bulletin
from monitoramento.tracking_store import load_module_updates
from bulletin_pdf_factory import make_tb_pdf


class MonitoringRoutesTests(FirestoreTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.clients = []
        admin = create_first_admin("admin", "AdminSenhaSegura#2026")
        self.admin_id = admin.id
        for username, role, unit in (
            ("vera", "unit", "Unidade de Saúde de Vera (demonstração)"),
            ("outra", "unit", "Unidade de Saúde Diferente (demonstração)"),
            ("vigilancia", "surveillance", None),
        ):
            account = create_user(username, "SenhaTemporaria#2026", role, unit)
            change_password(account.id, "SenhaDeTesteForte#2026")
        self.client = TestClient(app, follow_redirects=False)
        self.clients.append(self.client)
        self._login("vera", "SenhaDeTesteForte#2026")
        self.addCleanup(lambda: [client.close() for client in self.clients])

    def _require_password_change(self, user_id, required):
        def update(tx):
            row = tx.get('auth_users', key(user_id))
            row['must_change_password'] = required
            tx.set('auth_users', key(user_id), row)
        get_store().run(update, guard='auth')

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

    def test_forced_password_change_blocks_protected_posts_for_all_roles(self) -> None:
        cases = {
            "admin": (
                ("/admin/usuarios", {"username": "blocked-user", "role": "unit",
                 "unit": "Unidade teste", "password": "SenhaTemporaria#2026"}),
                (f"/admin/usuarios/{self.admin_id}/email", {"email": ""}),
                (f"/admin/usuarios/{self.admin_id}/senha",
                 {"password": "SenhaTemporaria#2026", "confirmation": "SenhaTemporaria#2026"}),
                (f"/admin/usuarios/{self.admin_id}/desativar", {}),
                (f"/admin/usuarios/{self.admin_id}/excluir", {}),
            ),
            "vigilancia": (
                ("/api/vigilancia/competencias/tuberculose/2027-01/abrir", {}),
                ("/api/vigilancia/competencias/tuberculose/2027-01/encerrar", {}),
                ("/api/vigilancia/historico/tuberculose/2027-01/teste/revisar",
                 {"approved": "true"}),
            ),
            "vera": (
                ("/api/historico/tuberculose/2027-01/teste/enviar", {}),
            ),
        }
        for username, requests in cases.items():
            account = next(user for user in list_users() if user.username == username)
            self._require_password_change(account.id, True)
            token, csrf = create_session(account.id)
            self.client.cookies.set(COOKIE_NAME, token)
            try:
                for path, data in requests:
                    with self.subTest(username=username, path=path):
                        token, csrf = create_session(account.id)
                        self.client.cookies.set(COOKIE_NAME, token)
                        response = self.client.post(path, data={**data, "csrf_token": csrf})
                        self.assertEqual(response.status_code, 403)
                        self.assertIn("Altere a senha", response.text)
                self.assertEqual(self.client.get("/trocar-senha").status_code, 200)
                self.assertEqual(
                    self.client.post("/logout", data={"csrf_token": csrf}).status_code, 303
                )
            finally:
                self._require_password_change(account.id, False)

    def test_communication_hides_previous_values_from_another_unit(self) -> None:
        unit = "Unidade de Saúde de Vera (demonstração)"
        for competence, record_unit, value in (
            ("2026-10", "Outra unidade", "SEGREDO-OUTRA-UNIDADE"),
            ("2026-11", unit, "Valor atual"),
        ):
            import_monthly_records(
                agravo="tuberculose", competence=competence,
                source_content=competence.encode(), imported_by="vigilancia",
                records=[{"patient_ref": "transferido", "unit_ref": record_unit,
                          "values": {"forma": value}}],
            )
        followup = create_manual_followup(
            agravo="tuberculose", competence="2026-11", patient_ref="transferido",
            unit_ref=unit, actor="vigilancia", text="Conferir campo.", field_key="forma",
        )
        response = self.client.get(f"/comunicacao/{followup.id}")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Valor atual", response.text)
        self.assertNotIn("SEGREDO-OUTRA-UNIDADE", response.text)

    def test_individual_import_requires_preview_confirmation_and_unit_matching(self) -> None:
        unit = "Unidade de Saúde de Vera (demonstração)"
        self._switch_role("vigilancia")
        csrf = self._form_csrf()
        page = self.client.get("/vigilancia/importar")
        self.assertEqual(page.status_code, 200)
        response = self.client.post(
            "/api/boletins/previsualizar",
            data={"csrf_token": csrf, "competence": "2026-11", "unit": unit},
            files={"boletim": ("ficticio.pdf", make_tb_pdf(unit=unit), "application/pdf")},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("PESSOA FICTICIA ALFA", response.text)
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertIsNone(get_monthly_record(agravo="tuberculose", competence="2026-11", patient_ref="900001"))
        token = re.search(r'name="preview_token" value="([^"]+)"', response.text).group(1)
        invalid_csrf = self.client.post("/api/boletins/confirmar", data={"csrf_token": "invalid", "preview_token": token})
        self.assertEqual(invalid_csrf.status_code, 403)
        confirmed = self.client.post("/api/boletins/confirmar", data={"csrf_token": csrf, "preview_token": token})
        self.assertEqual(confirmed.status_code, 200)
        self.assertIn("2 registros importados", confirmed.text)
        record = get_monthly_record(agravo="tuberculose", competence="2026-11", patient_ref="900001")
        self.assertEqual(record.unit_ref, unit)
        self.assertEqual(record.original_values["hiv"]["codigo"], "2")
        repeated = self.client.post("/api/boletins/confirmar", data={"csrf_token": csrf, "preview_token": token})
        self.assertEqual(repeated.status_code, 422)
        mismatch = self.client.post(
            "/api/boletins/previsualizar",
            data={"csrf_token": csrf, "competence": "2026-11", "unit": unit},
            files={"boletim": ("ficticio.pdf", make_tb_pdf(unit="Outra unidade"), "application/pdf")},
        )
        self.assertEqual(mismatch.status_code, 422)
        preview = self.client.post(
            "/api/boletins/previsualizar",
            data={"csrf_token": csrf, "competence": "2026-12", "unit": unit},
            files={"boletim": ("ficticio.pdf", make_tb_pdf(unit=unit), "application/pdf")},
        )
        token = re.search(r'name="preview_token" value="([^"]+)"', preview.text).group(1)
        discarded = self.client.post("/api/boletins/cancelar", data={"csrf_token": csrf, "preview_token": token})
        self.assertEqual(discarded.status_code, 303)
        self.assertIsNone(get_monthly_record(agravo="tuberculose", competence="2026-12", patient_ref="900001"))
        denied = self.client.post("/api/boletins/confirmar", data={"csrf_token": csrf, "preview_token": token})
        self.assertEqual(denied.status_code, 422)

    def test_individual_import_denies_unit_and_forced_password_accounts(self) -> None:
        self.assertEqual(self.client.get("/vigilancia/importar").status_code, 403)
        csrf = self._form_csrf()
        denied = self.client.post("/api/boletins/confirmar", data={"csrf_token": csrf, "preview_token": "x" * 43})
        self.assertEqual(denied.status_code, 403)
        self._switch_role("vigilancia")
        csrf = self._form_csrf()
        surveillance = next(u for u in list_users() if u.username == 'vigilancia')
        self._require_password_change(surveillance.id, True)
        denied = self.client.post("/api/boletins/confirmar", data={"csrf_token": csrf, "preview_token": "x" * 43})
        self.assertEqual(denied.status_code, 403)

    def test_stale_login_form_returns_fresh_form_without_authenticating(self) -> None:
        self.client.cookies.clear()
        old_page = self.client.get("/login")
        old_token = re.search(r'name="csrf_token" value="([^"]+)"', old_page.text).group(1)
        self.client.get("/login")  # Another tab replaces the anonymous cookie.
        with patch("monitoramento.routes.authenticate") as authenticate_mock:
            rejected = self.client.post("/login", data={
                "username": "admin", "password": "AdminSenhaSegura#2026", "csrf_token": old_token,
            })
            self.assertEqual(rejected.status_code, 403)
            self.assertIn("text/html", rejected.headers["content-type"])
            self.assertIn("Abra o login no Edge ou Chrome", rejected.text)
            authenticate_mock.assert_not_called()
        fresh_token = re.search(r'name="csrf_token" value="([^"]+)"', rejected.text).group(1)
        self.assertNotEqual(old_token, fresh_token)
        self.assertEqual(rejected.headers["cache-control"], "no-store")
        retried = self.client.post("/login", data={
            "username": "admin", "password": "AdminSenhaSegura#2026", "csrf_token": fresh_token,
        })
        self.assertEqual(retried.status_code, 303)
        self.assertEqual(retried.headers["location"], "/admin/usuarios")

    def test_missing_login_cookie_returns_fresh_form_without_authenticating(self) -> None:
        self.client.cookies.clear()
        with patch("monitoramento.routes.authenticate") as authenticate_mock:
            rejected = self.client.post("/login", data={
                "username": "admin", "password": "AdminSenhaSegura#2026", "csrf_token": "expired",
            })
            self.assertEqual(rejected.status_code, 403)
            self.assertIn('name="csrf_token"', rejected.text)
            self.assertIn("monitoramento_login_csrf", rejected.cookies)
            authenticate_mock.assert_not_called()

    def test_home_and_legacy_panel_link_to_all_dashboards(self) -> None:
        for path in ("/", "/painel"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertIn('href="/tuberculose"', response.text)
                self.assertIn('href="/hanseniase"', response.text)
                self.assertIn('href="/vigilancia"', response.text)

    def test_login_has_accessible_password_toggle_and_recovery_link(self) -> None:
        self.client.post(
            "/logout",
            data={"csrf_token": self._form_csrf()},
            follow_redirects=False,
        )
        login_page = self.client.get("/login")
        self.assertEqual(login_page.status_code, 200)
        self.assertIn('id="login-password" type="password"', login_page.text)
        self.assertIn('aria-label="Mostrar senha"', login_page.text)
        self.assertIn('input.type = visible ? "text" : "password"', login_page.text)
        self.assertIn('href="/recuperar-senha">Esqueceu sua senha?</a>', login_page.text)

    def test_recovery_response_is_indistinguishable_for_known_and_unknown_email(self) -> None:
        self.client.post(
            "/logout",
            data={"csrf_token": self._form_csrf()},
            follow_redirects=False,
        )
        page = self.client.get("/recuperar-senha")
        self.assertEqual(page.status_code, 200)
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
        with patch("monitoramento.routes.send_password_reset_email") as send_email:
            unknown = self.client.post(
                "/recuperar-senha",
                data={"csrf_token": csrf, "email": "ausente@example.test"},
            )
            self.assertEqual(unknown.status_code, 200)
            self.assertIn(
                "Se o e-mail informado estiver cadastrado, você receberá as instruções",
                unknown.text,
            )
            send_email.assert_not_called()

            vera_id = next(user.id for user in list_users() if user.username == "vera")
            set_user_recovery_email(vera_id, "vera@example.test")
            try:
                known = self.client.post(
                    "/recuperar-senha",
                    data={"csrf_token": csrf, "email": "vera@example.test"},
                )
                self.assertEqual(known.status_code, 200)
                self.assertIn(
                    "Se o e-mail informado estiver cadastrado, você receberá as instruções",
                    known.text,
                )
                send_email.assert_called_once()
            finally:
                set_user_recovery_email(vera_id, None)

    def test_password_reset_route_completes_without_automatic_login(self) -> None:
        self.client.post(
            "/logout",
            data={"csrf_token": self._form_csrf()},
            follow_redirects=False,
        )
        vera_id = next(user.id for user in list_users() if user.username == "vera")
        set_user_recovery_email(vera_id, "vera-reset@example.test")
        try:
            page = self.client.get("/recuperar-senha")
            csrf = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
            with patch("monitoramento.routes.send_password_reset_email") as send_email:
                requested = self.client.post(
                    "/recuperar-senha",
                    data={
                        "csrf_token": csrf,
                        "email": "vera-reset@example.test",
                    },
                )
            self.assertEqual(requested.status_code, 200)
            token = send_email.call_args.args[1]

            reset_page = self.client.get("/redefinir-senha")
            reset_csrf = re.search(
                r'name="csrf_token" value="([^"]+)"', reset_page.text
            ).group(1)
            reset = self.client.post(
                "/redefinir-senha",
                data={
                    "csrf_token": reset_csrf,
                    "token": token,
                    "password": "SenhaRecuperada#2026",
                    "confirmation": "SenhaRecuperada#2026",
                },
            )
            self.assertEqual(reset.status_code, 200)
            self.assertIn(
                "Senha redefinida com sucesso. Você já pode acessar o sistema",
                reset.text,
            )
            self.assertNotIn("monitoramento_session", self.client.cookies)
            account = authenticate("vera", "SenhaRecuperada#2026")
            self.assertEqual(account.role, "unit")
            self.assertEqual(account.unit, "Unidade de Saúde de Vera (demonstração)")
        finally:
            set_user_recovery_email(vera_id, None)
            change_password(vera_id, "SenhaDeTesteForte#2026")

    def test_mail_failure_keeps_generic_response_and_does_not_log_secrets(self) -> None:
        self.client.post(
            "/logout",
            data={"csrf_token": self._form_csrf()},
            follow_redirects=False,
        )
        vera_id = next(user.id for user in list_users() if user.username == "vera")
        recipient = "vera-mail-failure@example.test"
        set_user_recovery_email(vera_id, recipient)
        try:
            page = self.client.get("/recuperar-senha")
            csrf = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
            with patch(
                "monitoramento.routes.send_password_reset_email",
                side_effect=OSError("fictitious SMTP secret detail"),
            ) as send_email, self.assertLogs(
                "monitoramento.routes", level="WARNING"
            ) as captured_logs:
                response = self.client.post(
                    "/recuperar-senha",
                    data={"csrf_token": csrf, "email": recipient},
                )
            token = send_email.call_args.args[1]
            self.assertIn(
                "Se o e-mail informado estiver cadastrado, você receberá as instruções",
                response.text,
            )
            logged_text = "\n".join(captured_logs.output)
            self.assertNotIn(recipient, logged_text)
            self.assertNotIn(token, logged_text)
            self.assertNotIn("fictitious SMTP secret detail", logged_text)
            self.assertFalse(
                reset_password_with_token(token, "SenhaNovaSegura#2026")
            )
        finally:
            set_user_recovery_email(vera_id, None)

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

    def test_admin_can_reset_active_account_password_and_force_change(self) -> None:
        self._switch_role("admin", "AdminSenhaSegura#2026")
        surveillance = next(user for user in list_users() if user.username == "vigilancia")
        self.addCleanup(
            change_password,
            surveillance.id,
            "SenhaDeTesteForte#2026",
        )
        session_token, _ = create_session(surveillance.id)
        page = self.client.get("/admin/usuarios")
        self.assertEqual(page.status_code, 200)
        self.assertIn(f'action="/admin/usuarios/{surveillance.id}/senha"', page.text)
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
        self.assertIsNotNone(csrf)

        mismatch = self.client.post(
            f"/admin/usuarios/{surveillance.id}/senha",
            data={
                "csrf_token": csrf.group(1),
                "password": "SenhaTemporariaNova#2026",
                "confirmation": "SenhaTemporariaErrada#2026",
            },
        )
        self.assertIn("As senhas não conferem", mismatch.text)
        self.assertIsNotNone(authenticate("vigilancia", "SenhaDeTesteForte#2026"))

        response = self.client.post(
            f"/admin/usuarios/{surveillance.id}/senha",
            data={
                "csrf_token": csrf.group(1),
                "password": "SenhaTemporariaNova#2026",
                "confirmation": "SenhaTemporariaNova#2026",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("deverá escolher uma nova senha", response.text)
        self.assertIsNone(get_session(session_token))
        account = authenticate("vigilancia", "SenhaTemporariaNova#2026")
        self.assertIsNotNone(account)
        self.assertTrue(account.must_change_password)

        self._switch_role("vigilancia", "SenhaTemporariaNova#2026")
        restricted = self.client.get("/vigilancia")
        self.assertEqual(restricted.status_code, 303)
        self.assertEqual(restricted.headers["location"], "/trocar-senha")

    def test_unit_cannot_reset_another_accounts_password(self) -> None:
        surveillance = next(user for user in list_users() if user.username == "vigilancia")
        csrf = self._form_csrf()
        response = self.client.post(
            f"/admin/usuarios/{surveillance.id}/senha",
            data={
                "csrf_token": csrf,
                "password": "SenhaTemporariaNova#2026",
                "confirmation": "SenhaTemporariaNova#2026",
            },
        )
        self.assertEqual(response.status_code, 403)
        self.assertIsNotNone(authenticate("vigilancia", "SenhaDeTesteForte#2026"))

    def test_admin_can_delete_account_then_create_replacement(self) -> None:
        self._switch_role("admin", "AdminSenhaSegura#2026")
        surveillance = next(user for user in list_users() if user.username == "vigilancia")
        session_token, _ = create_session(surveillance.id)
        page = self.client.get("/admin/usuarios")
        self.assertIn(f'action="/admin/usuarios/{surveillance.id}/excluir"', page.text)
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
        self.assertIsNotNone(csrf)

        response = self.client.post(
            f"/admin/usuarios/{surveillance.id}/excluir",
            data={"csrf_token": csrf.group(1)},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Conta excluída definitivamente", response.text)
        self.assertNotIn("vigilancia</td>", response.text)
        self.assertIsNone(get_session(session_token))
        self.assertIsNone(authenticate("vigilancia", "SenhaDeTesteForte#2026"))
        replacement = create_user(
            "vigilancia",
            "SenhaTemporaria#2026",
            "surveillance",
            None,
        )
        self.assertTrue(replacement.must_change_password)

    def test_admin_cannot_delete_own_account(self) -> None:
        self._switch_role("admin", "AdminSenhaSegura#2026")
        admin = next(user for user in list_users() if user.username == "admin")
        page = self.client.get("/admin/usuarios")
        self.assertNotIn(f'action="/admin/usuarios/{admin.id}/excluir"', page.text)
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
        response = self.client.post(
            f"/admin/usuarios/{admin.id}/excluir",
            data={"csrf_token": csrf.group(1)},
        )
        self.assertIn("Não é possível excluir a própria conta", response.text)

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
                self.assertIn("Envio do boletim mensal", response.text)
                self.assertIn(
                    f'href="/monitoramento-mensal?agravo={path.removeprefix("/")}"',
                    response.text,
                )
                self.assertIn(
                    "As alterações demonstrativas desta página não enviam o boletim.",
                    response.text,
                )
                self.assertIn('name="followup_status"', response.text)
                self.assertIn('name="contatos_identificados"', response.text)
                self.assertIn('name="contatos_examinados"', response.text)
                self.assertGreaterEqual(
                    response.text.count('name="data_ultimo_comparecimento"'),
                    1,
                )
                self.assertIn("<th>Data do último comparecimento</th>", response.text)
                self.assertIn("<th>Observação da unidade</th>", response.text)
                self.assertIn('name="observation"', response.text)
                self.assertIn("Salvar alterações", response.text)
                self.assertIn("Para registrar uma observação do profissional", response.text)
                self.assertIn("preencha “Resposta da unidade”", response.text)
                self.assertIn("transcritos das fichas em branco fornecidas", response.text)
                self.assertIn("A ausência de um registro", response.text)
                self.assertIn("Alertas demonstrativos", response.text)
                self.assertIn('value="1"', response.text)
                if path == "/tuberculose":
                    self.assertIn(
                        'data-transfer-field="update-tuberculose-DEMO-TB-001" hidden',
                        response.text,
                    )
                    self.assertIn("4 - Em andamento", response.text)
                    self.assertIn(
                        "2 - Não detectável resistente à rifampicina",
                        response.text,
                    )
                else:
                    self.assertIn("1 - PB — Paucibacilar", response.text)
                self.assertNotIn('action="/api/boletins/analisar"', response.text)
                self.assertNotIn('type="file" name="boletim"', response.text)
                self.assertNotIn("Importar boletim de", response.text)
                self.assertNotIn('href="/vigilancia"', response.text)
                self.assertNotIn("Unidade Demonstrativa Norte", response.text)
                self.assertNotIn(
                    "DEMO-TB-003" if path == "/tuberculose" else "DEMO-HAN-003",
                    response.text,
                )

    def test_unit_cannot_open_import_interface_or_upload_endpoint(self) -> None:
        page = self.client.get("/tuberculose")
        for forbidden in (
            '<section class="upload-panel"',
            '<form class="upload-controls"',
            "/api/boletins/analisar",
            '<input type="file"',
            "Importar boletim",
            'href="/vigilancia"',
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, page.text)

        response = self.client.post(
            "/api/boletins/analisar",
            data={
                "csrf_token": self._form_csrf(),
                "agravo": "tuberculose",
            },
            files={
                "boletim": (
                    "boletim.pdf",
                    self.make_pdf(),
                    "application/pdf",
                )
            },
        )
        self.assertEqual(response.status_code, 403)
        self.assertIn("Somente a Vigilância Epidemiológica", response.json()["detail"])

    def test_surveillance_can_import_both_conditions(self) -> None:
        self._switch_role("vigilancia")
        for agravo in ("tuberculose", "hanseniase"):
            with self.subTest(agravo=agravo):
                page = self.client.get(f"/{agravo}")
                self.assertEqual(page.status_code, 200)
                self.assertIn('action="/api/boletins/analisar"', page.text)
                self.assertIn('type="file" name="boletim"', page.text)
                self.assertIn('href="/vigilancia"', page.text)
                response = self.client.post(
                    "/api/boletins/analisar",
                    data={
                        "csrf_token": self._form_csrf(f"/{agravo}"),
                        "agravo": agravo,
                    },
                    files={
                        "boletim": (
                            "boletim.pdf",
                            self.make_pdf(agravo=agravo),
                            "application/pdf",
                        )
                    },
                )
                self.assertEqual(response.status_code, 200)

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
        self.assertIn("As fichas importadas pela Vigilância ficam no painel de envio mensal", no_match.text)
        self.assertIn("Abrir painel de envio mensal", no_match.text)

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
            ("/admin/usuarios/{user_id}/senha", "POST"),
            ("/admin/usuarios/{user_id}/excluir", "POST"),
            ("/logout", "POST"),
            ("/api/acompanhamento/{agravo}/{record_id}", "POST"),
            ("/api/historico/{agravo}/{competence}", "GET"),
            ("/api/historico/{agravo}/{competence}/{patient_ref}/rascunho", "POST"),
            ("/api/historico/{agravo}/{competence}/{patient_ref}/enviar", "POST"),
            ("/api/vigilancia/competencias/{agravo}/{competence}/abrir", "POST"),
            ("/api/vigilancia/competencias/{agravo}/{competence}/encerrar", "POST"),
            ("/api/vigilancia/historico/{agravo}/{competence}/{patient_ref}/revisar", "POST"),
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

    def test_monthly_history_api_is_unit_scoped_and_preserves_previous_competence(self) -> None:
        patient_ref = "notificacao-ficticia-longa-001"
        import_monthly_records(
            agravo="tuberculose",
            competence="2026-10",
            source_content=b"october synthetic bulletin",
            imported_by="vigilancia",
            records=[
                {
                    "patient_ref": patient_ref,
                    "unit_ref": "Unidade de Saúde de Vera (demonstração)",
                    "values": {
                        "nome": "Paciente fictício",
                        "data_ultimo_comparecimento": "2026-10-18",
                    },
                },
                {
                    "patient_ref": "registro-ficticio-outra-unidade",
                    "unit_ref": "Unidade de Saúde Diferente (demonstração)",
                    "values": {"nome": "Outro paciente fictício"},
                },
                {
                    "patient_ref": "registro-anterior-a-conferir-ficticio",
                    "unit_ref": "Unidade de Saúde de Vera (demonstração)",
                    "values": {"nome": "Registro anterior fictício"},
                },
            ],
        )
        import_monthly_records(
            agravo="tuberculose",
            competence="2026-11",
            source_content=b"november synthetic bulletin",
            imported_by="vigilancia",
            records=[
                {
                    "patient_ref": patient_ref,
                    "unit_ref": "Unidade de Saúde de Vera (demonstração)",
                    "values": {"nome": "Paciente fictício"},
                },
                {
                    "patient_ref": "registro-ficticio-outra-unidade",
                    "unit_ref": "Unidade de Saúde Diferente (demonstração)",
                    "values": {"nome": "Outro paciente fictício"},
                },
            ],
        )

        history = self.client.get("/api/historico/tuberculose/2026-11")
        self.assertEqual(history.status_code, 200)
        self.assertEqual(history.json()["situacao_competencia"], "open")
        self.assertEqual(len(history.json()["registros"]), 1)
        record = history.json()["registros"][0]
        self.assertEqual(record["identificador"], patient_ref)
        self.assertEqual(
            record["competencia_anterior"]["data_ultimo_comparecimento"],
            "2026-10-18",
        )
        self.assertEqual(
            record["comparacao"]["data_ultimo_comparecimento"]["status"],
            "not_updated",
        )
        self.assertEqual(
            history.json()["registros_anteriores_ausentes_no_mes_atual"][0][
                "situacao"
            ],
            "ausente_no_boletim_atual_conferir",
        )
        self.assertTrue(
            history.json()["registros_anteriores_ausentes_no_mes_atual"][0][
                "nao_classificar_automaticamente"
            ]
        )

        save = self.client.post(
            f"/api/historico/tuberculose/2026-11/{patient_ref}/rascunho",
            data={
                "csrf_token": self._form_csrf(),
                "data_ultimo_comparecimento": "2026-11-07",
            },
        )
        self.assertEqual(save.status_code, 200)
        refreshed = self.client.get("/api/historico/tuberculose/2026-11").json()
        self.assertEqual(
            refreshed["registros"][0]["comparacao"]["data_ultimo_comparecimento"]["status"],
            "changed",
        )
        october = get_monthly_record(
            agravo="tuberculose",
            patient_ref=patient_ref,
            competence="2026-10",
        )
        self.assertEqual(october.values["data_ultimo_comparecimento"], "2026-10-18")

        wrong_unit = self.client.post(
            "/api/historico/tuberculose/2026-11/registro-ficticio-outra-unidade/rascunho",
            data={
                "csrf_token": self._form_csrf(),
                "data_ultimo_comparecimento": "2026-11-08",
            },
        )
        self.assertEqual(wrong_unit.status_code, 404)
        historical_edit = self.client.post(
            f"/api/historico/tuberculose/2026-10/{patient_ref}/rascunho",
            data={
                "csrf_token": self._form_csrf(),
                "data_ultimo_comparecimento": "2026-10-19",
            },
        )
        self.assertEqual(historical_edit.status_code, 422)

        self._switch_role("vigilancia")
        all_units = self.client.get("/api/historico/tuberculose/2026-11")
        self.assertEqual(all_units.status_code, 200)
        self.assertEqual(len(all_units.json()["registros"]), 2)

    def test_communication_dashboard_and_actions_enforce_unit_scope(self) -> None:
        import_monthly_records(
            agravo="tuberculose",
            competence="2026-11",
            source_content=b"synthetic-communication-prior",
            imported_by="vigilancia",
            records=[
                {
                    "patient_ref": "comunicacao-vera-ficticia",
                    "unit_ref": "Unidade de Saúde de Vera (demonstração)",
                    "values": {
                        "contatos_identificados": "3",
                        "contatos_examinados": "0",
                    },
                }
            ],
        )
        import_monthly_records(
            agravo="tuberculose",
            competence="2026-12",
            source_content=b"synthetic-communication-bulletin",
            imported_by="vigilancia",
            records=[
                {
                    "patient_ref": "comunicacao-vera-ficticia",
                    "unit_ref": "Unidade de Saúde de Vera (demonstração)",
                    "values": {
                        "contatos_identificados": "3",
                        "contatos_examinados": "1",
                    },
                },
                {
                    "patient_ref": "comunicacao-outra-ficticia",
                    "unit_ref": "Unidade de Saúde Diferente (demonstração)",
                    "values": {
                        "contatos_identificados": "5",
                        "contatos_examinados": "2",
                    },
                },
            ],
            unit_coverage=(
                "Unidade de Saúde de Vera (demonstração)",
                "Unidade de Saúde Diferente (demonstração)",
            ),
        )
        unit_page = self.client.get("/comunicacao")
        self.assertEqual(unit_page.status_code, 200)
        self.assertNotIn("comunicacao-vera-ficticia", unit_page.text)
        self.assertNotIn("comunicacao-outra-ficticia", unit_page.text)
        vera_followup = next(
            item for item in list_monthly_followups()
            if item.patient_ref == "comunicacao-vera-ficticia"
        )
        self.assertEqual(vera_followup.field_key, "contatos_examinados")
        self.assertEqual(
            len(list_monthly_followups(unit_ref="Unidade de Saúde de Vera (demonstração)")),
            1,
        )
        self.assertEqual(
            self.client.get(f"/comunicacao/{vera_followup.id}").status_code,
            404,
        )
        unauthorized_manual = self.client.post(
            "/comunicacao/manual",
            data={
                "csrf_token": self._form_csrf("/comunicacao"),
                "agravo": "tuberculose",
                "competence": "2026-12",
                "patient_ref": "comunicacao-vera-ficticia",
                "text": "Solicitação não permitida à unidade.",
                "priority": "normal",
            },
        )
        self.assertEqual(unauthorized_manual.status_code, 403)
        unauthorized_edit = self.client.post(
            f"/comunicacao/{vera_followup.id}/revisar",
            data={
                "csrf_token": self._form_csrf("/comunicacao"),
                "action": "save_note",
                "text": "A unidade não pode alterar esta orientação.",
                "priority": "normal",
            },
        )
        self.assertEqual(unauthorized_edit.status_code, 403)

        self._switch_role("vigilancia")
        dashboard = self.client.get("/comunicacao")
        self.assertEqual(dashboard.status_code, 200)
        self.assertIn("comunicacao-vera-ficticia", dashboard.text)
        self.assertIn("comunicacao-outra-ficticia", dashboard.text)
        self.assertIn("Nova solicitação da Vigilância", dashboard.text)
        other_followup = next(
            item for item in list_monthly_followups()
            if item.patient_ref == "comunicacao-outra-ficticia"
        )
        self.assertEqual(
            self.client.get(f"/comunicacao/{other_followup.id}").status_code,
            200,
        )
        csrf = self._form_csrf(f"/comunicacao/{vera_followup.id}")
        sent = self.client.post(
            f"/comunicacao/{vera_followup.id}/revisar",
            data={
                "csrf_token": csrf,
                "action": "send",
                "text": "Confirmar os contatos ainda não examinados.",
                "priority": "high",
            },
        )
        self.assertEqual(sent.status_code, 303)
        self.assertEqual(
            self.client.get(f"/comunicacao/{other_followup.id}").status_code,
            200,
        )
        manual = self.client.post(
            "/comunicacao/manual",
            data={
                "csrf_token": self._form_csrf("/comunicacao"),
                "agravo": "tuberculose",
                "competence": "2026-12",
                "patient_ref": "comunicacao-vera-ficticia",
                "text": "Conferir a informação importada.",
                "priority": "normal",
            },
        )
        self.assertEqual(manual.status_code, 303)
        manual_id = int(manual.headers["location"].rsplit("/", maxsplit=1)[-1])

        self._switch_role("vera")
        bulletin_page = self.client.get("/tuberculose")
        self.assertEqual(bulletin_page.status_code, 200)
        self.assertIn("Observações da Vigilância e resposta da unidade", bulletin_page.text)
        self.assertIn("Resposta / justificativa da unidade", bulletin_page.text)
        self.assertIn(
            f'action="/comunicacao/{vera_followup.id}/responder"',
            bulletin_page.text,
        )
        self.assertIn("Confirmar os contatos ainda não examinados.", bulletin_page.text)
        monthly_page = self.client.get(
            "/monitoramento-mensal?agravo=tuberculose&competence=2026-12"
        )
        self.assertEqual(monthly_page.status_code, 200)
        self.assertIn(
            f'action="/comunicacao/{vera_followup.id}/responder"',
            monthly_page.text,
        )
        self.assertIn("Resposta / justificativa", monthly_page.text)
        field_page = self.client.get(f"/comunicacao/{vera_followup.id}")
        self.assertEqual(field_page.status_code, 200)
        self.assertIn("Campo relacionado: Total de contatos examinados", field_page.text)
        self.assertIn("Competência anterior", field_page.text)
        self.assertIn(">0<", field_page.text)
        response = self.client.post(
            f"/comunicacao/{vera_followup.id}/responder",
            data={
                "csrf_token": self._form_csrf("/tuberculose"),
                "text": "Os contatos restantes foram agendados.",
                "submit": "submitted",
            },
        )
        self.assertEqual(response.status_code, 303)
        refreshed = get_monthly_followup(
            followup_id=vera_followup.id,
            unit_ref="Unidade de Saúde de Vera (demonstração)",
        )
        self.assertEqual(refreshed.state, "responded")
        self.assertEqual(refreshed.response_by, "vera")
        general_page = self.client.get(f"/comunicacao/{manual_id}")
        self.assertIn("Observações gerais da Vigilância", general_page.text)
        general_response = self.client.post(
            f"/comunicacao/{manual_id}/responder",
            data={
                "csrf_token": self._form_csrf(f"/comunicacao/{manual_id}"),
                "text": "A equipe verificará a informação.",
                "submit": "submitted",
            },
        )
        self.assertEqual(general_response.status_code, 303)
        self.assertEqual(
            get_monthly_record(
                agravo="tuberculose",
                patient_ref="comunicacao-vera-ficticia",
                competence="2026-12",
            ).values["contatos_examinados"],
            "1",
        )
        field_update = self.client.post(
            f"/comunicacao/{vera_followup.id}/atualizar-campo",
            data={
                "csrf_token": self._form_csrf(f"/comunicacao/{vera_followup.id}"),
                "contatos_examinados": "2",
            },
        )
        self.assertEqual(field_update.status_code, 303)
        self.assertEqual(
            get_monthly_record(
                agravo="tuberculose",
                patient_ref="comunicacao-vera-ficticia",
                competence="2026-12",
            ).values["contatos_examinados"],
            "2",
        )
        refreshed = get_monthly_followup(
            followup_id=vera_followup.id,
            unit_ref="Unidade de Saúde de Vera (demonstração)",
        )
        self.assertIn("Confirmar os contatos", refreshed.vigilance_text)
        self.assertIn("agendados", refreshed.response_text)

    def test_hanseniase_field_observation_uses_its_official_dictionary(self) -> None:
        import_monthly_records(
            agravo="hanseniase",
            competence="2026-11",
            source_content=b"synthetic-hans-monthly-field",
            imported_by="vigilancia",
            records=[
                {
                    "patient_ref": "hans-comunicacao-ficticia",
                    "unit_ref": "Unidade de Saúde de Vera (demonstração)",
                    "values": {"esquema_terapeutico": "1", "doses_supervisionadas": "4"},
                }
            ],
        )
        self._switch_role("vigilancia")
        manual = self.client.post(
            "/comunicacao/manual",
            data={
                "csrf_token": self._form_csrf("/comunicacao"),
                "agravo": "hanseniase",
                "competence": "2026-11",
                "patient_ref": "hans-comunicacao-ficticia",
                "field_key": "esquema_terapeutico",
                "text": "Conferir o esquema terapêutico atual.",
                "priority": "normal",
            },
        )
        self.assertEqual(manual.status_code, 303)
        followup_id = int(manual.headers["location"].rsplit("/", maxsplit=1)[-1])
        self._switch_role("vera")
        page = self.client.get(f"/comunicacao/{followup_id}")
        self.assertIn("esquema terapêutico atual (et)", page.text.lower())
        self.assertIn("PQT/PB/6 doses", page.text)
        update = self.client.post(
            f"/comunicacao/{followup_id}/atualizar-campo",
            data={
                "csrf_token": self._form_csrf(f"/comunicacao/{followup_id}"),
                "esquema_terapeutico": "2",
            },
        )
        self.assertEqual(update.status_code, 303)
        current = get_monthly_record(
            agravo="hanseniase",
            patient_ref="hans-comunicacao-ficticia",
            competence="2026-11",
        )
        self.assertEqual(
            current.values["esquema_terapeutico"],
            {"codigo": "2", "descricao": "PQT/MB/12 doses"},
        )

    def test_monthly_categorical_values_keep_code_and_description(self) -> None:
        patient_ref = "notificacao-ficticia-dicionario"
        for competence, source, code in (
            ("2026-10", b"dictionary-october", "3"),
            ("2026-11", b"dictionary-november", "3"),
        ):
            import_monthly_records(
                agravo="tuberculose",
                competence=competence,
                source_content=source,
                imported_by="vigilancia",
                records=[
                    {
                        "patient_ref": patient_ref,
                        "unit_ref": "Unidade de Saúde de Vera (demonstração)",
                        "values": {"histopatologia": code},
                    }
                ],
            )
        original = get_monthly_record(
            agravo="tuberculose",
            patient_ref=patient_ref,
            competence="2026-11",
        )
        self.assertEqual(
            original.original_values["histopatologia"],
            {
                "codigo": "3",
                "descricao": "Não sugestivo de TB",
                "valor_original": "3",
            },
        )

        saved = self.client.post(
            f"/api/historico/tuberculose/2026-11/{patient_ref}/rascunho",
            data={
                "csrf_token": self._form_csrf(),
                "histopatologia": "4",
            },
        )
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(
            saved.json()["valores_atualizados"]["histopatologia"],
            {"codigo": "4", "descricao": "Em andamento"},
        )
        record = self.client.get("/api/historico/tuberculose/2026-11").json()[
            "registros"
        ][0]
        self.assertEqual(record["comparacao"]["histopatologia"]["status"], "changed")

        for protected_field, value in (
            ("nome", "Nome fictício alterado"),
            ("numero_notificacao", "notificacao-alterada"),
            ("contatos_identificados", "99"),
        ):
            with self.subTest(field=protected_field):
                rejected = self.client.post(
                    f"/api/historico/tuberculose/2026-11/{patient_ref}/rascunho",
                    data={
                        "csrf_token": self._form_csrf(),
                        protected_field: value,
                    },
                )
                self.assertEqual(rejected.status_code, 422)

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

    def test_monthly_monitoring_is_unit_scoped_and_confirms_silence(self) -> None:
        vera_unit = "Unidade de Saúde de Vera (demonstração)"
        other_unit = "Unidade de Saúde Diferente (demonstração)"
        no_import = self.client.get(
            "/monitoramento-mensal?agravo=tuberculose&competence=2026-10"
        )
        self.assertEqual(no_import.status_code, 200)
        self.assertIn("o envio não é automático", no_import.text)
        self.assertIn("Nenhuma ficha mensal foi importada", no_import.text)
        import_monthly_records(
            agravo="tuberculose",
            competence="2026-11",
            source_content=b"boletim-vazio-com-cobertura-ficticia",
            imported_by="vigilancia",
            records=[],
            unit_coverage=(vera_unit, other_unit),
        )
        response = self.client.get(
            "/monitoramento-mensal?agravo=tuberculose&competence=2026-11"
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(vera_unit, response.text)
        self.assertNotIn(other_unit, response.text)
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', response.text).group(1)
        response = self.client.post(
            "/monitoramento-mensal/confirmar",
            data={
                "csrf_token": csrf,
                "agravo": "tuberculose",
                "competence": "2026-11",
                "action": "confirm_absence",
                "note": "",
            },
        )
        self.assertEqual(response.status_code, 303)
        confirmed = self.client.get(
            "/monitoramento-mensal?agravo=tuberculose&competence=2026-11"
        )
        self.assertIn("ausência confirmada", confirmed.text)

        self._switch_role("outra")
        other_view = self.client.get(
            "/monitoramento-mensal?agravo=tuberculose&competence=2026-11"
        )
        self.assertEqual(other_view.status_code, 200)
        self.assertIn(other_unit, other_view.text)
        self.assertNotIn(vera_unit, other_view.text)
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', other_view.text).group(1)
        forbidden = self.client.post(
            "/vigilancia/monitoramento-mensal/acao",
            data={
                "csrf_token": csrf,
                "agravo": "tuberculose",
                "competence": "2026-11",
                "unit_ref": vera_unit,
                "action": "confirm_absence",
                "note": "",
            },
        )
        self.assertEqual(forbidden.status_code, 403)

    def test_monthly_monitoring_displays_official_bulletin_field_names(self) -> None:
        unit = "Unidade de Saúde de Vera (demonstração)"
        other_unit = "Unidade de Saúde Diferente (demonstração)"
        patient_ref = "notificacao-ficticia-2026-001"
        import_monthly_records(
            agravo="tuberculose",
            competence="2026-10",
            source_content=b"boletim-anterior-outra-unidade",
            imported_by="vigilancia",
            records=[
                {
                    "patient_ref": patient_ref,
                    "unit_ref": other_unit,
                    "values": {
                        "data_ultimo_comparecimento": "2026-10-19",
                    },
                }
            ],
            unit_coverage=(other_unit,),
        )
        import_monthly_records(
            agravo="tuberculose",
            competence="2026-11",
            source_content=b"boletim-ficticio-campos-oficiais",
            imported_by="vigilancia",
            records=[
                {
                    "patient_ref": patient_ref,
                    "unit_ref": unit,
                    "values": {
                        "numero_notificacao": "notificacao-ficticia-2026-001",
                        "contatos_examinados": "0",
                    },
                }
            ],
            unit_coverage=(unit,),
        )
        response = self.client.get(
            "/monitoramento-mensal?agravo=tuberculose&competence=2026-11"
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("Nº da Notificação Atual", response.text)
        self.assertIn("Total de contatos examinados", response.text)
        self.assertIn("Campos oficiais e comparação mensal", response.text)
        self.assertIn("Competência anterior", response.text)
        self.assertIn("Competência atual", response.text)
        self.assertNotIn("Identificador fictício", response.text)
        self.assertIn(patient_ref, response.text)
        self.assertNotIn("2026-10-19", response.text)

        module_page = self.client.get("/tuberculose")
        self.assertEqual(module_page.status_code, 200)
        self.assertIn("Nº da Notificação Atual", module_page.text)
        self.assertNotIn("Identificador fictício", module_page.text)

    def test_monthly_bulletin_can_be_saved_submitted_and_corrected_after_return(self) -> None:
        unit = "Unidade de Saúde de Vera (demonstração)"
        patient_ref = "notificacao-ficticia-envio-001"
        import_monthly_records(
            agravo="tuberculose",
            competence="2026-11",
            source_content=b"boletim-ficticio-envio-retificacao",
            imported_by="vigilancia",
            records=[
                {
                    "patient_ref": patient_ref,
                    "unit_ref": unit,
                    "values": {"contatos_examinados": "0"},
                }
            ],
            unit_coverage=(unit,),
        )
        page = self.client.get(
            "/monitoramento-mensal?agravo=tuberculose&competence=2026-11"
        )
        self.assertEqual(page.status_code, 200)
        self.assertIn("Salvar rascunho", page.text)
        self.assertIn("Enviar atualização", page.text)
        update_url = (
            f"/monitoramento-mensal/tuberculose/2026-11/"
            f"{patient_ref}/atualizar"
        )
        draft = self.client.post(
            update_url,
            data={
                "csrf_token": self._form_csrf("/monitoramento-mensal"),
                "action": "draft",
                "contatos_examinados": "1",
            },
            follow_redirects=False,
        )
        self.assertEqual(draft.status_code, 303)
        self.assertIn("saved=draft", draft.headers["location"])
        self.assertEqual(
            get_monthly_record(
                agravo="tuberculose",
                patient_ref=patient_ref,
                competence="2026-11",
            ).state,
            "draft",
        )
        submitted = self.client.post(
            update_url,
            data={
                "csrf_token": self._form_csrf("/monitoramento-mensal"),
                "action": "submit",
                "contatos_examinados": "1",
            },
            follow_redirects=False,
        )
        self.assertEqual(submitted.status_code, 303)
        self.assertIn("saved=submitted", submitted.headers["location"])
        record = get_monthly_record(
            agravo="tuberculose",
            patient_ref=patient_ref,
            competence="2026-11",
        )
        self.assertEqual(record.state, "submitted")
        self.assertEqual(record.values["contatos_examinados"], "1")

        locked_page = self.client.get(
            "/monitoramento-mensal?agravo=tuberculose&competence=2026-11"
        )
        self.assertIn("solicite à Vigilância que a devolva para correção", locked_page.text)
        self.assertNotIn(
            f'action="{update_url}"',
            locked_page.text,
        )
        self._switch_role("vigilancia")
        returned = self.client.post(
            f"/api/vigilancia/historico/tuberculose/2026-11/{patient_ref}/revisar",
            data={
                "csrf_token": self._form_csrf("/comunicacao"),
                "approved": "false",
                "note": "Corrigir valor fictício para conferência.",
            },
        )
        self.assertEqual(returned.status_code, 200)
        self.assertEqual(returned.json()["situacao"], "returned")

        self._switch_role("vera")
        correction_page = self.client.get(
            "/monitoramento-mensal?agravo=tuberculose&competence=2026-11"
        )
        self.assertIn("Corrija os campos indicados e envie novamente", correction_page.text)
        corrected = self.client.post(
            update_url,
            data={
                "csrf_token": self._form_csrf("/monitoramento-mensal"),
                "action": "submit",
                "contatos_examinados": "2",
            },
            follow_redirects=False,
        )
        self.assertEqual(corrected.status_code, 303)
        final_record = get_monthly_record(
            agravo="tuberculose",
            patient_ref=patient_ref,
            competence="2026-11",
        )
        self.assertEqual(final_record.state, "submitted")
        self.assertEqual(final_record.values["contatos_examinados"], "2")

    def test_only_surveillance_can_set_deadlines_and_review_silence(self) -> None:
        unit = "Unidade de Saúde de Vera (demonstração)"
        import_monthly_records(
            agravo="hanseniase",
            competence="2026-12",
            source_content=b"boletim-han-vazio-com-cobertura",
            imported_by="vigilancia",
            records=[],
            unit_coverage=(unit,),
        )
        page = self.client.get(
            "/monitoramento-mensal?agravo=hanseniase&competence=2026-12"
        )
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
        denied = self.client.post(
            "/monitoramento-mensal/prazo",
            data={
                "csrf_token": csrf,
                "agravo": "hanseniase",
                "competence": "2026-12",
                "opened_on": "2026-12-01",
                "due_on": "2026-12-10",
                "extension_due_on": "",
            },
        )
        self.assertEqual(denied.status_code, 403)
        self._switch_role("vigilancia")
        page = self.client.get(
            "/monitoramento-mensal?agravo=hanseniase&competence=2026-12"
        )
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
        saved = self.client.post(
            "/monitoramento-mensal/prazo",
            data={
                "csrf_token": csrf,
                "agravo": "hanseniase",
                "competence": "2026-12",
                "opened_on": "2026-12-01",
                "due_on": "2026-12-10",
                "extension_due_on": "2026-12-20",
            },
        )
        self.assertEqual(saved.status_code, 303)
        updated_page = self.client.get(
            "/monitoramento-mensal?agravo=hanseniase&competence=2026-12"
        )
        self.assertIn('value="2026-12-20"', updated_page.text)
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', updated_page.text).group(1)
        unknown_unit = self.client.post(
            "/vigilancia/monitoramento-mensal/acao",
            data={
                "csrf_token": csrf,
                "agravo": "hanseniase",
                "competence": "2026-12",
                "unit_ref": "Unidade inexistente",
                "action": "confirm_absence",
                "note": "",
            },
        )
        self.assertEqual(unknown_unit.status_code, 404)

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
        self._switch_role("vigilancia")
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
    def make_pdf(
        multirow_header: bool = False,
        agravo: str = "tuberculose",
    ) -> bytes:
        document = pymupdf.open()
        page = document.new_page()
        title = "Tuberculose" if agravo == "tuberculose" else "Hanseníase"
        page.insert_text((50, 50), f"Boletim de Acompanhamento de {title}")
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
