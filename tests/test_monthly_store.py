from firestore_support import FirestoreTestCase
from monitoramento.firestore_store import get_store, key
import os
import unittest
from unittest.mock import patch
from datetime import date

from monitoramento.monthly_store import (
    close_monthly_competence,
    compare_monthly_record_fields,
    create_manual_followup,
    ensure_contact_followup,
    get_monthly_competence_state,
    get_monthly_followup_history,
    get_monthly_followup,
    get_monthly_record,
    get_monthly_vigilance_notes,
    get_record_revisions,
    get_monthly_unit_confirmation_history,
    import_monthly_records,
    list_monthly_followups,
    list_monthly_records,
    monthly_followup_metrics,
    monthly_unit_monitoring,
    review_monthly_followup,
    review_monthly_record,
    save_monthly_followup_response,
    set_monthly_monitoring_deadline,
    submit_monthly_record,
    update_monthly_unit_confirmation,
    update_monthly_draft,
)


class MonthlyStoreTests(FirestoreTestCase):


    @staticmethod
    def _record(
        patient_ref: str,
        unit_ref: str = "Unidade fictícia Vera",
        values: dict[str, object] | None = None,
    ) -> dict[str, object]:
        return {
            "patient_ref": patient_ref,
            "unit_ref": unit_ref,
            "values": values or {},
        }

    def test_protected_import_does_not_close_unvalidated_period_or_modify_closed_one(self):
        common = dict(agravo="tuberculose", imported_by="vigilancia",
                      records=[self._record("guarded")])
        import_monthly_records(competence="2026-11", source_content=b"nov", **common)
        with self.assertRaises(ValueError):
            import_monthly_records(competence="2026-12", source_content=b"dec",
                                   protect_workflow=True, **common)
        self.assertEqual(get_monthly_competence_state(agravo="tuberculose", competence="2026-11"), "open")
        self.assertIsNone(get_monthly_competence_state(agravo="tuberculose", competence="2026-12"))
        submit_monthly_record(agravo="tuberculose", competence="2026-11", patient_ref="guarded",
                              unit_ref="Unidade fictícia Vera", actor="unidade")
        review_monthly_record(agravo="tuberculose", competence="2026-11", patient_ref="guarded",
                              actor="vigilancia", approved=True, note="Conferido")
        import_monthly_records(competence="2026-12", source_content=b"dec", protect_workflow=True, **common)
        with self.assertRaises(ValueError):
            import_monthly_records(competence="2026-11", source_content=b"nov-alterado",
                                   protect_workflow=True, **common)

    def test_imports_months_keeps_history_and_compares_values(self) -> None:
        october_values = {
            "campo_texto_demo": "valor de outubro fictício",
            "data_ultimo_comparecimento": "2026-10-12",
        }
        october = import_monthly_records(
            agravo="tuberculose",
            competence="2026-10",
            source_content=b"pdf ficticio outubro",
            imported_by="vigilancia-teste",
            records=[self._record("notificacao-ficticia-1", values=october_values)],
        )
        self.assertEqual(october["inserted"], 1)
        self.assertEqual(get_monthly_competence_state(
            agravo="tuberculose", competence="2026-10"
        ), "open")

        november_values = {
            "campo_texto_demo": "valor de novembro fictício",
        }
        november = import_monthly_records(
            agravo="tuberculose",
            competence="2026-11",
            source_content=b"pdf ficticio novembro",
            imported_by="vigilancia-teste",
            records=[
                self._record("notificacao-ficticia-1", values=november_values),
                self._record(
                    "notificacao-ficticia-2",
                    "Outra unidade fictícia",
                    {"campo_texto_demo": "novo caso fictício"},
                ),
            ],
        )
        self.assertEqual(november["inserted"], 2)
        self.assertEqual(get_monthly_competence_state(
            agravo="tuberculose", competence="2026-10"
        ), "closed")
        closed_by = get_store().get("monthly_competences", key("tuberculose", "2026-10"))["closed_by"]
        self.assertEqual(closed_by, "vigilancia-teste")

        with self.assertRaisesRegex(ValueError, "não está aberta"):
            update_monthly_draft(
                agravo="tuberculose",
                patient_ref="notificacao-ficticia-1",
                competence="2026-10",
                unit_ref="Unidade fictícia Vera",
                actor="profissional-teste",
                values={"campo_texto_demo": "edição bloqueada"},
            )

        current = get_monthly_record(
            agravo="tuberculose",
            patient_ref="notificacao-ficticia-1",
            competence="2026-11",
        )
        previous = get_monthly_record(
            agravo="tuberculose",
            patient_ref="notificacao-ficticia-1",
            competence="2026-10",
        )
        self.assertIsNotNone(current)
        self.assertIsNotNone(previous)
        comparison = compare_monthly_record_fields(current, previous)
        self.assertEqual(comparison["campo_texto_demo"]["status"], "changed")
        self.assertEqual(
            comparison["data_ultimo_comparecimento"]["status"],
            "not_updated",
        )

        update_monthly_draft(
            agravo="tuberculose",
            patient_ref="notificacao-ficticia-1",
            competence="2026-11",
            unit_ref="Unidade fictícia Vera",
            actor="profissional-teste",
            values={"data_ultimo_comparecimento": "2026-11-09"},
        )
        self.assertEqual(
            get_monthly_record(
                agravo="tuberculose",
                patient_ref="notificacao-ficticia-1",
                competence="2026-10",
            ).values["data_ultimo_comparecimento"],
            "2026-10-12",
        )
        current = get_monthly_record(
            agravo="tuberculose",
            patient_ref="notificacao-ficticia-1",
            competence="2026-11",
        )
        self.assertEqual(
            compare_monthly_record_fields(current, previous)[
                "data_ultimo_comparecimento"
            ]["status"],
            "changed",
        )

        submitted = submit_monthly_record(
            agravo="tuberculose",
            patient_ref="notificacao-ficticia-1",
            competence="2026-11",
            unit_ref="Unidade fictícia Vera",
            actor="profissional-teste",
        )
        self.assertEqual(submitted.state, "submitted")
        reviewed = review_monthly_record(
            agravo="tuberculose",
            patient_ref="notificacao-ficticia-1",
            competence="2026-11",
            actor="vigilancia-teste",
            approved=True,
            note="Conferido em teste fictício.",
        )
        self.assertEqual(reviewed.state, "validated")
        submit_monthly_record(
            agravo="tuberculose",
            patient_ref="notificacao-ficticia-2",
            competence="2026-11",
            unit_ref="Outra unidade fictícia",
            actor="profissional-teste-2",
        )
        review_monthly_record(
            agravo="tuberculose",
            patient_ref="notificacao-ficticia-2",
            competence="2026-11",
            actor="vigilancia-teste",
            approved=True,
            note="Validado em teste.",
        )
        self.assertEqual(len(get_record_revisions(
            agravo="tuberculose",
            patient_ref="notificacao-ficticia-1",
            competence="2026-11",
        )), 4)
        notes = get_monthly_vigilance_notes(
            agravo="tuberculose",
            patient_ref="notificacao-ficticia-1",
            competence="2026-11",
        )
        self.assertEqual(
            [note["note"] for note in notes],
            ["Conferido em teste fictício."],
        )

        close_monthly_competence(
            agravo="tuberculose",
            competence="2026-11",
            actor="vigilancia-teste",
        )
        closed_by = get_store().get("monthly_competences", key("tuberculose", "2026-11"))["closed_by"]
        self.assertEqual(closed_by, "vigilancia-teste")
        december = import_monthly_records(
            agravo="tuberculose",
            competence="2026-12",
            source_content=b"pdf ficticio dezembro",
            imported_by="vigilancia-teste",
            records=[self._record("notificacao-ficticia-1", values=november_values)],
        )
        self.assertEqual(december["inserted"], 1)
        self.assertEqual(len(list_monthly_records(
            agravo="tuberculose", competence="2026-10"
        )), 1)
        self.assertEqual(len(list_monthly_records(
            agravo="tuberculose", competence="2026-11"
        )), 2)
        self.assertEqual(
            get_monthly_vigilance_notes(
                agravo="tuberculose",
                patient_ref="notificacao-ficticia-1",
                competence="2026-11",
            ),
            notes,
        )

    def test_repeated_import_is_idempotent_and_changed_source_conflicts(self) -> None:
        record = self._record("notificacao-ficticia-1", values={"campo_demo": "original"})
        first = import_monthly_records(
            agravo="hanseniase",
            competence="2026-10",
            source_content=b"pdf-han-original",
            imported_by="vigilancia-teste",
            records=[record],
        )
        duplicate = import_monthly_records(
            agravo="hanseniase",
            competence="2026-10",
            source_content=b"pdf-han-original",
            imported_by="vigilancia-teste",
            records=[record],
        )
        self.assertEqual(first["import_id"], duplicate["import_id"])
        self.assertTrue(duplicate["duplicate"])
        self.assertEqual(len(list_monthly_records(
            agravo="hanseniase", competence="2026-10"
        )), 1)

        update_monthly_draft(
            agravo="hanseniase",
            patient_ref="notificacao-ficticia-1",
            competence="2026-10",
            unit_ref="Unidade fictícia Vera",
            actor="profissional-teste",
            values={"campo_demo": "atualização da unidade"},
        )
        conflict = import_monthly_records(
            agravo="hanseniase",
            competence="2026-10",
            source_content=b"pdf-han-corrigido",
            imported_by="vigilancia-teste",
            records=[
                self._record(
                    "notificacao-ficticia-1",
                    values={"campo_demo": "valor de origem divergente"},
                )
            ],
        )
        self.assertEqual(conflict["conflicts"], 1)
        stored = get_monthly_record(
            agravo="hanseniase",
            patient_ref="notificacao-ficticia-1",
            competence="2026-10",
        )
        self.assertEqual(stored.original_values["campo_demo"], "original")
        self.assertEqual(stored.updated_values["campo_demo"], "atualização da unidade")

    def test_import_rejects_duplicate_patient_refs_in_same_pdf(self) -> None:
        with self.assertRaisesRegex(ValueError, "duplicados"):
            import_monthly_records(
                agravo="tuberculose",
                competence="2026-10",
                source_content=b"pdf duplicado ficticio",
                imported_by="vigilancia-teste",
                records=[
                    self._record("notificacao-ficticia-1"),
                    self._record("notificacao-ficticia-1"),
                ],
            )

    def test_followup_suggestion_response_review_and_history_are_audited(self) -> None:
        import_monthly_records(
            agravo="tuberculose",
            competence="2026-11",
            source_content=b"boletim-ficticio-comunicacao",
            imported_by="vigilancia-teste",
            records=[
                self._record(
                    "notificacao-ficticia-3",
                    values={
                        "contatos_identificados": "4",
                        "contatos_examinados": "2",
                    },
                )
            ],
        )
        record = get_monthly_record(
            agravo="tuberculose",
            patient_ref="notificacao-ficticia-3",
            competence="2026-11",
        )
        suggestion = ensure_contact_followup(record)
        self.assertIsNotNone(suggestion)
        self.assertEqual(suggestion.state, "automatic_suggestion")
        self.assertIn("4 contatos", suggestion.automatic_text)
        self.assertEqual(ensure_contact_followup(record).id, suggestion.id)
        self.assertEqual(len(list_monthly_followups(unit_ref="Unidade fictícia Vera")), 1)
        import_monthly_records(
            agravo="tuberculose",
            competence="2026-12",
            source_content=b"boletim-ficticio-comunicacao-dezembro",
            imported_by="vigilancia-teste",
            records=[
                self._record(
                    "notificacao-ficticia-3",
                    values={
                        "contatos_identificados": "4",
                        "contatos_examinados": "2",
                    },
                )
            ],
        )
        next_month = get_monthly_record(
            agravo="tuberculose",
            patient_ref="notificacao-ficticia-3",
            competence="2026-12",
        )
        carried = ensure_contact_followup(next_month)
        self.assertEqual(carried.id, suggestion.id)
        self.assertEqual(carried.competence, "2026-11")

        with self.assertRaises(PermissionError):
            save_monthly_followup_response(
                followup_id=suggestion.id,
                unit_ref="Outra unidade fictícia",
                actor="profissional-outra-unidade",
                text="resposta não autorizada",
                submit=True,
            )
        with self.assertRaises(ValueError):
            save_monthly_followup_response(
                followup_id=suggestion.id,
                unit_ref="Unidade fictícia Vera",
                actor="profissional-teste",
                text="rascunho antes do envio",
                submit=True,
            )

        reviewed = review_monthly_followup(
            followup_id=suggestion.id,
            actor="vigilancia-teste",
            action="send",
            text="Favor informar as providências adotadas.",
            priority="high",
        )
        self.assertEqual(reviewed.state, "awaiting_unit")
        self.assertEqual(reviewed.automatic_text, suggestion.automatic_text)
        edited_note = review_monthly_followup(
            followup_id=suggestion.id,
            actor="vigilancia-teste",
            action="save_note",
            text="Favor informar as providências e o prazo de avaliação.",
            priority="high",
        )
        self.assertEqual(edited_note.state, "awaiting_unit")
        self.assertEqual(edited_note.automatic_text, suggestion.automatic_text)
        self.assertIn("prazo", edited_note.vigilance_text)
        draft = save_monthly_followup_response(
            followup_id=suggestion.id,
            unit_ref="Unidade fictícia Vera",
            actor="profissional-teste",
            text="Verificando os dados.",
            submit=False,
        )
        self.assertEqual(draft.state, "awaiting_unit")
        self.assertEqual(draft.draft_text, "Verificando os dados.")
        submitted = save_monthly_followup_response(
            followup_id=suggestion.id,
            unit_ref="Unidade fictícia Vera",
            actor="profissional-teste",
            text="Dois contatos foram examinados e os demais estão agendados.",
            submit=True,
        )
        self.assertEqual(submitted.state, "responded")
        self.assertEqual(submitted.draft_text, "")
        self.assertEqual(submitted.response_by, "profissional-teste")
        requested = review_monthly_followup(
            followup_id=suggestion.id,
            actor="vigilancia-teste",
            action="request_more_info",
            text="Informar a data prevista para os contatos restantes.",
        )
        self.assertEqual(requested.state, "needs_more_info")
        submitted_again = save_monthly_followup_response(
            followup_id=suggestion.id,
            unit_ref="Unidade fictícia Vera",
            actor="profissional-teste",
            text="Agendados para a próxima semana.",
            submit=True,
        )
        self.assertEqual(submitted_again.state, "responded")
        in_review = review_monthly_followup(
            followup_id=suggestion.id,
            actor="vigilancia-teste",
            action="start_review",
            text="Conferindo a informação recebida.",
        )
        self.assertEqual(in_review.state, "under_review")
        resolved = review_monthly_followup(
            followup_id=suggestion.id,
            actor="vigilancia-teste",
            action="finish_review",
            text="Solicitação conferida e concluída.",
        )
        self.assertEqual(resolved.state, "resolved")
        self.assertEqual(
            get_monthly_followup(followup_id=suggestion.id).automatic_text,
            suggestion.automatic_text,
        )
        history = get_monthly_followup_history(suggestion.id)
        self.assertEqual(
            [entry["kind"] for entry in history],
            ["event", "event", "event", "response", "event", "response", "event",
             "event", "response", "event", "event"],
        )
        self.assertEqual(history[3]["text"], "Verificando os dados.")
        self.assertEqual(monthly_followup_metrics()["total"], 1)
        self.assertEqual(monthly_followup_metrics()["respostas_enviadas"], 2)

    def test_followup_history_keeps_operation_order_when_clock_repeats(self) -> None:
        import_monthly_records(
            agravo="tuberculose", competence="2026-11",
            source_content=b"same-clock", imported_by="vigilancia",
            records=[self._record("same-clock")],
        )
        followup = create_manual_followup(
            agravo="tuberculose", competence="2026-11", patient_ref="same-clock",
            unit_ref="Unidade fictícia Vera", actor="vigilancia", text="Conferir.",
        )
        with patch("monitoramento.monthly_store._now",
                   return_value="2030-01-01T00:00:00.000000+00:00"):
            for number in (1, 2):
                review_monthly_followup(
                    followup_id=followup.id, actor="vigilancia", action="save_note",
                    text=f"Observação {number}",
                )
                save_monthly_followup_response(
                    followup_id=followup.id, unit_ref=followup.unit_ref, actor="unidade",
                    text=f"Rascunho {number}", submit=False,
                )
        history = get_monthly_followup_history(followup.id)
        self.assertEqual(
            [entry["text"] for entry in history],
            ["Conferir.", "Observação 1", "Rascunho 1", "Observação 2", "Rascunho 2"],
        )

    def test_manual_followup_requires_existing_record_and_creates_audited_thread(self) -> None:
        import_monthly_records(
            agravo="hanseniase",
            competence="2026-11",
            source_content=b"boletim-hanseniase-ficticio",
            imported_by="vigilancia-teste",
            records=[self._record("notificacao-ficticia-4")],
        )
        thread = create_manual_followup(
            agravo="hanseniase",
            patient_ref="notificacao-ficticia-4",
            competence="2026-11",
            unit_ref="Unidade fictícia Vera",
            actor="vigilancia-teste",
            text="Conferir a informação informada no boletim.",
            field_key="doses_supervisionadas",
        )
        self.assertEqual(thread.state, "awaiting_unit")
        self.assertEqual(thread.automatic_text, "")
        self.assertEqual(thread.field_key, "doses_supervisionadas")
        self.assertEqual(thread.vigilance_text, "Conferir a informação informada no boletim.")
        with self.assertRaises(PermissionError):
            create_manual_followup(
                agravo="hanseniase",
                patient_ref="notificacao-ficticia-4",
                competence="2026-11",
                unit_ref="Unidade diferente",
                actor="vigilancia-teste",
                text="Solicitação não autorizada.",
            )
        with self.assertRaisesRegex(ValueError, "não pode ser vinculado"):
            create_manual_followup(
                agravo="hanseniase",
                patient_ref="notificacao-ficticia-4",
                competence="2026-11",
                unit_ref="Unidade fictícia Vera",
                actor="vigilancia-teste",
                text="Campo imutável não deve ser editável.",
                field_key="numero_notificacao",
            )

    def test_unit_monitoring_separates_red_yellow_green_and_deadlines(self) -> None:
        units = (
            "Unidade fictícia sem envio",
            "Unidade fictícia parcial",
            "Unidade fictícia completa",
        )
        import_monthly_records(
            agravo="tuberculose",
            competence="2026-10",
            source_content=b"monitoramento-ficticio-estados",
            imported_by="vigilancia-teste",
            records=[
                self._record("notificacao-sem-envio", units[0]),
                self._record("notificacao-parcial-1", units[1]),
                self._record("notificacao-parcial-2", units[1]),
                self._record("notificacao-parcial-3", units[1]),
                self._record("notificacao-completa", units[2]),
            ],
            unit_coverage=units,
        )
        set_monthly_monitoring_deadline(
            agravo="tuberculose",
            competence="2026-10",
            opened_on="2026-10-01",
            due_on="2026-10-10",
            extension_due_on=None,
            actor="vigilancia-teste",
        )
        submit_monthly_record(
            agravo="tuberculose",
            patient_ref="notificacao-parcial-1",
            competence="2026-10",
            unit_ref=units[1],
            actor="profissional-teste",
        )
        submit_monthly_record(
            agravo="tuberculose",
            patient_ref="notificacao-parcial-2",
            competence="2026-10",
            unit_ref=units[1],
            actor="profissional-teste",
        )
        submit_monthly_record(
            agravo="tuberculose",
            patient_ref="notificacao-completa",
            competence="2026-10",
            unit_ref=units[2],
            actor="profissional-teste",
        )
        before_deadline = {
            row["unit_ref"]: row
            for row in monthly_unit_monitoring(
                agravo="tuberculose",
                competence="2026-10",
                units=units,
                as_of=date(2026, 10, 10),
            )
        }
        self.assertEqual(before_deadline[units[0]]["situation"], "awaiting")
        self.assertEqual(
            before_deadline[units[0]]["patients"][0]["situation"],
            "awaiting",
        )
        after_deadline = {
            row["unit_ref"]: row
            for row in monthly_unit_monitoring(
                agravo="tuberculose",
                competence="2026-10",
                units=units,
                as_of=date(2026, 10, 11),
            )
        }
        self.assertEqual(after_deadline[units[0]]["situation"], "no_update")
        self.assertEqual(
            after_deadline[units[0]]["patients"][0]["situation"],
            "no_update",
        )
        self.assertEqual(after_deadline[units[1]]["situation"], "partial")
        self.assertEqual(after_deadline[units[1]]["percentage"], 67)
        self.assertEqual(
            {
                patient["patient_ref"]: patient["situation"]
                for patient in after_deadline[units[1]]["patients"]
            },
            {
                "notificacao-parcial-1": "complete",
                "notificacao-parcial-2": "complete",
                "notificacao-parcial-3": "no_update",
            },
        )
        self.assertEqual(after_deadline[units[2]]["situation"], "complete")
        self.assertEqual(after_deadline[units[2]]["percentage"], 100)
        self.assertEqual(
            after_deadline[units[2]]["patients"][0]["situation"],
            "complete",
        )

    def test_silence_requires_unit_coverage_and_reconciliation(self) -> None:
        previous_unit = "Unidade fictícia com histórico"
        silent_unit = "Unidade fictícia silenciosa"
        import_monthly_records(
            agravo="hanseniase",
            competence="2026-09",
            source_content=b"historico-ficticio-hanseniase",
            imported_by="vigilancia-teste",
            records=[self._record("notificacao-ausente-atual", previous_unit)],
            unit_coverage=(previous_unit,),
        )
        import_monthly_records(
            agravo="hanseniase",
            competence="2026-10",
            source_content=b"boletim-vazio-cobertura-confirmada",
            imported_by="vigilancia-teste",
            records=[],
            unit_coverage=(previous_unit, silent_unit),
        )
        rows = {
            row["unit_ref"]: row
            for row in monthly_unit_monitoring(
                agravo="hanseniase",
                competence="2026-10",
                units=(previous_unit, silent_unit),
            )
        }
        self.assertEqual(rows[previous_unit]["situation"], "silent_pending")
        self.assertEqual(rows[previous_unit]["previous_missing"], 1)
        self.assertEqual(rows[silent_unit]["situation"], "silent_pending")
        self.assertEqual(rows[silent_unit]["previous_missing"], 0)

        with self.assertRaisesRegex(ValueError, "histórico anterior"):
            update_monthly_unit_confirmation(
                agravo="hanseniase",
                competence="2026-10",
                unit_ref=previous_unit,
                actor="unidade-teste",
                actor_role="unit",
                action="confirm_absence",
            )
        update_monthly_unit_confirmation(
            agravo="hanseniase",
            competence="2026-10",
            unit_ref=previous_unit,
            actor="unidade-teste",
            actor_role="unit",
            action="request_review",
            note="Há um registro do mês anterior que precisa ser conferido.",
        )
        reconciliation = monthly_unit_monitoring(
            agravo="hanseniase",
            competence="2026-10",
            units=(previous_unit,),
        )[0]
        self.assertEqual(reconciliation["situation"], "reconciliation_required")
        update_monthly_unit_confirmation(
            agravo="hanseniase",
            competence="2026-10",
            unit_ref=previous_unit,
            actor="vigilancia-teste",
            actor_role="surveillance",
            action="resolve_reconciliation",
            note="Registro anterior conferido; ausência atual revisada.",
        )
        resolved = monthly_unit_monitoring(
            agravo="hanseniase",
            competence="2026-10",
            units=(previous_unit,),
        )[0]
        self.assertEqual(resolved["situation"], "silent_confirmed")
        self.assertEqual(
            len(get_monthly_unit_confirmation_history(
                agravo="hanseniase",
                competence="2026-10",
                unit_ref=previous_unit,
            )),
            2,
        )
        update_monthly_unit_confirmation(
            agravo="hanseniase",
            competence="2026-10",
            unit_ref=silent_unit,
            actor="unidade-teste",
            actor_role="unit",
            action="confirm_absence",
        )
        confirmed = monthly_unit_monitoring(
            agravo="hanseniase",
            competence="2026-10",
            units=(silent_unit,),
        )[0]
        self.assertEqual(confirmed["situation"], "silent_confirmed")

    def test_unit_without_explicit_import_coverage_is_unavailable(self) -> None:
        import_monthly_records(
            agravo="tuberculose",
            competence="2026-11",
            source_content=b"import-sem-cobertura-explicita",
            imported_by="vigilancia-teste",
            records=[],
        )
        row = monthly_unit_monitoring(
            agravo="tuberculose",
            competence="2026-11",
            units=("Unidade sem cobertura fictícia",),
        )[0]
        self.assertTrue(row["imported"])
        self.assertFalse(row["coverage_confirmed"])
        self.assertEqual(row["situation"], "data_unavailable")


if __name__ == "__main__":
    unittest.main()
