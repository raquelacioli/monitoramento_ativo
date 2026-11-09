"""Integration fixtures: never use production credentials or a remote database."""
import os
import unittest
import uuid
from unittest.mock import patch


class FirestoreTestCase(unittest.TestCase):
    def setUp(self):
        host = os.environ.get('FIRESTORE_EMULATOR_HOST', '')
        if host not in ('127.0.0.1:8085', 'localhost:8085'):
            raise RuntimeError('Execute os testes com o emulador local em 127.0.0.1:8085.')
        self._env = patch.dict(os.environ, {
            'FIREBASE_PROJECT_ID': 'demo-monitoramento-ativo',
            'FIRESTORE_DATABASE_ID': '(default)',
            'FIRESTORE_NAMESPACE': 'test_' + uuid.uuid4().hex,
            'APP_ENV': 'test',
            'MONITORAMENTO_DB_PATH': ':memory:',
            'RECOVERY_EMAIL_PROVIDER': 'smtp',
        })
        self._env.start()
        self.addCleanup(self._env.stop)

