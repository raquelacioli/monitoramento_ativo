import os
import secrets
from dataclasses import replace
from typing import Literal

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from monitoramento.auth import (
    COOKIE_NAME,
    User,
    authenticate,
    change_password,
    create_session,
    create_user,
    deactivate_user,
    get_session,
    list_users,
    revoke_session,
    validate_csrf,
)
from monitoramento.bulletin_forms import BULLETIN_FIELDS, validate_form_values
from monitoramento.data import MODULES
from monitoramento.pdf_analysis import (
    MAX_PDF_BYTES,
    PdfAnalysisError,
    analyze_bulletin,
)
from monitoramento.tracking_store import (
    FOLLOWUP_STATUSES,
    load_module_updates,
    save_tracking_update,
)
from monitoramento.views import (
    render_bulletin_summary,
    render_home,
    render_login,
    render_module,
    render_password_change,
    render_user_admin,
    render_vigilance,
)

router = APIRouter()
LOGIN_CSRF_COOKIE = "monitoramento_login_csrf"
_COOKIE_SECURE = os.environ.get("MONITORAMENTO_COOKIE_SECURE") == "1"


def _session(request: Request) -> tuple[User, str] | None:
    return get_session(request.cookies.get(COOKIE_NAME))


def _login_location(user: User) -> str:
    if user.must_change_password:
        return "/trocar-senha"
    if user.role == "admin":
        return "/admin/usuarios"
    if user.role == "surveillance":
        return "/vigilancia"
    return "/tuberculose"


def _set_session_cookie(response: Response, token: str) -> None:
    from monitoramento.auth import SESSION_TTL_SECONDS

    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        secure=_COOKIE_SECURE,
        samesite="strict",
        path="/",
    )


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/", samesite="strict")


def _csrf_or_forbid(request: Request, submitted: str) -> tuple[User, str]:
    session = _session(request)
    if session is None:
        raise HTTPException(status_code=401, detail="Faça login para continuar.")
    if not validate_csrf(submitted, session[1]):
        raise HTTPException(status_code=403, detail="Token de segurança inválido.")
    return session


@router.get("/", response_class=HTMLResponse)
@router.get("/painel", response_class=HTMLResponse)
def home() -> HTMLResponse:
    return render_home()


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request) -> Response:
    session = _session(request)
    if session is not None:
        return RedirectResponse(_login_location(session[0]), status_code=303)
    csrf_token = secrets.token_urlsafe(32)
    response = render_login(csrf_token)
    response.set_cookie(
        LOGIN_CSRF_COOKIE,
        csrf_token,
        max_age=600,
        httponly=True,
        secure=_COOKIE_SECURE,
        samesite="strict",
        path="/login",
    )
    return response


@router.post("/login", response_class=HTMLResponse)
def login(
    request: Request,
    username: str = Form(..., max_length=80),
    password: str = Form(..., max_length=256),
    csrf_token: str = Form(..., max_length=128),
) -> Response:
    if not validate_csrf(csrf_token, request.cookies.get(LOGIN_CSRF_COOKIE)):
        raise HTTPException(status_code=403, detail="Token de segurança inválido.")
    user = authenticate(username, password)
    if user is None:
        response = render_login(csrf_token, "Usuário ou senha inválidos.")
        response.status_code = 401
        response.set_cookie(
            LOGIN_CSRF_COOKIE,
            csrf_token,
            max_age=600,
            httponly=True,
            secure=_COOKIE_SECURE,
            samesite="strict",
            path="/login",
        )
        return response

    token, _csrf = create_session(user.id)
    response = RedirectResponse(_login_location(user), status_code=303)
    _set_session_cookie(response, token)
    response.delete_cookie(LOGIN_CSRF_COOKIE, path="/login", samesite="strict")
    return response


@router.post("/logout")
def logout(request: Request, csrf_token: str = Form(..., max_length=128)) -> Response:
    _csrf_or_forbid(request, csrf_token)
    revoke_session(request.cookies.get(COOKIE_NAME))
    response = RedirectResponse("/login", status_code=303)
    _clear_session_cookie(response)
    return response


@router.get("/trocar-senha", response_class=HTMLResponse)
def password_change_page(request: Request) -> Response:
    session = _session(request)
    if session is None:
        return RedirectResponse("/login", status_code=303)
    return render_password_change(session[1], forced=session[0].must_change_password)


@router.post("/trocar-senha", response_class=HTMLResponse)
def password_change(
    request: Request,
    csrf_token: str = Form(..., max_length=128),
    password: str = Form(..., min_length=12, max_length=256),
    confirmation: str = Form(..., min_length=12, max_length=256),
) -> Response:
    user, _ = _csrf_or_forbid(request, csrf_token)
    if password != confirmation:
        return render_password_change(
            _session(request)[1], "As senhas não conferem.", user.must_change_password
        )
    try:
        change_password(user.id, password)
    except ValueError as error:
        return render_password_change(
            _session(request)[1], str(error), user.must_change_password
        )
    token, _csrf = create_session(user.id)
    response = RedirectResponse(
        _login_location(replace(user, must_change_password=False)),
        status_code=303,
    )
    _set_session_cookie(response, token)
    return response


@router.get("/admin/usuarios", response_class=HTMLResponse)
def user_admin_page(request: Request) -> Response:
    session = _session(request)
    if session is None:
        return RedirectResponse("/login", status_code=303)
    user, csrf_token = session
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Acesso restrito ao administrador.")
    if user.must_change_password:
        return RedirectResponse("/trocar-senha", status_code=303)
    return render_user_admin(list_users(), csrf_token)


@router.post("/admin/usuarios", response_class=HTMLResponse)
def add_user(
    request: Request,
    csrf_token: str = Form(..., max_length=128),
    username: str = Form(..., max_length=80),
    role: str = Form(..., max_length=20),
    unit: str = Form(default="", max_length=180),
    password: str = Form(..., min_length=12, max_length=256),
) -> Response:
    user, csrf = _csrf_or_forbid(request, csrf_token)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Acesso restrito ao administrador.")
    try:
        create_user(username, password, role, unit)
    except ValueError as error:
        return render_user_admin(list_users(), csrf, str(error))
    return render_user_admin(list_users(), csrf, success="Conta criada. A pessoa deverá trocar a senha no primeiro acesso.")


@router.post("/admin/usuarios/{user_id}/desativar", response_class=HTMLResponse)
def disable_user(
    user_id: int,
    request: Request,
    csrf_token: str = Form(..., max_length=128),
) -> Response:
    user, csrf = _csrf_or_forbid(request, csrf_token)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Acesso restrito ao administrador.")
    try:
        deactivate_user(user_id, user.id)
    except ValueError as error:
        return render_user_admin(list_users(), csrf, str(error))
    return render_user_admin(list_users(), csrf, success="Conta desativada e sessões encerradas.")


@router.get("/vigilancia", response_class=HTMLResponse)
def vigilance(request: Request) -> Response:
    session = _session(request)
    if session is None:
        return RedirectResponse("/login", status_code=303)
    user, csrf_token = session
    if user.must_change_password:
        return RedirectResponse("/trocar-senha", status_code=303)
    if user.role not in {"surveillance", "admin"}:
        raise HTTPException(status_code=403, detail="Acesso restrito à Vigilância.")
    return render_vigilance(csrf_token=csrf_token, username=user.username)


def _render_filtered_module(
    module_key: str,
    search: str,
    unit: str,
    followup_status: str,
    month: str,
    request: Request,
    saved: bool = False,
) -> Response:
    session = _session(request)
    if session is None:
        return RedirectResponse("/login", status_code=303)
    user, csrf_token = session
    if user.must_change_password:
        return RedirectResponse("/trocar-senha", status_code=303)
    if user.role == "admin":
        return RedirectResponse("/admin/usuarios", status_code=303)
    if user.role not in {"unit", "surveillance"}:
        raise HTTPException(status_code=403, detail="Perfil de acesso inválido.")

    module = load_module_updates(MODULES[module_key])
    selected_unit = user.unit if user.role == "unit" else unit
    normalized_search = search.casefold().strip()
    filtered = tuple(
        patient
        for patient in module.patients
        if (not normalized_search or normalized_search in patient.identifier.casefold())
        and (not selected_unit or patient.unit.casefold() == selected_unit.casefold())
        and (not followup_status or patient.followup_status == followup_status)
        and (not month or patient.month_reference == month)
    )
    return render_module(
        module,
        filtered,
        search,
        selected_unit or "",
        followup_status,
        month,
        saved,
        csrf_token,
        editable=user.role == "unit",
        username=user.username,
    )


@router.get("/tuberculose", response_class=HTMLResponse)
def tuberculose(
    request: Request,
    search: str = Query(default="", max_length=80),
    unit: str = Query(default="", max_length=100),
    followup_status: str = Query(default="", max_length=80),
    month: str = Query(default="", max_length=30),
    saved: bool = Query(default=False),
) -> Response:
    return _render_filtered_module(
        "tuberculose", search, unit, followup_status, month, request, saved
    )


@router.get("/hanseniase", response_class=HTMLResponse)
def hanseniase(
    request: Request,
    search: str = Query(default="", max_length=80),
    unit: str = Query(default="", max_length=100),
    followup_status: str = Query(default="", max_length=80),
    month: str = Query(default="", max_length=30),
    saved: bool = Query(default=False),
) -> Response:
    return _render_filtered_module(
        "hanseniase", search, unit, followup_status, month, request, saved
    )


@router.post("/api/acompanhamento/{agravo}/{record_id}")
async def update_tracking(
    agravo: Literal["tuberculose", "hanseniase"],
    record_id: str,
    request: Request,
) -> Response:
    session = _session(request)
    if session is None:
        raise HTTPException(status_code=401, detail="Faça login para continuar.")
    user, csrf = session
    if user.role != "unit":
        raise HTTPException(status_code=403, detail="Somente a unidade pode editar registros.")
    if user.must_change_password:
        raise HTTPException(status_code=403, detail="Altere a senha antes de continuar.")

    form = await request.form(max_files=0, max_fields=64)
    csrf_value = form.get("csrf_token")
    if not isinstance(csrf_value, str) or not validate_csrf(csrf_value, csrf):
        raise HTTPException(status_code=403, detail="Token de segurança inválido.")
    module = MODULES[agravo]
    patient = next(
        (item for item in module.patients if item.identifier == record_id),
        None,
    )
    if patient is None:
        raise HTTPException(status_code=404, detail="Registro demonstrativo não encontrado.")
    if patient.unit.casefold() != (user.unit or "").casefold():
        raise HTTPException(status_code=403, detail="Registro fora da unidade vinculada.")

    allowed_keys = {
        "csrf_token",
        "followup_status",
        "pending_items",
        "observation",
        *(field.key for field in BULLETIN_FIELDS[agravo]),
    }
    if set(form.keys()) - allowed_keys:
        raise HTTPException(status_code=422, detail="O formulário contém campos desconhecidos.")
    try:
        followup_status = str(form.get("followup_status", ""))
        if followup_status not in FOLLOWUP_STATUSES:
            raise ValueError("Selecione uma situação de acompanhamento válida.")
        values = {
            field.key: str(form.get(field.key, ""))
            for field in BULLETIN_FIELDS[agravo]
        }
        validated_values = validate_form_values(agravo, values)
        contacts_registered = int(validated_values["contatos_identificados"] or "0")
        contacts_examined = int(validated_values["contatos_examinados"] or "0")
        save_tracking_update(
            agravo=agravo,
            record_id=record_id,
            followup_status=followup_status,
            contacts_registered=contacts_registered,
            contacts_examined=contacts_examined,
            pending_items=str(form.get("pending_items", "")),
            observation=str(form.get("observation", "")),
            form_values=validated_values,
        )
    except (TypeError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return RedirectResponse(url=f"/{agravo}?saved=1", status_code=303)


@router.post("/api/boletins/analisar")
def analyze_bulletin_upload(
    request: Request,
    csrf_token: str = Form(..., max_length=128),
    agravo: Literal["tuberculose", "hanseniase"] = Form(...),
    boletim: UploadFile = File(...),
) -> HTMLResponse:
    user, csrf = _csrf_or_forbid(request, csrf_token)
    if user.role not in {"unit", "surveillance"}:
        raise HTTPException(status_code=403, detail="Perfil sem permissão para analisar boletins.")
    try:
        content = boletim.file.read(MAX_PDF_BYTES + 1)
        report = analyze_bulletin(content, agravo)
    except PdfAnalysisError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    finally:
        boletim.file.close()

    if user.role == "unit":
        unit_matches = tuple(
            unit for unit in report.units
            if unit.unit.casefold() == (user.unit or "").casefold()
        )
        if not unit_matches and (not report.empty_bulletin or report.units):
            raise HTTPException(
                status_code=422,
                detail="O boletim não corresponde à unidade vinculada à sua conta.",
            )
        report = replace(report, units=unit_matches, records_without_unit=0)
    return render_bulletin_summary(agravo, report, csrf_token=csrf)


@router.get("/api/status")
def status() -> dict[str, str | list[str]]:
    return {
        "sistema": "Monitoramento Ativo de Tuberculose e Hanseníase",
        "status": "Funcionando",
        "modulos": ["Tuberculose", "Hanseníase"],
        "dados": "Demonstrativos; campos ainda não validados oficialmente",
    }
