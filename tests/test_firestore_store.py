import os
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from firestore_support import FirestoreTestCase


class StoreTests(FirestoreTestCase):
    def test_atomic_rollback_and_read_your_writes(self):
        from monitoramento.firestore_store import get_store, key
        store = get_store()
        def failed(tx):
            tx.set('checks', key('a'), {'value': 1})
            self.assertEqual(tx.get('checks', key('a'))['value'], 1)
            self.assertEqual(len(tx.query('checks', [('value', '==', 1)])), 1)
            raise ValueError('abort')
        with self.assertRaises(ValueError):
            store.run(failed)
        self.assertIsNone(store.get('checks', key('a')))

    def test_concurrent_counter_is_unique(self):
        from monitoramento.firestore_store import get_store
        store = get_store()
        with ThreadPoolExecutor(max_workers=4) as pool:
            ids = list(pool.map(lambda _: store.run(lambda tx: tx.next_id('test')), range(8)))
        self.assertEqual(sorted(ids), list(range(1, 9)))

    def test_namespace_isolation(self):
        from monitoramento.firestore_store import get_store, key
        get_store().run(lambda tx: tx.set('checks', key('a'), {'value': 2}))
        with patch.dict(os.environ, {'FIRESTORE_NAMESPACE': 'test_other'}):
            self.assertIsNone(get_store().get('checks', key('a')))

    def test_reject_remote_emulator_and_wrong_project(self):
        from monitoramento.firestore_store import get_store
        for change in ({'FIRESTORE_EMULATOR_HOST': 'remote.invalid:8085'},
                       {'FIREBASE_PROJECT_ID': 'monitoramentoativo'},
                       {'APP_ENV': 'production'}):
            with patch.dict(os.environ, change), self.assertRaises(ValueError):
                get_store()
