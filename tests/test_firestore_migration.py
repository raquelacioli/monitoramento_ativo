import hashlib
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
from firestore_support import FirestoreTestCase
from monitoramento.firestore_store import get_store, key
from monitoramento.auth import _password_hash, authenticate, create_user


class MigrationTests(FirestoreTestCase):
    def setUp(self):
        super().setUp()
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.source = Path(self.temporary.name) / 'ficticio.sqlite3'
        salt = b'0123456789abcdef'
        with closing(sqlite3.connect(self.source)) as c, c:
            c.execute('CREATE TABLE auth_users (id INTEGER PRIMARY KEY, username TEXT, role TEXT, '
                      'unit TEXT, password_hash BLOB, password_salt BLOB, active INTEGER, '
                      'must_change_password INTEGER, created_at INTEGER)')
            c.execute('INSERT INTO auth_users VALUES (?,?,?,?,?,?,?,?,?)',
                      (7, 'migrado-ficticio', 'admin', None,
                       _password_hash('SenhaFicticia#2026', salt), salt, 1, 0, 1))
        self.original = hashlib.sha256(self.source.read_bytes()).digest()

    def test_dry_run_has_no_writes_and_preserves_sqlite(self):
        from monitoramento.migrate_sqlite import migrate
        report = migrate(self.source)
        self.assertEqual(report['counts']['auth_users'], 1)
        self.assertEqual(get_store().query('auth_users'), [])
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).digest(), self.original)

    def test_apply_preserves_login_ids_and_is_idempotent(self):
        from monitoramento.migrate_sqlite import migrate
        result = migrate(self.source, apply=True)
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(authenticate('migrado-ficticio', 'SenhaFicticia#2026').id, 7)
        self.assertEqual(migrate(self.source, apply=True)['status'], 'complete')
        user = create_user('novo-ficticio', 'SenhaFicticia#2026', 'unit', 'Unidade fictícia')
        self.assertEqual(user.id, 8)
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).digest(), self.original)

    def test_rejects_nonempty_destination_and_orphan_reference(self):
        from monitoramento.migrate_sqlite import migrate
        create_user('existente', 'SenhaFicticia#2026', 'unit', 'Unidade fictícia')
        with self.assertRaises(ValueError): migrate(self.source, apply=True)
        with closing(sqlite3.connect(self.source)) as c, c:
            c.execute('CREATE TABLE monthly_records (agravo TEXT, patient_ref TEXT, competence TEXT, import_id INTEGER)')
            c.execute("INSERT INTO monthly_records VALUES ('tuberculose','ficticio','2026-11',999)")
        with self.assertRaises(ValueError): migrate(self.source)

    def test_rejects_missing_password_schema_before_any_write(self):
        from monitoramento.migrate_sqlite import migrate
        with closing(sqlite3.connect(self.source)) as c, c:
            c.execute('DROP TABLE auth_users')
            c.execute('CREATE TABLE auth_users (id INTEGER, username TEXT, role TEXT)')
            c.execute("INSERT INTO auth_users VALUES (7, 'ficticio', 'admin')")
        with self.assertRaises(ValueError): migrate(self.source, apply=True)
        self.assertEqual(get_store().query('auth_users'), [])

    def test_rejects_invalid_password_hash_and_empty_source(self):
        from monitoramento.migrate_sqlite import migrate
        with closing(sqlite3.connect(self.source)) as c, c:
            c.execute("UPDATE auth_users SET password_hash=X'00'")
        with self.assertRaises(ValueError): migrate(self.source)
        with closing(sqlite3.connect(self.source)) as c, c:
            c.execute('DELETE FROM auth_users')
        with self.assertRaises(ValueError): migrate(self.source)

