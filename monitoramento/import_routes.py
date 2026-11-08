import sqlite3

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response, RedirectResponse

from monitoramento.auth import list_users
from monitoramento.bulletin_import import extract_tb_records
from monitoramento.import_previews import PendingImport, preview_store
from monitoramento.import_views import render_import_form, render_import_preview, render_import_result
from monitoramento.monthly_store import import_monthly_records
from monitoramento.monthly_workflow import Competence
from monitoramento.pdf_analysis import MAX_PDF_BYTES, _normalize
from monitoramento.routes import _csrf_or_forbid, _session

router = APIRouter()


def _units() -> tuple[str, ...]:
    units = {}
    for account in list_users():
        if account.active and account.role == "unit" and account.unit:
            units.setdefault(_normalize(account.unit), account.unit)
    return tuple(sorted(units.values(), key=str.casefold))


def _surveillance(request: Request, csrf: str):
    user, token = _csrf_or_forbid(request, csrf)
    if user.role != "surveillance":
        raise HTTPException(status_code=403, detail="Somente a Vigilância pode importar boletins.")
    return user, token


@router.get("/vigilancia/importar")
def import_page(request: Request) -> Response:
    session = _session(request)
    if session is None:
        return RedirectResponse("/login", status_code=303)
    user, csrf = session
    if user.must_change_password:
        return RedirectResponse("/trocar-senha", status_code=303)
    if user.role != "surveillance":
        raise HTTPException(status_code=403, detail="Somente a Vigilância pode importar boletins.")
    return render_import_form(_units(), csrf)


@router.post("/api/boletins/previsualizar")
def preview_import(
    request: Request,
    csrf_token: str = Form(..., max_length=128),
    competence: str = Form(..., max_length=7),
    unit: str = Form(..., max_length=180),
    boletim: UploadFile = File(...),
) -> Response:
    try:
        user, csrf = _surveillance(request, csrf_token)
        units = _units()
        try:
            competence = str(Competence.parse(competence))
            selected_unit = next((value for value in units if _normalize(value) == _normalize(unit)), None)
            if selected_unit is None:
                raise ValueError("Selecione uma unidade cadastrada com conta ativa.")
            content = boletim.file.read(MAX_PDF_BYTES + 1)
            bulletin = extract_tb_records(content)
            if _normalize(bulletin.unit) != _normalize(selected_unit):
                raise ValueError("A unidade do PDF não corresponde à unidade selecionada.")
            token = preview_store.create(owner_id=user.id, competence=competence,
                                         unit=selected_unit, content=content, bulletin=bulletin)
        except ValueError as error:
            return render_import_form(units, csrf, error=str(error), status_code=422)
        return render_import_preview(preview_store.get(token, owner_id=user.id), token, csrf)
    finally:
        boletim.file.close()


@router.post("/api/boletins/confirmar")
def confirm_import(
    request: Request,
    csrf_token: str = Form(..., max_length=128),
    preview_token: str = Form(..., min_length=20, max_length=128),
) -> Response:
    user, csrf = _surveillance(request, csrf_token)
    units = _units()

    def persist(item: PendingImport):
        if item.unit not in units:
            raise ValueError("A unidade não possui mais conta ativa. Confira o cadastro e envie novamente.")
        records = []
        for record in item.bulletin.records:
            records.append({**record, "unit_ref": item.unit,
                            "values": {**record["values"], "unidade": item.unit}})
        result = import_monthly_records(
            agravo="tuberculose", competence=item.competence, source_content=item.content,
            imported_by=user.username, records=records, unit_coverage=(item.unit,), protect_workflow=True,
        )
        return result, item

    try:
        result, item = preview_store.consume(preview_token, owner_id=user.id, importer=persist)
    except ValueError as error:
        return render_import_form(units, csrf, error=str(error), status_code=422)
    except sqlite3.Error as error:
        raise HTTPException(status_code=503, detail="Banco indisponível. Tente confirmar novamente.") from error
    return render_import_result(result, item, csrf)


@router.post("/api/boletins/cancelar")
def cancel_import(
    request: Request,
    csrf_token: str = Form(..., max_length=128),
    preview_token: str = Form(..., min_length=20, max_length=128),
) -> Response:
    user, csrf = _surveillance(request, csrf_token)
    try:
        preview_store.consume(preview_token, owner_id=user.id, importer=lambda item: None)
    except ValueError as error:
        return render_import_form(_units(), csrf, error=str(error), status_code=422)
    return RedirectResponse("/vigilancia/importar", status_code=303,
                            headers={"Cache-Control": "no-store"})
