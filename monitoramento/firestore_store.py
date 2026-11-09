"""Server-side Firestore access. No SQLite fallback and no client credentials."""
import copy
import hashlib
import json
import os
import re
import threading
from functools import lru_cache, wraps
from contextvars import ContextVar

from google.auth.credentials import AnonymousCredentials
from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter
from google.oauth2 import service_account


class MigrationPendingError(ValueError):
    """The destination is not yet available to the application."""


_snapshot = ContextVar('firestore_read_snapshot', default=None)


def snapshot_read(function):
    @wraps(function)
    def read(*args, **kwargs):
        if _snapshot.get() is not None:
            return function(*args, **kwargs)
        store = get_store()
        def call(reader):
            token = _snapshot.set(reader)
            try: return function(*args, **kwargs)
            finally: _snapshot.reset(token)
        return store.read(call)
    return read


def key(*parts) -> str:
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False, separators=(',', ':'),
                                     default=str).encode()).hexdigest()


def _matches(data, filters):
    for field, op, value in filters:
        actual = data.get(field)
        if op == '==' and actual != value: return False
        if op == '!=' and actual == value: return False
        if op == 'in' and actual not in value: return False
        if op == 'not-in' and actual in value: return False
        if op in ('<', '<=', '>', '>='):
            if actual is None: return False
            if op == '<' and not actual < value: return False
            if op == '<=' and not actual <= value: return False
            if op == '>' and not actual > value: return False
            if op == '>=' and not actual >= value: return False
        if op not in ('==', '!=', 'in', 'not-in', '<', '<=', '>', '>='):
            raise ValueError('Operador de consulta não suportado.')
    return True


class UnitOfWork:
    """Buffer writes so callbacks may read their own writes before SDK flush."""
    def __init__(self, store, transaction):
        self.store, self.transaction = store, transaction
        self.pending = {}
        self.cache = {}

    def get(self, collection, document_key):
        address = (collection, str(document_key))
        if address in self.pending:
            return copy.deepcopy(self.pending[address])
        if address not in self.cache:
            snap = self.store.ref(*address).get(transaction=self.transaction)
            self.cache[address] = snap.to_dict() if snap.exists else None
        return copy.deepcopy(self.cache[address])

    def query(self, collection, filters=()):
        rows = {}
        for snap in self.store._query(collection, filters).stream(transaction=self.transaction):
            data = snap.to_dict()
            self.cache[(collection, snap.id)] = data
            rows[snap.id] = data
        for (name, doc_id), data in self.pending.items():
            if name != collection: continue
            if data is not None and _matches(data, filters): rows[doc_id] = data
            else: rows.pop(doc_id, None)
        return copy.deepcopy(list(rows.values()))

    def set(self, collection, document_key, data):
        self.pending[(collection, str(document_key))] = copy.deepcopy(data)

    def delete(self, collection, document_key):
        self.pending[(collection, str(document_key))] = None

    def next_id(self, name):
        doc_id = key(name)
        current = self.get('_counters', doc_id) or {'value': 0}
        current['value'] += 1
        self.set('_counters', doc_id, current)
        return current['value']

    def flush(self):
        if len(self.pending) > 450:
            raise ValueError('Operação excedeu o limite seguro de documentos por transação.')
        for (collection, doc_id), data in self.pending.items():
            ref = self.store.ref(collection, doc_id)
            if data is None: self.transaction.delete(ref)
            else: self.transaction.set(ref, data)


class Store:
    def __init__(self, client, namespace):
        self.client, self.namespace = client, namespace
        self._lock = threading.RLock()

    def ref(self, collection, document_key):
        if not re.fullmatch(r'[A-Za-z0-9_]+', collection):
            raise ValueError('Coleção inválida.')
        return self.client.collection('monitoramento_ativo').document(self.namespace).collection(
            collection).document(str(document_key))

    def _query(self, collection, filters):
        query = self.ref(collection, '_').parent
        for field, op, value in filters:
            query = query.where(filter=FieldFilter(field, op, value))
        return query

    def _get_unchecked(self, collection, document_key):
        snap = self.ref(collection, document_key).get(timeout=15)
        return snap.to_dict() if snap.exists else None

    def _check_readable(self):
        migration = self._get_unchecked('_migration', key('state'))
        if migration and migration.get('status') != 'complete':
            raise MigrationPendingError('Namespace em migração; publicação ainda não concluída.')

    def get(self, collection, document_key):
        if collection != '_migration': self._check_readable()
        return self._get_unchecked(collection, document_key)

    def query(self, collection, filters=()):
        self._check_readable()
        return [snap.to_dict() for snap in self._query(collection, filters).stream(timeout=30)]

    def run(self, callback, guard='domain'):
        @firestore.transactional
        def execute(transaction):
            tx = UnitOfWork(self, transaction)
            admission_id = key('__namespace__')
            admission_version = (tx.get('_guards', admission_id) or {}).get('version', 0)
            guard_id = key(guard)
            version = (tx.get('_guards', guard_id) or {}).get('version', 0)
            migration = tx.get('_migration', key('state'))
            if migration and migration.get('status') != 'complete' and guard != 'migration':
                raise MigrationPendingError('Namespace em migração; publicação ainda não concluída.')
            result = callback(tx)
            # Every domain conflicts with migration admission across processes.
            tx.set('_guards', admission_id, {'version': admission_version + 1})
            tx.set('_guards', guard_id, {'version': version + 1})
            tx.flush()
            return result
        # Avoid needless SDK retries between threads of the single Render worker.
        # The Firestore transaction/guard remains authoritative across processes.
        with self._lock:
            return execute(self.client.transaction(max_attempts=10))

    def read(self, callback):
        @firestore.transactional
        def execute(transaction):
            reader = UnitOfWork(self, transaction)
            state = reader.get('_migration', key('state'))
            if state and state.get('status') != 'complete':
                raise MigrationPendingError('Namespace em migração; publicação ainda não concluída.')
            result = callback(reader)
            if reader.pending:
                raise ValueError('Snapshot de leitura não permite alterações.')
            return result
        return execute(self.client.transaction(read_only=True))


@lru_cache(maxsize=16)
def _configured_store(project, database, namespace, emulator, credential_path, app_env):
    if database != '(default)':
        raise ValueError('Este aplicativo utiliza somente o banco Firestore (default).')
    if not re.fullmatch(r'(monitoramento_ativo(?:_[a-zA-Z0-9_]+)?|test_[a-zA-Z0-9_]+)', namespace):
        raise ValueError('Namespace Firestore inválido ou fora do Monitoramento Ativo.')
    if emulator:
        if (emulator not in ('127.0.0.1:8085', 'localhost:8085')
                or project != 'demo-monitoramento-ativo' or app_env != 'test'):
            raise ValueError('Emulador permitido apenas em testes locais com projeto fictício.')
        credentials = AnonymousCredentials()
    else:
        if project != 'monitoramentoativo' or namespace.startswith('test_'):
            raise ValueError('Projeto Firestore de produção inválido.')
        if not credential_path:
            raise ValueError('Configure GOOGLE_APPLICATION_CREDENTIALS com um Secret File.')
        try:
            credentials = service_account.Credentials.from_service_account_file(credential_path)
            if credentials.project_id != project:
                raise ValueError('wrong project')
        except Exception:
            raise ValueError('Arquivo de credenciais inválido ou de outro projeto.') from None
    client = firestore.Client(project=project, database=database, credentials=credentials)
    return Store(client, namespace)


def get_store():
    if _snapshot.get() is not None:
        return _snapshot.get()
    return _configured_store(
        os.environ.get('FIREBASE_PROJECT_ID', ''),
        os.environ.get('FIRESTORE_DATABASE_ID', '(default)'),
        os.environ.get('FIRESTORE_NAMESPACE', 'monitoramento_ativo'),
        os.environ.get('FIRESTORE_EMULATOR_HOST', ''),
        os.environ.get('GOOGLE_APPLICATION_CREDENTIALS', ''),
        os.environ.get('APP_ENV', 'production'),
    )
