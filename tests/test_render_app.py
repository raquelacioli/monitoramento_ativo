from unittest.mock import patch
from fastapi.testclient import TestClient
from google.api_core.exceptions import ServiceUnavailable
from firestore_support import FirestoreTestCase
from main import app


class RenderAppTests(FirestoreTestCase):
    def test_health_checks_firestore_and_app_opens_in_browser(self):
        with TestClient(app) as client:
            self.assertEqual(client.get('/healthz').status_code, 200)
            self.assertEqual(client.get('/').status_code, 200)
            self.assertEqual(client.get('/login').status_code, 200)

    def test_database_failure_returns_sanitized_503(self):
        client = TestClient(app)
        self.addCleanup(client.close)
        with patch('main.get_store', side_effect=ServiceUnavailable('private diagnostic')):
            response = client.get('/healthz')
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('private diagnostic', response.text)
