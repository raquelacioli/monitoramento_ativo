from firestore_support import FirestoreTestCase
from monitoramento.data import MODULES
from monitoramento.tracking_store import save_tracking_update, load_module_updates


class TrackingTests(FirestoreTestCase):
    def test_observation_and_alert_persist_without_sqlite(self):
        module = MODULES['tuberculose']
        patient = module.patients[0]
        save_tracking_update(agravo=module.key, record_id=patient.identifier,
            followup_status='Sinalização para revisão', contacts_registered=3,
            contacts_examined=1, pending_items='Conferência fictícia',
            observation='Observação fictícia da unidade', form_values={'campo': 'fictício'})
        loaded = load_module_updates(module).patients[0]
        self.assertEqual(loaded.observation, 'Observação fictícia da unidade')
        self.assertTrue(loaded.review_signal_demo)
        self.assertEqual(loaded.contacts_examined, 1)
