import importlib
import importlib.util
import unittest
from unittest.mock import Mock
import pymupdf

from bulletin_pdf_factory import make_tb_pdf, ROWS, HEADERS


class BulletinImportTests(unittest.TestCase):
    def extract(self, content):
        self.assertIsNotNone(importlib.util.find_spec("monitoramento.bulletin_import"),
                             "O extrator individual deve existir")
        return importlib.import_module("monitoramento.bulletin_import").extract_tb_records(content)

    def test_extracts_only_unambiguous_columns_and_preserves_notification(self):
        preview = self.extract(make_tb_pdf())
        self.assertEqual(preview.unit, "Unidade ficticia de testes")
        self.assertEqual(len(preview.records), 2)
        record = preview.records[0]
        self.assertEqual(record["patient_ref"], "900001")
        self.assertEqual(record["values"]["nome"], "PESSOA FICTICIA ALFA")
        self.assertEqual(record["values"]["data_notificacao"], "2026-11-01")
        self.assertEqual(record["values"]["contatos_identificados"], "4")
        self.assertNotIn("forma", record["values"])
        self.assertNotIn("bac_1_mes", record["values"])
        self.assertTrue(preview.warnings)

    def test_rejects_invalid_dates_codes_contacts_duplicates_and_unknown_layout(self):
        for column, value in ((1, "31/02/2026"), (6, "8"), (5, "99"), (0, "")):
            row = list(ROWS[0])
            row[column] = value
            with self.subTest(column=column):
                with self.assertRaises(ValueError):
                    self.extract(make_tb_pdf(rows=(tuple(row),)))
        with self.assertRaises(ValueError):
            self.extract(make_tb_pdf(rows=(ROWS[0], ROWS[0])))
        headers = list(HEADERS)
        headers[4] = "Campo desconhecido"
        with self.assertRaises(ValueError):
            self.extract(make_tb_pdf(headers=tuple(headers)))

    def test_rejects_empty_file_and_non_pdf(self):
        with self.assertRaises(ValueError):
            self.extract(make_tb_pdf(rows=()))
        with self.assertRaises(ValueError):
            self.extract(b"invalid")

    def test_unfilled_date_mask_remains_empty(self):
        row = list(ROWS[0])
        row[15] = " / / "
        preview = self.extract(make_tb_pdf(rows=(tuple(row),)))
        self.assertEqual(preview.records[0]["values"]["data_encerramento"], "")

    def test_rejects_multiple_tables_in_a_page_instead_of_assigning_wrong_unit(self):
        second = list(ROWS[0])
        second[0] = "900003"
        with pymupdf.open() as document:
            page = document.new_page(width=842, height=1190)
            for index, content in enumerate((make_tb_pdf(rows=(ROWS[0],)),
                    make_tb_pdf(rows=(tuple(second),), unit="Outra unidade ficticia"))):
                with pymupdf.open(stream=content, filetype="pdf") as source:
                    page.show_pdf_page(pymupdf.Rect(0, index * 595, 842, (index + 1) * 595), source, 0)
            with self.assertRaises(ValueError):
                self.extract(document.tobytes())

    def test_rejects_two_units_on_different_pages(self):
        with pymupdf.open() as document:
            for unit in ("Unidade ficticia A", "Unidade ficticia B"):
                with pymupdf.open(stream=make_tb_pdf(unit=unit), filetype="pdf") as source:
                    document.insert_pdf(source)
            with self.assertRaises(ValueError):
                self.extract(document.tobytes())

    def test_does_not_silently_skip_first_person_with_missing_id_and_date(self):
        invalid = list(ROWS[0])
        invalid[0] = invalid[1] = ""
        with self.assertRaises(ValueError):
            self.extract(make_tb_pdf(rows=(tuple(invalid), ROWS[1])))

    def test_rejects_two_unit_declarations_before_one_table(self):
        with self.assertRaises(ValueError):
            self.extract(make_tb_pdf(unit="Unidade ficticia A\nUnidade: Unidade ficticia B"))

    def test_preview_is_owner_bound_expires_and_is_consumed_only_after_success(self):
        self.assertIsNotNone(importlib.util.find_spec("monitoramento.import_previews"))
        module = importlib.import_module("monitoramento.import_previews")
        clock = Mock(return_value=100.0)
        store = module.PreviewStore(clock=clock, max_bytes=10000)
        token = store.create(owner_id=1, competence="2026-11", unit="Unidade ficticia",
                             content=b"pdf ficticio", bulletin=Mock(records=()))
        with self.assertRaises(ValueError):
            store.get(token, owner_id=2)
        failing = Mock(side_effect=ValueError("Banco indisponivel"))
        with self.assertRaises(ValueError):
            store.consume(token, owner_id=1, importer=failing)
        self.assertEqual(store.get(token, owner_id=1).competence, "2026-11")
        self.assertEqual(store.consume(token, owner_id=1, importer=lambda item: "ok"), "ok")
        with self.assertRaises(ValueError):
            store.get(token, owner_id=1)
        token = store.create(owner_id=1, competence="2026-11", unit="Unidade ficticia",
                             content=b"pdf ficticio", bulletin=Mock(records=()))
        clock.return_value = 701.0
        with self.assertRaises(ValueError):
            store.get(token, owner_id=1)

    def test_preview_memory_limit_rejects_without_discarding_another_owner(self):
        self.assertIsNotNone(importlib.util.find_spec("monitoramento.import_previews"))
        store = importlib.import_module("monitoramento.import_previews").PreviewStore(max_bytes=500)
        token = store.create(owner_id=1, competence="2026-11", unit="Unidade ficticia",
                             content=b"small", bulletin=Mock(records=()))
        with self.assertRaises(ValueError):
            store.create(owner_id=2, competence="2026-11", unit="Unidade ficticia",
                         content=b"x" * 501, bulletin=Mock(records=()))
        self.assertEqual(store.get(token, owner_id=1).unit, "Unidade ficticia")


if __name__ == "__main__":
    unittest.main()
