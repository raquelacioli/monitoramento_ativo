"""Monthly workflows against the isolated local Firestore emulator."""
from datetime import date
from concurrent.futures import ThreadPoolExecutor
import threading
from unittest.mock import patch

from firestore_support import FirestoreTestCase
from monitoramento import monthly_store as monthly


class FirestoreMonthlyTests(FirestoreTestCase):
    def seed(self, *, competence="2026-11", records=None, source=b"fictitious"):
        return monthly.import_monthly_records(
            agravo="tuberculose", competence=competence, source_content=source,
            imported_by="vigilancia-ficticia",
            records=records if records is not None else [
                {"patient_ref": "fake-1", "unit_ref": "Unidade ficticia",
                 "values": {"contatos_identificados": "4", "contatos_examinados": "1"}}],
            unit_coverage=("Unidade ficticia",))

    def test_native_document_import_and_monthly_history(self):
        self.seed()
        record = monthly.get_monthly_record(agravo="tuberculose", patient_ref="fake-1", competence="2026-11")
        self.assertEqual(record.state, "draft")
        monthly.update_monthly_draft(agravo="tuberculose", patient_ref="fake-1", competence="2026-11",
            unit_ref="Unidade ficticia", actor="unidade", values={"observacao": "Ficticia"})
        monthly.submit_monthly_record(agravo="tuberculose", patient_ref="fake-1", competence="2026-11",
            unit_ref="Unidade ficticia", actor="unidade")
        monthly.review_monthly_record(agravo="tuberculose", patient_ref="fake-1", competence="2026-11",
            actor="vigilancia", approved=True, note="Conferido ficticio")
        revisions = monthly.get_record_revisions(agravo="tuberculose", patient_ref="fake-1", competence="2026-11")
        self.assertEqual([r["action"] for r in revisions], ["imported", "draft_saved", "submitted", "validated"])
        self.assertEqual(monthly.monthly_unit_monitoring(agravo="tuberculose", competence="2026-11",
            units=("Unidade ficticia",), as_of=date(2026,11,30))[0]["situation"], "complete")

    def test_import_failure_is_invisible_and_retry_resumes(self):
        records=[{"patient_ref": f"fake-{i}", "unit_ref": "Unidade ficticia", "values": {}} for i in range(240)]
        original = monthly._stage_import_batch
        calls = 0
        def fail_second(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("synthetic batch failure")
            return original(*args, **kwargs)
        with patch.object(monthly, "_stage_import_batch", side_effect=fail_second):
            with self.assertRaisesRegex(RuntimeError,"synthetic"):
                self.seed(records=records)
        self.assertEqual(monthly.list_monthly_records(agravo="tuberculose", competence="2026-11"), ())
        result=self.seed(records=records)
        self.assertEqual(result["inserted"],240)
        self.assertEqual(len(monthly.list_monthly_records(agravo="tuberculose", competence="2026-11")),240)
        self.assertTrue(self.seed(records=records)["duplicate"])

    def test_followup_visibility_response_audit_and_isolation(self):
        self.seed()
        record=monthly.get_monthly_record(agravo="tuberculose",patient_ref="fake-1",competence="2026-11")
        suggestion=monthly.ensure_contact_followup(record)
        self.assertIsNone(monthly.get_monthly_followup(followup_id=suggestion.id, unit_ref="Unidade ficticia"))
        monthly.review_monthly_followup(followup_id=suggestion.id,actor="vig",action="send",text="Conferir ficticio")
        with self.assertRaises(PermissionError):
            monthly.save_monthly_followup_response(followup_id=suggestion.id,unit_ref="Outra",actor="u",text="Resposta",submit=True)
        monthly.save_monthly_followup_response(followup_id=suggestion.id,unit_ref="Unidade ficticia",actor="u",text="Resposta ficticia",submit=True)
        self.assertEqual(monthly.monthly_followup_metrics()["respostas_enviadas"],1)
        self.assertEqual([h["kind"] for h in monthly.get_monthly_followup_history(suggestion.id)],
                         ["event","event","event","response"])

    def test_thousand_records_publish_together_and_reimport_preserves_updates(self):
        records=[{"patient_ref": f"fake-{i:04d}", "unit_ref": "Unidade ficticia", "values": {}} for i in range(1000)]
        self.assertEqual(self.seed(records=records)["inserted"],1000)
        monthly.update_monthly_draft(agravo="tuberculose",patient_ref="fake-0000",competence="2026-11",
            unit_ref="Unidade ficticia",actor="unidade",values={"observacao":"Preservar"})
        records[0]["values"]={"campo":"alterado"}
        self.assertEqual(self.seed(records=records,source=b"different-source")["conflicts"],1)
        record=monthly.get_monthly_record(agravo="tuberculose",patient_ref="fake-0000",competence="2026-11")
        self.assertEqual(record.updated_values["observacao"],"Preservar")
        self.assertNotIn("campo",record.original_values)

    def test_pending_import_blocks_other_monthly_mutations(self):
        self.seed()
        original=monthly._stage_import_batch
        with patch.object(monthly,"_stage_import_batch",side_effect=RuntimeError("synthetic")):
            with self.assertRaises(RuntimeError):
                self.seed(competence="2026-12",source=b"december")
        with self.assertRaisesRegex(ValueError,"pendente"):
            monthly.update_monthly_draft(agravo="tuberculose",patient_ref="fake-1",competence="2026-11",
                unit_ref="Unidade ficticia",actor="u",values={"observacao":"blocked"})
        self.assertEqual(monthly.get_monthly_competence_state(agravo="tuberculose",competence="2026-11"),"open")
        self.assertEqual(len(monthly.list_monthly_records(agravo="tuberculose",competence="2026-11")),1)
        self.seed(competence="2026-12",source=b"december")
        self.assertEqual(monthly.get_monthly_competence_state(agravo="tuberculose",competence="2026-11"),"closed")

    def test_concurrent_same_source_publishes_and_counts_once(self):
        records=[{"patient_ref":f"concurrent-{i}","unit_ref":"Unidade ficticia","values":{}} for i in range(180)]
        barrier=threading.Barrier(2)
        original=monthly._stage_import_batch
        def interleaved(import_id, items, coverage, index):
            if index==0:
                barrier.wait(timeout=10)
            return original(import_id,items,coverage,index)
        with patch.object(monthly,"_stage_import_batch",side_effect=interleaved):
            with ThreadPoolExecutor(max_workers=2) as pool:
                results=list(pool.map(lambda _:self.seed(records=records),range(2)))
        self.assertEqual(sum(r["inserted"] for r in results),180)
        self.assertEqual(sum(r["duplicate"] for r in results),1)
        self.assertEqual(len(monthly.list_monthly_records(agravo="tuberculose",competence="2026-11")),180)

    def test_failed_import_requires_same_parsed_input_on_resume(self):
        with patch.object(monthly,"_stage_import_batch",side_effect=RuntimeError("synthetic")):
            with self.assertRaises(RuntimeError):
                self.seed()
        with self.assertRaisesRegex(ValueError,"mesmo boletim"):
            self.seed(records=[{"patient_ref":"different","unit_ref":"Unidade ficticia","values":{}}])
        self.seed()

    def test_retry_after_publication_lost_response_is_duplicate(self):
        store=monthly.get_store()
        original=store.run
        failed=False
        def disconnect_after_publish(callback, guard="domain"):
            nonlocal failed
            result=original(callback,guard=guard)
            if callback.__name__=="publish" and not failed:
                failed=True
                raise ConnectionError("synthetic lost response")
            return result
        with patch.object(store,"run",side_effect=disconnect_after_publish):
            with self.assertRaises(ConnectionError):
                self.seed()
        self.assertTrue(self.seed()["duplicate"])
        self.assertEqual(len(monthly.list_monthly_records(agravo="tuberculose",competence="2026-11")),1)

    def test_monthly_writes_require_auditable_actor(self):
        self.seed()
        with self.assertRaisesRegex(ValueError,"responsável"):
            monthly.create_manual_followup(agravo="tuberculose",competence="2026-11",patient_ref="fake-1",
                unit_ref="Unidade ficticia",actor=" ",text="Ficticio")

    def test_concurrent_draft_patches_do_not_lose_fields_or_versions(self):
        self.seed()
        def update(index):
            return monthly.update_monthly_draft(agravo="tuberculose",patient_ref="fake-1",competence="2026-11",
                unit_ref="Unidade ficticia",actor=f"fake-user-{index}",values={f"fake-field-{index}":str(index)})
        with ThreadPoolExecutor(max_workers=4) as pool:
            results=list(pool.map(update,range(8)))
        self.assertEqual(sorted(r.version for r in results),list(range(2,10)))
        record=monthly.get_monthly_record(agravo="tuberculose",patient_ref="fake-1",competence="2026-11")
        self.assertEqual(record.updated_values,{f"fake-field-{i}":str(i) for i in range(8)})
        self.assertEqual(record.version,9)

    def test_publication_between_query_and_marker_never_exposes_partial_import(self):
        # The competence already exists, so the period lookup cannot hide a partial batch.
        self.seed(records=[],source=b"existing-empty-competence")
        records=[{"patient_ref":f"snapshot-{i:03d}","unit_ref":"Unidade ficticia","values":{}} for i in range(180)]
        original_stage=monthly._stage_import_batch
        def fail_second(import_id,items,coverage,index):
            if index==1:
                raise RuntimeError("synthetic interrupted import")
            return original_stage(import_id,items,coverage,index)
        with patch.object(monthly,"_stage_import_batch",side_effect=fail_second):
            with self.assertRaises(RuntimeError):
                self.seed(records=records,source=b"snapshot-source")
        store=monthly.get_store()
        real_query=store._query
        triggered=False
        class PublishAfterCapture:
            def __init__(self,query,owner):
                self.query=query
                self.owner=owner
            def __getattr__(self,name):
                return getattr(self.query,name)
            def stream(self,*args,**kwargs):
                # Capture only the first staged batch before publishing the rest.
                snapshots=list(self.query.stream(*args,**kwargs))
                self.owner.assertEqual(len(snapshots),80)
                # New thread has no reader ContextVar and uses its own writer transaction.
                with ThreadPoolExecutor(max_workers=1) as executor:
                    result=executor.submit(self.owner.seed,records=records,source=b"snapshot-source").result(timeout=20)
                self.owner.assertEqual(result["inserted"],180)
                yield from snapshots
        def interleave(collection,filters):
            nonlocal triggered
            query=real_query(collection,filters)
            if collection=="monthly_records" and not triggered:
                triggered=True
                return PublishAfterCapture(query,self)
            return query
        with patch.object(store,"_query",side_effect=interleave):
            observed=monthly.list_monthly_records(agravo="tuberculose",competence="2026-11")
        self.assertTrue(triggered)
        self.assertIn(len(observed),(0,180),"Publication markers and records must share a consistent snapshot.")
        self.assertEqual(len(monthly.list_monthly_records(agravo="tuberculose",competence="2026-11")),180)
