import unittest
from datetime import date

from monitoramento.monthly_workflow import (
    BulletinSchema,
    BulletinState,
    ChangeKind,
    Competence,
    FieldDefinition,
    FieldType,
    MonthlyBulletinVersion,
    compare_monthly_fields,
    transition_bulletin,
)


class MonthlyWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.schema = BulletinSchema(
            agravo="agravo-ficticio-de-teste",
            version="versao-ficticia-de-teste",
            source_document="metadados sintéticos usados somente no teste",
            fields=(
                FieldDefinition(
                    code="campo_texto_demo",
                    label="Campo demonstrativo de texto",
                    value_type=FieldType.TEXT,
                    required=True,
                    source_version="versao-ficticia-de-teste",
                ),
                FieldDefinition(
                    code="campo_inteiro_demo",
                    label="Campo demonstrativo inteiro",
                    value_type=FieldType.INTEGER,
                    required=False,
                    source_version="versao-ficticia-de-teste",
                ),
                FieldDefinition(
                    code="campo_opcao_demo",
                    label="Campo demonstrativo com opções",
                    value_type=FieldType.CHOICE,
                    required=False,
                    source_version="versao-ficticia-de-teste",
                    allowed_values=("opcao_a_demo", "opcao_b_demo"),
                ),
                FieldDefinition(
                    code="campo_data_demo",
                    label="Campo demonstrativo de data",
                    value_type=FieldType.DATE,
                    required=False,
                    source_version="versao-ficticia-de-teste",
                ),
            ),
        )

    def test_competence_parsing_and_previous_month_across_year(self) -> None:
        competence = Competence.parse("2027-01")
        self.assertEqual(str(competence), "2027-01")
        self.assertEqual(str(competence.previous()), "2026-12")
        with self.assertRaises(ValueError):
            Competence.parse("2027-13")

    def test_compare_updates_new_pending_removal_and_unknown_field(self) -> None:
        changes = {
            change.code: change
            for change in compare_monthly_fields(
                {
                    "campo_texto_demo": "valor antigo ficticio",
                    "campo_inteiro_demo": 2,
                    "campo_opcao_demo": "opcao_a_demo",
                },
                {
                    "campo_texto_demo": "valor novo ficticio",
                    "campo_inteiro_demo": 0,
                    "campo_opcao_demo": "",
                    "campo_data_demo": date(2026, 11, 1),
                    "campo_desconhecido_demo": "valor",
                },
                self.schema,
            )
        }

        self.assertEqual(changes["campo_texto_demo"].kind, ChangeKind.UPDATED)
        self.assertEqual(changes["campo_inteiro_demo"].kind, ChangeKind.UPDATED)
        self.assertEqual(changes["campo_inteiro_demo"].current_value, 0)
        self.assertEqual(changes["campo_opcao_demo"].kind, ChangeKind.REMOVED)
        self.assertEqual(changes["campo_data_demo"].kind, ChangeKind.NEW)
        self.assertEqual(changes["campo_desconhecido_demo"].kind, ChangeKind.INCONSISTENT)

        pending = compare_monthly_fields(
            {},
            {},
            self.schema,
        )
        self.assertEqual(
            next(change for change in pending if change.code == "campo_texto_demo").kind,
            ChangeKind.PENDING,
        )

    def test_closed_bulletin_is_immutable_and_requires_new_version(self) -> None:
        previous = MonthlyBulletinVersion(
            record_ref="referencia-ficticia",
            agravo="agravo-ficticio-de-teste",
            unit_ref="unidade-ficticia",
            competence=Competence(2026, 10),
            schema_version=self.schema.version,
            version=1,
            state=BulletinState.CLOSED,
            values=(("campo_inteiro_demo", 0),),
        )
        self.assertEqual(previous.values, (("campo_inteiro_demo", 0),))
        with self.assertRaises(ValueError):
            transition_bulletin(BulletinState.CLOSED, BulletinState.DRAFT)

        correction = MonthlyBulletinVersion(
            record_ref=previous.record_ref,
            agravo=previous.agravo,
            unit_ref=previous.unit_ref,
            competence=previous.competence,
            schema_version=previous.schema_version,
            version=2,
            state=BulletinState.DRAFT,
            values=(("campo_inteiro_demo", 1),),
            previous_version=previous.version,
        )
        self.assertEqual(correction.previous_version, previous.version)
        self.assertEqual(previous.values, (("campo_inteiro_demo", 0),))

    def test_workflow_requires_validated_information_before_submission(self) -> None:
        with self.assertRaises(ValueError):
            transition_bulletin(
                BulletinState.DRAFT,
                BulletinState.SUBMITTED,
                has_blocking_errors=True,
            )
        self.assertEqual(
            transition_bulletin(BulletinState.DRAFT, BulletinState.SUBMITTED),
            BulletinState.SUBMITTED,
        )
        self.assertEqual(
            transition_bulletin(BulletinState.SUBMITTED, BulletinState.VALIDATED),
            BulletinState.VALIDATED,
        )
        self.assertEqual(
            transition_bulletin(BulletinState.VALIDATED, BulletinState.CLOSED),
            BulletinState.CLOSED,
        )


if __name__ == "__main__":
    unittest.main()
