"""Run all tests against the local, anonymous Firestore emulator only."""
import os
from pathlib import Path
import socket
import subprocess
import sys


def main():
    root = Path(__file__).resolve().parent.parent
    try:
        with socket.create_connection(('127.0.0.1', 8085), timeout=2): pass
    except OSError:
        raise SystemExit('Inicie o emulador Firestore fictício em 127.0.0.1:8085 primeiro.') from None
    env = os.environ.copy()
    env.pop('GOOGLE_APPLICATION_CREDENTIALS', None)
    env.update(FIRESTORE_EMULATOR_HOST='127.0.0.1:8085',
               FIREBASE_PROJECT_ID='demo-monitoramento-ativo', FIRESTORE_DATABASE_ID='(default)',
               FIRESTORE_NAMESPACE='test_runner', APP_ENV='test',
               MONITORAMENTO_DB_PATH=':memory:', MONITORAMENTO_COOKIE_SECURE='0')
    temporary = root / '.test-tmp'
    temporary.mkdir(exist_ok=True)
    env.update(TEMP=str(temporary), TMP=str(temporary))
    return subprocess.call([sys.executable, '-B', '-m', 'unittest', 'discover', '-s', 'tests', '-q'],
                           cwd=root, env=env)


if __name__ == '__main__': sys.exit(main())
