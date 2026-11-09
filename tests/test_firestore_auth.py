from concurrent.futures import ThreadPoolExecutor
from firestore_support import FirestoreTestCase
from monitoramento import auth


class FirestoreAuthTests(FirestoreTestCase):
    def test_firestore_persists_login_and_revokes_on_password_change(self):
        from monitoramento.firestore_store import get_store, key
        user = auth.create_first_admin('admin-ficticio', 'SenhaFicticia#2026')
        self.assertEqual(get_store().get('auth_users', key(user.id))['username'], user.username)
        token, csrf = auth.create_session(user.id)
        self.assertEqual(auth.get_session(token)[0].id, user.id)
        self.assertTrue(auth.validate_csrf(csrf, csrf))
        auth.change_password(user.id, 'NovaSenhaFicticia#2026')
        self.assertIsNone(auth.get_session(token))
        self.assertIsNone(auth.authenticate(user.username, 'SenhaFicticia#2026'))
        self.assertIsNotNone(auth.authenticate(user.username, 'NovaSenhaFicticia#2026'))

    def test_concurrent_username_and_first_admin_uniqueness(self):
        def create(_):
            try:
                return auth.create_first_admin('admin-ficticio', 'SenhaFicticia#2026')
            except ValueError:
                return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sum(u is not None for u in pool.map(create, range(2))), 1)

    def test_reset_token_is_consumed_once_and_email_change_invalidates_it(self):
        user = auth.create_user('unidade-ficticia', 'SenhaFicticia#2026', 'unit',
                                'Unidade fictícia', 'ficticio@example.test')
        token, _ = auth.issue_password_reset_token(user.email, '192.0.2.10')
        auth.set_user_recovery_email(user.id, 'novo@example.test')
        self.assertFalse(auth.reset_password_with_token(token, 'NovaSenhaFicticia#2026'))
        token, _ = auth.issue_password_reset_token('novo@example.test', '192.0.2.10')
        def reset(_):
            return auth.reset_password_with_token(token, 'NovaSenhaFicticia#2026')
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(list(pool.map(reset, range(2))).count(True), 1)

    def test_last_admin_and_deactivation(self):
        admin = auth.create_first_admin('admin-ficticio', 'SenhaFicticia#2026')
        unit = auth.create_user('unidade-ficticia', 'SenhaFicticia#2026', 'unit', 'Unidade fictícia')
        with self.assertRaises(ValueError):
            auth.delete_user(admin.id, unit.id)
        session, _ = auth.create_session(unit.id)
        auth.deactivate_user(unit.id, admin.id)
        self.assertIsNone(auth.get_session(session))
