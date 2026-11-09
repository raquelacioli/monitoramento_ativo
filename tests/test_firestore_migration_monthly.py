"""Migrate a completely synthetic legacy monthly database into the local emulator."""
import ast
import hashlib
import json
import sqlite3
import subprocess
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from firestore_support import FirestoreTestCase
from monitoramento import monthly_store as monthly
from monitoramento.firestore_store import Store, get_store, key
from monitoramento.migrate_sqlite import migrate


class MonthlyMigrationTests(FirestoreTestCase):
    def setUp(self):
        super().setUp()
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.source = Path(self.temporary.name) / "monthly-entirely-fictitious.sqlite3"
        # Read source code only. Execute the schema literal, never import or execute legacy code.
        source = subprocess.check_output(
            ["git", "show", "HEAD:monitoramento/monthly_store.py"],
            cwd=Path(__file__).resolve().parents[1], text=True, encoding="utf-8")
        tree = ast.parse(source)
        initialize = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_initialize")
        script = next(ast.literal_eval(n.args[0]) for n in ast.walk(initialize)
                      if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                      and n.func.attr == "executescript")
        with closing(sqlite3.connect(self.source)) as connection, connection:
            connection.executescript(script)
            self._populate(connection)
        self.source_hash = hashlib.sha256(self.source.read_bytes()).digest()

    @staticmethod
    def insert(connection, table, **values):
        columns = ",".join(values)
        placeholders = ",".join("?" for _ in values)
        connection.execute(f"INSERT INTO {table} ({columns}) VALUES ({placeholders})", tuple(values.values()))

    def _populate(self, c):
        t0, t1, t2, t3 = (f"2026-11-01T00:00:0{i}.000000+00:00" for i in range(4))
        for agravo, competence, state in (("tuberculose", "2026-10", "closed"),
                                         ("tuberculose", "2026-11", "open"),
                                         ("hanseniase", "2026-11", "open")):
            self.insert(c, "monthly_competences", agravo=agravo, competence=competence,
                        state=state, opened_by="vigilancia-ficticia", opened_at=t0,
                        closed_by="vigilancia-ficticia" if state == "closed" else None,
                        closed_at=t0 if state == "closed" else None)
        for ident, agravo, competence, count in ((1, "tuberculose", "2026-10", 1),
                                                (2, "tuberculose", "2026-11", 1),
                                                (3, "hanseniase", "2026-11", 1),
                                                (4, "hanseniase", "2026-11", 0)):
            self.insert(c, "monthly_imports", id=ident, agravo=agravo, competence=competence,
                        source_sha256=hashlib.sha256(f"synthetic-source-{ident}".encode()).hexdigest(),
                        imported_by="vigilancia-ficticia", imported_at=t0, record_count=count)
        for ident, unit in ((1, "Unidade ficticia"), (2, "Unidade ficticia"),
                            (2, "Unidade silenciosa ficticia"), (3, "Unidade hanseniase ficticia")):
            self.insert(c, "monthly_import_unit_coverage", import_id=ident, unit_ref=unit)
        originals = {"contatos_identificados": "4", "contatos_examinados": "1"}
        for agravo, patient, competence, unit, imported, version, state in (
            ("tuberculose", "fake-notification", "2026-10", "Unidade ficticia", 1, 1, "validated"),
            ("tuberculose", "fake-notification", "2026-11", "Unidade ficticia", 2, 4, "returned"),
            ("hanseniase", "fake-hans", "2026-11", "Unidade hanseniase ficticia", 3, 1, "draft")):
            self.insert(c, "monthly_records", agravo=agravo, patient_ref=patient, competence=competence,
                        unit_ref=unit, import_id=imported, original_values=json.dumps(originals),
                        updated_values=json.dumps({"observacao": "Atualizacao ficticia"}), state=state,
                        version=version, updated_by="unidade-ficticia", updated_at=t2,
                        reviewer_note="Conferir boletim ficticio")
        for version, action, state in ((1,"imported","draft"),(2,"draft_saved","draft"),
                                       (3,"submitted","submitted"),(4,"returned","returned")):
            self.insert(c, "monthly_record_revisions", id=version, agravo="tuberculose",
                        patient_ref="fake-notification", competence="2026-11", version=version,
                        action=action, actor="vigilancia-ficticia", occurred_at=t2 if version==4 else t0,
                        original_values=json.dumps(originals), updated_values='{"observacao":"Atualizacao ficticia"}',
                        state=state, note="Conferir boletim ficticio" if version==4 else "")
        self.insert(c,"monthly_import_conflicts",id=1,import_id=4,agravo="hanseniase",patient_ref="fake-hans",
                    competence="2026-11",stored_original_values=json.dumps(originals),
                    incoming_original_values='{"campo":"Ficticio alterado"}',detected_at=t2)
        self.insert(c,"monthly_vigilance_notes",id=1,agravo="tuberculose",patient_ref="fake-notification",
                    competence="2026-11",actor="vigilancia-ficticia",occurred_at=t2,action="returned",
                    note="Conferir boletim ficticio")
        self.insert(c,"monthly_followups",id=7,agravo="tuberculose",patient_ref="fake-notification",
                    unit_ref="Unidade ficticia",competence="2026-11",rule_id="contacts_not_examined",
                    field_key="contatos_examinados",automatic_text="Alerta ficticio",vigilance_text="Conferir contatos ficticios",
                    state="responded",priority="high",created_by="vigilancia-ficticia",created_at=t0,
                    updated_by="unidade-ficticia",updated_at=t2)
        for ident, version, state, when, text in ((20,1,"submitted",t2,"Resposta ficticia enviada"),
                                                (21,2,"draft",t3,"Novo rascunho ficticio")):
            self.insert(c,"monthly_followup_responses",id=ident,followup_id=7,version=version,
                        actor="unidade-ficticia",occurred_at=when,state=state,response_text=text)
        for ident, action, old_state, new_state, when in ((10,"send","automatic_suggestion","awaiting_unit",t1),
                                                       (11,"unit_submitted","awaiting_unit","responded",t2)):
            self.insert(c,"monthly_followup_events",id=ident,followup_id=7,actor="vigilancia-ficticia",
                        occurred_at=when,action=action,old_state=old_state,new_state=new_state,
                        old_text="Ficticio anterior",new_text="Ficticio atual",priority="high")
        self.insert(c,"monthly_monitoring_deadlines",agravo="tuberculose",competence="2026-11",
                    opened_on="2026-11-01",due_on="2026-11-10",extension_due_on="2026-11-15",
                    updated_by="vigilancia-ficticia",updated_at=t2)
        self.insert(c,"monthly_monitoring_deadline_events",id=30,agravo="tuberculose",competence="2026-11",
                    actor="vigilancia-ficticia",occurred_at=t2,action="updated",old_values='{}',
                    new_values='{"extension_due_on":"2026-11-15"}')
        self.insert(c,"monthly_unit_confirmations",agravo="tuberculose",competence="2026-11",
                    unit_ref="Unidade silenciosa ficticia",status="confirmed_absent",note="Ausencia ficticia",
                    updated_by="unidade-ficticia",updated_role="unit",updated_at=t2)
        self.insert(c,"monthly_unit_confirmation_events",id=40,agravo="tuberculose",competence="2026-11",
                    unit_ref="Unidade silenciosa ficticia",actor="unidade-ficticia",actor_role="unit",
                    occurred_at=t2,action="confirm_absence",old_status=None,new_status="confirmed_absent",
                    note="Ausencia ficticia")

    def assert_migrated(self):
        record=monthly.get_monthly_record(agravo="tuberculose",patient_ref="fake-notification",competence="2026-11")
        self.assertEqual(record.state,"returned")
        self.assertEqual(record.version,4)
        self.assertEqual(record.updated_values,{"observacao":"Atualizacao ficticia"})
        self.assertEqual(record.original_values["contatos_identificados"],"4")
        revisions=monthly.get_record_revisions(agravo="tuberculose",patient_ref="fake-notification",competence="2026-11")
        self.assertEqual([r["version"] for r in revisions],[1,2,3,4])
        self.assertEqual(revisions[-1]["action"],"returned")
        self.assertEqual(monthly.get_monthly_vigilance_notes(agravo="tuberculose",patient_ref="fake-notification",
            competence="2026-11")[0]["note"],"Conferir boletim ficticio")
        followup=monthly.get_monthly_followup(followup_id=7,unit_ref="Unidade ficticia")
        self.assertEqual(followup.response_text,"Resposta ficticia enviada")
        self.assertEqual(followup.draft_text,"Novo rascunho ficticio")
        self.assertEqual(followup.response_version,1)
        history=monthly.get_monthly_followup_history(7)
        self.assertEqual([r["kind"] for r in history],["event","event","response","response"])
        metrics=monthly.monthly_followup_metrics(agravo="tuberculose",competence="2026-11")
        self.assertEqual(metrics["total"],1)
        self.assertEqual(metrics["respostas_enviadas"],1)
        self.assertEqual(metrics["tempo_medio_resposta_segundos"],1)
        self.assertEqual(monthly.get_monthly_monitoring_deadline(agravo="tuberculose",competence="2026-11")
                         ["extension_due_on"],"2026-11-15")
        units=monthly.monthly_unit_monitoring(agravo="tuberculose",competence="2026-11",
            units=("Unidade ficticia","Unidade silenciosa ficticia"))
        self.assertTrue(units[0]["coverage_confirmed"])
        self.assertEqual(units[1]["situation"],"silent_confirmed")
        hans=monthly.monthly_unit_monitoring(agravo="hanseniase",competence="2026-11",
            units=("Unidade hanseniase ficticia",))[0]
        self.assertFalse(hans["integrity_ok"])
        self.assertEqual(hans["situation"],"data_unavailable")
        self.assertEqual(monthly.get_monthly_unit_confirmation_history(agravo="tuberculose",competence="2026-11",
            unit_ref="Unidade silenciosa ficticia")[0]["new_status"],"confirmed_absent")
        self.assertEqual(get_store().get("monthly_monitoring_deadline_events",key(30))["new_values"],
                         {"extension_due_on":"2026-11-15"})

    def test_all_monthly_domains_survive_migration_and_counters_continue(self):
        self.assertEqual(migrate(self.source,apply=True)["status"],"complete")
        self.assert_migrated()
        self.assertEqual(migrate(self.source,apply=True)["status"],"complete")
        response=monthly.save_monthly_followup_response(followup_id=7,unit_ref="Unidade ficticia",
            actor="unidade-ficticia",text="Resposta ficticia seguinte",submit=True)
        self.assertEqual(response.response_version,3)
        self.assertEqual(response.draft_text,"")
        self.assertEqual(len(get_store().query("monthly_followup_responses")),3)
        self.assertIsNotNone(get_store().get("monthly_followup_responses",key(22)))
        followup=monthly.create_manual_followup(agravo="tuberculose",patient_ref="fake-notification",competence="2026-11",
            unit_ref="Unidade ficticia",actor="vigilancia-ficticia",text="Outra solicitacao ficticia")
        self.assertEqual(followup.id,8)
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).digest(),self.source_hash)

    def test_failure_between_migration_batches_resumes_without_duplicates(self):
        # More than 100 prepared documents makes a second bounded migration batch necessary.
        with closing(sqlite3.connect(self.source)) as connection, connection:
            for version in range(5,125):
                self.insert(connection,"monthly_record_revisions",id=version,agravo="tuberculose",
                    patient_ref="fake-notification",competence="2026-11",version=version,action="draft_saved",
                    actor="unidade-ficticia",occurred_at="2026-11-01T00:00:03.000000+00:00",
                    original_values='{}',updated_values='{}',state="draft",note="Ficticio")
        original_hash=hashlib.sha256(self.source.read_bytes()).digest()
        store=get_store()
        run=store.run
        batches=0
        def fail_second(callback,guard="domain"):
            nonlocal batches
            if callback.__name__=="copy_batch":
                batches+=1
                if batches==2:
                    raise ConnectionError("synthetic migration failure")
            return run(callback,guard=guard)
        with patch.object(store,"run",side_effect=fail_second):
            with self.assertRaisesRegex(ConnectionError,"synthetic"):
                migrate(self.source,apply=True)
        state=store.get("_migration",key("state"))
        self.assertEqual(state["status"],"loading")
        self.assertEqual(state["offset"],100)
        with self.assertRaisesRegex(ValueError,"migração"):
            monthly.list_monthly_records(agravo="tuberculose",competence="2026-11")
        self.assertEqual(migrate(self.source,apply=True)["status"],"complete")
        self.assertEqual(len(monthly.get_record_revisions(agravo="tuberculose",patient_ref="fake-notification",
            competence="2026-11")),124)
        self.assertEqual(len(store.query("monthly_followups")),1)
        self.assertEqual(len(store.query("monthly_followup_responses")),2)
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).digest(),original_hash)

    def test_concurrent_live_writer_and_migration_admission_cannot_mix_destinations(self):
        store=get_store()
        # Independent process analogue: distinct Store/RLock, same Firestore namespace.
        other_process=Store(store.client,store.namespace)
        rendezvous=threading.Barrier(2)
        writer_done=threading.Event()
        writer_first=True
        admission_first=True
        actual_run=store.run
        identity=key("tuberculose","fake-notification","2026-11")
        sentinel={"sentinel":"concurrent-fictitious-live-data"}

        def live_write(tx):
            nonlocal writer_first
            tx.set("monthly_records",identity,sentinel)
            if writer_first:
                writer_first=False
                rendezvous.wait(timeout=5)

        def admission_run(callback,guard="domain"):
            nonlocal admission_first
            if callback.__name__!="begin":
                return actual_run(callback,guard=guard)
            def admit(tx):
                nonlocal admission_first
                result=callback(tx)
                if admission_first:
                    admission_first=False
                    rendezvous.wait(timeout=5)
                return result
            result=actual_run(admit,guard=guard)
            # Keep the admitted namespace loading until the competing transaction
            # has committed or rejected. A retry must not masquerade as a later,
            # legitimate update after completed migration.
            if not writer_done.wait(timeout=10):
                raise AssertionError("Competing writer did not finish promptly.")
            return result

        def writer():
            try:
                other_process.run(live_write,guard="live_writer")
                return True
            except ValueError:
                return False
            finally:
                writer_done.set()

        def migration():
            try:
                return migrate(self.source,apply=True)["status"]=="complete"
            except ValueError:
                return False

        with patch.object(store,"run",side_effect=admission_run):
            with ThreadPoolExecutor(max_workers=2) as pool:
                live=pool.submit(writer)
                copied=pool.submit(migration)
                writer_succeeded=live.result(timeout=20)
                migration_succeeded=copied.result(timeout=20)
        self.assertEqual(int(writer_succeeded)+int(migration_succeeded),1,
                         "An admitted migration and an overlapping live writer must not both commit.")
        if writer_succeeded:
            self.assertEqual(store.get("monthly_records",identity),sentinel)
            self.assertEqual(store.query("monthly_imports"),[])
            self.assertIsNone(store.get("_migration",key("state")))
        else:
            self.assert_migrated()
            self.assertNotIn("sentinel",store.get("monthly_records",identity))
            self.assertEqual(store.get("_migration",key("state"))["status"],"complete")
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).digest(),self.source_hash)

    def test_empty_partial_monthly_schema_is_rejected_before_namespace_admission(self):
        malformed=Path(self.temporary.name)/"malformed-empty-monthly-fictitious.sqlite3"
        with closing(sqlite3.connect(malformed)) as connection, connection:
            connection.execute("CREATE TABLE monthly_followups (id INTEGER PRIMARY KEY)")
        original_hash=hashlib.sha256(malformed.read_bytes()).digest()
        with self.assertRaisesRegex(ValueError,"colunas obrigatórias"):
            migrate(malformed,apply=True)
        self.assertIsNone(get_store().get("_migration",key("state")))
        self.assertEqual(get_store().query("monthly_followups"),[])
        self.assertEqual(hashlib.sha256(malformed.read_bytes()).digest(),original_hash)
