"""PDF authored entirely from fictional values; never reads a patient file."""
from pathlib import Path

import pymupdf


COLUMNS = (16.44, 57.92, 103.76, 217.91, 395.23, 422.41, 451.26, 469.72,
           494.19, 524.21, 557.10, 593.54, 611.12, 651.15, 690.01, 773.46, 822.87)
HEADERS = (
    "N da\nNotificacao", "Data da\nNotificacao", "Nome", "Forma Bac Bac Bac Bac Bac Bac Bac",
    "Total contat\nidentif", "Total contat\nexam", "HIV", "TARV", "Cultura", "TRM-TB",
    "Histopat", "TS", "Realizado\nTDO?", "Situacao\nEncerra", "Se Local de Transf\nTransf (Mun/UF)",
    "Data de\nencerramento",
)
ROWS = (
    ("900001", "01/11/2026", "PESSOA FICTICIA ALFA", "", "4", "2", "2", "9", "4", "5", "5", "7", "9", "", "", ""),
    ("900002", "02/11/2026", "PESSOA FICTICIA BETA", "", "3", "3", "2", "9", "4", "5", "5", "7", "9", "", "", ""),
)


def make_tb_pdf(rows=ROWS, unit="Unidade ficticia de testes", headers=HEADERS):
    with pymupdf.open() as document:
        page = document.new_page(width=842, height=595)
        page.insert_text((30, 35), "Boletim de Acompanhamento de Tuberculose", fontsize=12)
        page.insert_text((30, 58), "AMOSTRA INTEIRAMENTE FICTICIA - SEM DADOS REAIS", fontsize=9)
        page.insert_text((30, 100), f"Unidade: {unit}", fontsize=9)
        top, header_bottom = 141.45, 178.68
        bottom = header_bottom + max(len(rows), 1) * 15
        for x in COLUMNS:
            page.draw_line((x, top), (x, bottom), width=0.5)
        for y in (top, header_bottom, *(header_bottom + (i + 1) * 15 for i in range(max(len(rows), 1)))):
            page.draw_line((COLUMNS[0], y), (COLUMNS[-1], y), width=0.5)
        for index, header in enumerate(headers):
            page.insert_text((COLUMNS[index] + 1, top + 8), header, fontsize=4)
        for row_index, row in enumerate(rows):
            for column, value in enumerate(row):
                if value:
                    page.insert_text((COLUMNS[column] + 1, header_bottom + row_index * 15 + 10), value, fontsize=5)
        return document.tobytes()


if __name__ == "__main__":
    target = Path(__file__).resolve().parents[1] / "docs" / "exemplos" / "boletim_tuberculose_ficticio.pdf"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(make_tb_pdf())
    print(target)
