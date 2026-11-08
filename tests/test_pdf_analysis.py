import unittest

import pymupdf

from monitoramento.pdf_analysis import analyze_bulletin
from monitoramento.views import render_bulletin_summary


class PdfAnalysisTests(unittest.TestCase):
    @staticmethod
    def make_pdf(tables=(), unit_line="Unidade: Unidade ficticia") -> bytes:
        with pymupdf.open() as document:
            page = document.new_page(width=800, height=800)
            page.insert_text((30, 30), "Boletim de Acompanhamento de Tuberculose")
            page.insert_text((30, 60), unit_line)
            if not tables:
                page.insert_text((30, 100),
                    "N. Notificacao Atual Data Notificacao Contatos identificados Contatos examinados",
                    fontsize=8)
            for index, (headers, values) in enumerate(tables):
                top = 130 + index * 160
                columns = [30 + number * 145 for number in range(len(headers) + 1)]
                for y in (top, top + 30, top + 60):
                    page.draw_line((columns[0], y), (columns[-1], y))
                for x in columns:
                    page.draw_line((x, top), (x, top + 60))
                for row, y in ((headers, top + 18), (values, top + 48)):
                    for column, value in enumerate(row):
                        page.insert_text((columns[column] + 3, y), value, fontsize=8)
            return document.tobytes()

    def test_empty_unit_is_not_replaced_with_table_header(self):
        report = analyze_bulletin(self.make_pdf(unit_line="Unidade:"), "tuberculose")
        self.assertTrue(report.empty_bulletin)
        self.assertEqual(report.units, ())

    def test_unit_name_on_separate_line_is_preserved(self):
        report = analyze_bulletin(
            self.make_pdf(unit_line="Unidade:\nUnidade ficticia separada"), "tuberculose"
        )
        self.assertEqual(report.units[0].unit, "Unidade ficticia separada")

    def test_explicit_empty_unit_on_next_page_does_not_inherit_previous_unit(self):
        table = (("Notificacao", "Data", "Contatos identificados", "Contatos examinados"),
                 ("123456", "01/11/2026", "5", "2"))
        with pymupdf.open() as combined:
            for unit_line in ("Unidade: Unidade ficticia", "Unidade: ______"):
                with pymupdf.open(stream=self.make_pdf(tables=(table,), unit_line=unit_line),
                                  filetype="pdf") as source:
                    combined.insert_pdf(source)
            report = analyze_bulletin(combined.tobytes(), "tuberculose")
        self.assertEqual(report.units[0].records, 1)
        self.assertEqual(report.records_without_unit, 1)

    def test_each_table_uses_its_own_contact_column_positions(self):
        pdf = self.make_pdf(tables=(
            (("Notificacao", "Data", "Contatos identificados", "Contatos examinados"),
             ("123456", "01/11/2026", "5", "2")),
            (("Notificacao", "Data", "Contatos examinados", "Contatos identificados"),
             ("123457", "02/11/2026", "1", "4")),
        ))
        report = analyze_bulletin(pdf, "tuberculose")
        self.assertEqual(report.units[0].records, 2)
        self.assertEqual(report.units[0].contacts_registered, 9)
        self.assertEqual(report.units[0].contacts_examined, 3)
        self.assertEqual(report.units[0].pending_contact_records, 2)

    def test_table_without_contact_columns_keeps_records_for_checking(self):
        pdf = self.make_pdf(tables=(
            (("Notificacao", "Data", "Nome"),
             ("123456", "01/11/2026", "Pessoa ficticia")),
        ))
        report = analyze_bulletin(pdf, "tuberculose")
        self.assertFalse(report.empty_bulletin)
        self.assertFalse(report.contact_columns_found)
        self.assertEqual(report.units[0].records, 1)
        self.assertEqual(report.units[0].contact_records_to_check, 1)

    def test_examined_contacts_above_registered_are_flagged_for_checking(self):
        pdf = self.make_pdf(tables=(
            (("Notificacao", "Data", "Contatos identificados", "Contatos examinados"),
             ("123456", "01/11/2026", "2", "8")),
        ))
        report = analyze_bulletin(pdf, "tuberculose")
        self.assertEqual(report.units[0].contact_records_to_check, 1)
        self.assertEqual(report.units[0].contacts_registered, 0)
        self.assertEqual(report.units[0].contacts_examined, 0)
        page = render_bulletin_summary("tuberculose", report).body.decode()
        self.assertIn("Totais parciais", page)
        self.assertIn("Registros com dados de contatos ausentes ou inconsistentes: 1", page)


if __name__ == "__main__":
    unittest.main()
