"""Conservative extraction for the identified 16-column TB bulletin layout."""
import re
from dataclasses import dataclass
from datetime import datetime

import pymupdf

from monitoramento.bulletin_forms import validate_form_values
from monitoramento.pdf_analysis import (
    MAX_PDF_BYTES, MAX_PDF_PAGES, PdfAnalysisError, _normalize, _unit_from_lines,
)

MAX_IMPORT_RECORDS = 1000
_COLUMN_FIELDS = {
    0: "numero_notificacao", 1: "data_notificacao", 2: "nome",
    4: "contatos_identificados", 5: "contatos_examinados", 6: "hiv", 7: "tarv",
    8: "cultura", 9: "trm_tb", 10: "histopatologia", 11: "teste_sensibilidade",
    12: "tdo_realizado", 13: "situacao_encerramento", 15: "data_encerramento",
}
_HEADER_SIGNATURE = {
    0: ("notifica",), 1: ("data", "notifica"), 2: ("nome",),
    4: ("contat", "identif"), 5: ("contat", "exam"), 6: ("hiv",),
    7: ("tarv",), 8: ("cultura",), 9: ("trmtb",), 10: ("histopat",),
    11: ("ts",), 12: ("tdo",), 13: ("situacao", "encerra"),
    14: ("transf",), 15: ("data", "encerramento"),
}


@dataclass(frozen=True)
class ExtractedBulletin:
    unit: str
    records: tuple[dict[str, object], ...]
    warnings: tuple[str, ...]


def _cell(value: object) -> str:
    return " ".join(str(value or "").split())


def _headers_match(rows: list[list[object]]) -> bool:
    if not rows or len(rows) > 2 or any(len(row) != 16 for row in rows):
        return False
    if any(_normalize(_cell(value)) not in {"", "atual"}
           for row in rows[1:] for value in row[:2]):
        return False
    if len(rows) == 2 and (
        _cell(rows[1][2])
        or not any(_normalize(_cell(value)) == "atual" for value in rows[1][:2])
    ):
        return False
    headers = [
        re.sub(r"[^a-z0-9]", "", _normalize(" ".join(_cell(row[i]) for row in rows)))
        for i in range(16)
    ]
    return all(all(part in headers[index] for part in parts)
               for index, parts in _HEADER_SIGNATURE.items())


def _values(row: list[object]) -> dict[str, str]:
    values = {key: _cell(row[column]) for column, key in _COLUMN_FIELDS.items()}
    if not re.fullmatch(r"[0-9]{4,12}", values["numero_notificacao"]):
        raise PdfAnalysisError("Há uma linha sem número de notificação válido.")
    if not values["nome"] or not values["data_notificacao"]:
        raise PdfAnalysisError("Há uma linha sem nome ou data de notificação.")
    for field in ("data_notificacao", "data_encerramento"):
        raw = values[field]
        if not raw:
            continue
        raw = re.sub(r"\s", "", raw)
        if re.fullmatch(r"[/_.-]+", raw):
            if field == "data_notificacao":
                raise PdfAnalysisError("Há uma linha sem data de notificação preenchida.")
            values[field] = ""
            continue
        if not re.fullmatch(r"[0-9]{2}/[0-9]{2}/[0-9]{4}", raw):
            raise PdfAnalysisError("Há uma data fora do formato DD/MM/AAAA.")
        try:
            values[field] = datetime.strptime(raw, "%d/%m/%Y").date().isoformat()
        except ValueError as error:
            raise PdfAnalysisError("Há uma data inválida no boletim.") from error
    for field in ("contatos_identificados", "contatos_examinados"):
        if values[field] and not re.fullmatch(r"[0-9]{1,9}", values[field]):
            raise PdfAnalysisError("Há uma quantidade de contatos inválida.")
    registered, examined = values["contatos_identificados"], values["contatos_examinados"]
    if registered and examined and int(examined) > int(registered):
        raise PdfAnalysisError("Contatos examinados superam os identificados em uma linha.")
    try:
        validate_form_values("tuberculose", values)
    except ValueError as error:
        raise PdfAnalysisError(str(error)) from error
    # Keep categorical source strings; monthly_store attaches code and description.
    return values


def extract_tb_records(content: bytes) -> ExtractedBulletin:
    if len(content) > MAX_PDF_BYTES or not content.startswith(b"%PDF-"):
        raise PdfAnalysisError("Envie um PDF válido de até 20 MB.")
    try:
        document = pymupdf.open(stream=content, filetype="pdf")
    except (pymupdf.FileDataError, ValueError) as error:
        raise PdfAnalysisError("Não foi possível abrir o PDF.") from error
    with document:
        if document.needs_pass or not 1 <= document.page_count <= MAX_PDF_PAGES:
            raise PdfAnalysisError("PDF protegido, vazio ou com páginas além do limite.")
        records: list[dict[str, object]] = []
        seen: set[str] = set()
        units: dict[str, str] = {}
        for page in document:
            tables = page.find_tables().tables
            if len(tables) != 1:
                raise PdfAnalysisError("Cada página deve conter uma única tabela reconhecida.")
            # Only document headings before the first table can identify its unit/title.
            first_top = min(table.bbox[1] for table in tables)
            heading = page.get_text(clip=pymupdf.Rect(0, 0, page.rect.width, first_top))
            if "tuberculose" not in _normalize(heading):
                raise PdfAnalysisError("O cabeçalho não identifica um boletim de Tuberculose.")
            heading_lines = [line.strip() for line in heading.splitlines() if line.strip()]
            declarations = [i for i, line in enumerate(heading_lines)
                            if re.match(r"^unidade\s*:", line, flags=re.IGNORECASE)]
            if not declarations:
                raise PdfAnalysisError("A unidade deve estar identificada em todas as páginas.")
            unit = ""
            for position, start in enumerate(declarations):
                end = declarations[position + 1] if position + 1 < len(declarations) else len(heading_lines)
                declared = _unit_from_lines(heading_lines[start:end])
                if not declared:
                    raise PdfAnalysisError("Há uma declaração de unidade em branco no cabeçalho.")
                units.setdefault(_normalize(declared), declared)
                unit = declared
            if len(units) > 1:
                raise PdfAnalysisError("Importe um boletim de uma única unidade por vez.")
            for table in tables:
                # Cell rectangles preserve word spacing and avoid merged text-order artifacts.
                rows = [[page.get_textbox(pymupdf.Rect(cell)) if cell else ""
                         for cell in table_row.cells] for table_row in table.rows]
                first_data = next((i for i, row in enumerate(rows)
                                   if row and re.fullmatch(r"[0-9]{4,12}", _cell(row[0]))), None)
                if first_data is None or not _headers_match(rows[:first_data]):
                    raise PdfAnalysisError("Layout não reconhecido ou boletim sem registros individuais.")
                for row in rows[first_data:]:
                    if not any(_cell(value) for value in row):
                        continue
                    if len(row) != 16:
                        raise PdfAnalysisError("Há uma linha com colunas incompletas.")
                    values = _values(row)
                    identifier = values["numero_notificacao"]
                    if identifier in seen:
                        raise PdfAnalysisError("Há notificações duplicadas no PDF.")
                    seen.add(identifier)
                    values["unidade"] = unit
                    records.append({"patient_ref": identifier, "unit_ref": unit, "values": values})
                    if len(records) > MAX_IMPORT_RECORDS:
                        raise PdfAnalysisError("O boletim excede o limite de 1000 registros por importação.")
        if not records:
            raise PdfAnalysisError("Não há registros individuais para importar.")
        return ExtractedBulletin(next(iter(units.values())), tuple(records), (
            "Forma, baciloscopias e transferência não são importadas das células mescladas.",
            "Confira todos os registros. A leitura não valida regras clínicas nem a versão do SINAN.",
        ))
