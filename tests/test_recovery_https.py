import json
import os
import unittest
from unittest.mock import patch, MagicMock
from monitoramento.recovery_mail import send_password_reset_email, RecoveryMailConfigurationError


class HttpsRecoveryTests(unittest.TestCase):
    def test_resend_uses_https_and_configured_origin_without_logging_secret(self):
        response = MagicMock()
        response.__enter__.return_value.status = 200
        env = {'RECOVERY_EMAIL_PROVIDER': 'resend', 'RESEND_API_KEY': 'fictitious-test-key',
               'RECOVERY_EMAIL_FROM': 'noreply@example.test',
               'APP_BASE_URL': 'https://monitoramento.example.test'}
        with patch.dict(os.environ, env), patch('urllib.request.urlopen', return_value=response) as send:
            send_password_reset_email('ficticio@example.test', 'fictitious-token')
        request = send.call_args.args[0]
        self.assertEqual(request.full_url, 'https://api.resend.com/emails')
        payload = json.loads(request.data)
        self.assertIn('https://monitoramento.example.test/redefinir-senha#token=fictitious-token', payload['text'])
        self.assertNotIn('fictitious-test-key', payload['text'])

    def test_provider_failure_is_sanitized(self):
        env = {'RECOVERY_EMAIL_PROVIDER': 'resend', 'RESEND_API_KEY': 'fictitious-test-key',
               'RECOVERY_EMAIL_FROM': 'noreply@example.test', 'APP_BASE_URL': 'https://example.test'}
        with patch.dict(os.environ, env), patch('urllib.request.urlopen', side_effect=OSError('secret response')):
            with self.assertRaises(RecoveryMailConfigurationError) as error:
                send_password_reset_email('ficticio@example.test', 'fictitious-token')
        self.assertNotIn('secret response', str(error.exception))
