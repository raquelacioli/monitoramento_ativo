import re
import unicodedata
from dataclasses import dataclass

import pymupdf

MAX_PDF_BYTES = 20 * 1024 * 1024
MAX_PDF_PAGES = 250
_ROW_START = re.compile(r"^\s*(\d{4,12})\s+(\d{1,2}/\d{1,2}/\d{2,4})\b")
_DATE = re.compile(r"\d{1,2}/\d{1,2}/\d{2,4}")


class PdfAnalysisError(ValueError):
    """Expected validation or extraction failure for an uploaded bulletin."""


@dataclass(frozen=True)
class UnitBulletinSummary:
    unit: str
    records: int
    contacts_registered: int
    contacts_examined: int
    pending_contact_records: int
    contact_records_to_check: int


@dataclass(frozen=True)
class BulletinSummary:
    pages: int
    agravo_confirmed: bool
    units: tuple[UnitBulletinSummary, ...]
    records_without_unit: int
    contact_columns_found: bool
    empty_bulletin: bool = False


@dataclass
class _MutableUnitSummary:
    records: int = 0
    contacts_registered: int = 0
    contacts_examined: int = 0
    pending_contact_records: int = 0
    contact_records_to_check: int = 0


def _normalize(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    return " ".join(
        "".join(char for char in decomposed if not unicodedata.combining(char)).split()
    )


def _unit_from_lines(lines: list[str]) -> str | None:
    for line_index, line in enumerate(lines):
        match = re.match(r"^unidade\s*:?\s*(.*)$", line, flags=re.IGNORECASE)
        if not match:
            continue
        value = match.group(1).strip(" :-")
        if not value and line_index + 1 < len(lines):
            value = lines[line_index + 1].strip()
        if value and not re.fullmatch(r"[_\s.-]+", value):
            return " ".join(value.split())[:180]
    return None


def _contact_columns(headers: list[str]) -> tuple[int | None, int | None]:
    registered_index = None
    examined_index = None
    for index, header in enumerate(headers):
        normalized = _normalize(header)
        if ("cont" in normalized and "exam" in normalized) or (
            "contato" in normalized and "examin" in normalized
        ):
            examined_index = index
        if (
            "cont" in normalized
            and ("reg" in normalized or "identific" in normalized)
            and "exam" not in normalized
        ):
            registered_index = index
    return registered_index, examined_index


def _has_bulletin_headers(text: str, selected_agravo: str) -> bool:
    if selected_agravo not in text or "notifica" not in text or "data" not in text:
        return False
    has_registered_contacts = "cont" in text and (
        "identif" in text or "reg" in text
    )
    has_examined_contacts = "cont" in text and "exam" in text
    return has_registered_contacts and has_examined_contacts


def _integer_cell(value: object) -> int | None:
    if value is None:
        return None
    match = re.fullmatch(r"\s*(\d+)\s*", str(value))
    return int(match.group(1)) if match else None


def _record_row(row: list[object]) -> bool:
    if not row:
        return False
    first_cell = "" if row[0] is None else str(row[0]).strip()
    if not re.fullmatch(r"\d{4,12}", first_cell):
        return False
    return any(_DATE.search("" if cell is None else str(cell)) for cell in row[1:])


def _table_rows(page: pymupdf.Page) -> tuple[list[list[object]], int | None, int | None]:
    rows: list[list[object]] = []
    registered_index: int | None = None
    examined_index: int | None = None

    for table in page.find_tables().tables:
        extracted = table.extract()
        if not extracted:
            continue
        first_record_index = next(
            (index for index, row in enumerate(extracted) if _record_row(row)),
            None,
        )
        if first_record_index is None:
            continue
        header_rows = extracted[:first_record_index]
        column_count = max((len(row) for row in header_rows), default=0)
        header = [
            " ".join(
                str(row[index]).strip()
                for row in header_rows
                if index < len(row) and row[index] is not None
            )
            for index in range(column_count)
        ]
        table_registered, table_examined = _contact_columns(header)
        if table_registered is None or table_examined is None:
            continue
        registered_index = table_registered
        examined_index = table_examined
        rows.extend(row for row in extracted[first_record_index:] if _record_row(row))

    return rows, registered_index, examined_index


def analyze_bulletin(content: bytes, selected_agravo: str) -> BulletinSummary:
    if len(content) > MAX_PDF_BYTES:
        raise PdfAnalysisError("O arquivo excede o limite de 20 MB.")
    if not content.startswith(b"%PDF-"):
        raise PdfAnalysisError("O arquivo enviado não parece ser um PDF válido.")
    if selected_agravo not in ("tuberculose", "hanseniase"):
        raise PdfAnalysisError("Selecione um agravo válido para a análise.")

    try:
        document = pymupdf.open(stream=content, filetype="pdf")
    except (pymupdf.FileDataError, ValueError) as error:
        raise PdfAnalysisError("Não foi possível abrir o PDF enviado.") from error

    try:
        if document.needs_pass:
            raise PdfAnalysisError("PDF protegido por senha não pode ser analisado.")
        if not document.page_count:
            raise PdfAnalysisError("O PDF não contém páginas.")
        if document.page_count > MAX_PDF_PAGES:
            raise PdfAnalysisError("O PDF excede o limite de 250 páginas.")

        unit_summaries: dict[str, _MutableUnitSummary] = {}
        records_without_unit = 0
        contact_columns_found = False
        first_page_text = ""
        current_unit: str | None = None
        observed_units: set[str] = set()

        for page_number, page in enumerate(document, start=1):
            page_text = page.get_text("text", sort=True)
            if page_number == 1:
                first_page_text = _normalize(page_text)
            lines = [line.strip() for line in page_text.splitlines() if line.strip()]
            page_unit = _unit_from_lines(lines)
            if page_unit:
                current_unit = page_unit
                observed_units.add(page_unit)

            table_rows, registered_index, examined_index = _table_rows(page)
            if table_rows:
                page_records = len(table_rows)
                contact_columns_found = True
                unit = current_unit
                for row in table_rows:
                    if registered_index >= len(row) or examined_index >= len(row):
                        if unit:
                            summary = unit_summaries.setdefault(unit, _MutableUnitSummary())
                            summary.contact_records_to_check += 1
                        continue
                    registered = _integer_cell(row[registered_index])
                    examined = _integer_cell(row[examined_index])
                    if registered is None or examined is None:
                        if unit:
                            summary = unit_summaries.setdefault(unit, _MutableUnitSummary())
                            summary.contact_records_to_check += 1
                    elif unit:
                        summary = unit_summaries.setdefault(unit, _MutableUnitSummary())
                        summary.contacts_registered += registered
                        summary.contacts_examined += examined
                        if registered > examined:
                            summary.pending_contact_records += 1

                if unit:
                    unit_summaries.setdefault(unit, _MutableUnitSummary()).records += page_records
                else:
                    records_without_unit += page_records
                continue

            text_records = sum(bool(_ROW_START.match(line)) for line in lines)
            if text_records:
                if current_unit:
                    unit_summaries.setdefault(current_unit, _MutableUnitSummary()).records += text_records
                else:
                    records_without_unit += text_records

        if not first_page_text.strip():
            raise PdfAnalysisError(
                "O PDF não contém texto selecionável. PDFs digitalizados exigem OCR, "
                "que não está habilitado nesta versão."
            )

        expected_keyword = "tuberculose" if selected_agravo == "tuberculose" else "hanseniase"
        other_keyword = "hanseniase" if selected_agravo == "tuberculose" else "tuberculose"
        if other_keyword in first_page_text and expected_keyword not in first_page_text:
            raise PdfAnalysisError(
                "O título do PDF parece indicar outro agravo. Volte e selecione o módulo correto."
            )
        agravo_confirmed = expected_keyword in first_page_text
        empty_bulletin = (
            not any(summary.records for summary in unit_summaries.values())
            and not records_without_unit
            and _has_bulletin_headers(first_page_text, expected_keyword)
        )
        if empty_bulletin:
            for unit in observed_units:
                unit_summaries.setdefault(unit, _MutableUnitSummary())
        if not unit_summaries and not records_without_unit and not empty_bulletin:
            raise PdfAnalysisError(
                "Não encontrei linhas de acompanhamento reconhecíveis no PDF. "
                "Confira se o boletim permite selecionar/copiar o texto."
            )
        contact_columns_found = contact_columns_found or empty_bulletin

        units = tuple(
            UnitBulletinSummary(
                unit=name,
                records=summary.records,
                contacts_registered=summary.contacts_registered,
                contacts_examined=summary.contacts_examined,
                pending_contact_records=summary.pending_contact_records,
                contact_records_to_check=summary.contact_records_to_check,
            )
            for name, summary in sorted(unit_summaries.items(), key=lambda item: item[0].casefold())
        )
        return BulletinSummary(
            pages=document.page_count,
            agravo_confirmed=agravo_confirmed,
            units=units,
            records_without_unit=records_without_unit,
            contact_columns_found=contact_columns_found,
            empty_bulletin=empty_bulletin,
        )
    finally:
        document.close()
