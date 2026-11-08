import logging
import os
import secrets
import smtplib
from dataclasses import replace
from datetime import date
from typing import Literal
from urllib.parse import quote, urlencode

from fastapi import (
    APIRouter,
    BackgroundTasks,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from dotenv import load_dotenv

from monitoramento.auth import (
    COOKIE_NAME,
    User,
    admin_reset_user_password,
    allow_password_reset_attempt,
    authenticate,
    change_password,
    create_session,
    create_user,
    delete_user,
    deactivate_user,
    get_session,
    invalidate_password_reset_token,
    list_users,
    revoke_session,
    reset_password_with_token,
    issue_password_reset_token,
    set_user_recovery_email,
    validate_csrf,
)
from monitoramento.bulletin_forms import (
    BULLETIN_FIELDS,
    monthly_editable_field_keys,
    prepare_updated_values,
    validate_form_values,
)
from monitoramento.data import MODULES
from monitoramento.monthly_workflow import Competence
from monitoramento.monthly_store import (
    close_monthly_competence,
    compare_monthly_record_fields,
    create_manual_followup,
    ensure_contact_followup,
    get_monthly_followup,
    get_monthly_followup_history,
    get_monthly_monitoring_deadline,
    get_monthly_competence_state,
    get_monthly_unit_confirmation_history,
    get_monthly_record,
    get_record_revisions,
    list_monthly_competences,
    list_monthly_followups,
    list_monthly_units,
    get_monthly_vigilance_notes,
    list_monthly_records,
    MonthlyFollowup,
    MonthlyRecord,
    monthly_followup_metrics,
    monthly_unit_monitoring,
    open_monthly_competence,
    review_monthly_followup,
    review_monthly_record,
    save_monthly_followup_response,
    submit_monthly_record,
    update_monthly_draft,
    set_monthly_monitoring_deadline,
    update_monthly_unit_confirmation,
)
from monitoramento.pdf_analysis import (
    MAX_PDF_BYTES,
    PdfAnalysisError,
    analyze_bulletin,
)
from monitoramento.recovery_mail import (
    RecoveryMailConfigurationError,
    send_password_reset_email,
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
    render_monthly_followup,
    render_monthly_followup_dashboard,
    render_monthly_monitoring,
    render_password_change,
    render_password_recovery,
    render_password_reset,
    render_user_admin,
    render_vigilance,
)

router = APIRouter()
load_dotenv()
LOGIN_CSRF_COOKIE = "monitoramento_login_csrf"
RECOVERY_CSRF_COOKIE = "monitoramento_recovery_csrf"
_COOKIE_SECURE = os.environ.get("MONITORAMENTO_COOKIE_SECURE") == "1"
_logger = logging.getLogger(__name__)


def _session(request: Request) -> tuple[User, str] | None:
    session = get_session(request.cookies.get(COOKIE_NAME))
    if (
        session is not None
        and session[0].must_change_password
        and request.method not in {"GET", "HEAD", "OPTIONS"}
        and request.url.path not in {"/trocar-senha", "/logout", "/login"}
    ):
        raise HTTPException(status_code=403, detail="Altere a senha antes de continuar.")
    return session


def _editable_followup_record(
    followup: MonthlyFollowup,
    unit_ref: str,
) -> MonthlyRecord | None:
    for agravo, competence in list_monthly_competences():
        if agravo != followup.agravo:
            continue
        record = get_monthly_record(
            agravo=agravo,
            patient_ref=followup.patient_ref,
            competence=competence,
        )
        if (
            record is not None
            and record.unit_ref.casefold() == unit_ref.casefold()
            and get_monthly_competence_state(
                agravo=agravo,
                competence=competence,
            ) == "open"
        ):
            return record
    return None


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


def _set_recovery_csrf(response: Response, token: str, path: str) -> None:
    response.set_cookie(
        RECOVERY_CSRF_COOKIE,
        token,
        max_age=600,
        httponly=True,
        secure=_COOKIE_SECURE,
        samesite="strict",
        path=path,
    )


def _anonymous_csrf_matches(request: Request, submitted: str) -> bool:
    return validate_csrf(submitted, request.cookies.get(RECOVERY_CSRF_COOKIE))


def _requester_address(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _deliver_password_reset_email(recipient: str, token: str) -> None:
    try:
        send_password_reset_email(recipient, token)
    except (
        RecoveryMailConfigurationError,
        smtplib.SMTPException,
        OSError,
        ValueError,
    ):
        invalidate_password_reset_token(token)
        _logger.warning("Envio de recuperação de senha indisponível.")


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


def _login_form_response(error: str = "", status_code: int = 200) -> Response:
    csrf_token = secrets.token_urlsafe(32)
    response = render_login(csrf_token, error)
    response.status_code = status_code
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


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request) -> Response:
    session = _session(request)
    if session is not None:
        return RedirectResponse(_login_location(session[0]), status_code=303)
    return _login_form_response()


@router.post("/login", response_class=HTMLResponse)
def login(
    request: Request,
    username: str = Form(..., max_length=80),
    password: str = Form(..., max_length=256),
    csrf_token: str = Form(..., max_length=128),
) -> Response:
    if not validate_csrf(csrf_token, request.cookies.get(LOGIN_CSRF_COOKIE)):
        return _login_form_response(
            "Não foi possível validar esta tentativa. A página pode ter expirado. "
            "Tente novamente. Abra o login no Edge ou Chrome se estiver usando o navegador do VS Code.",
            status_code=403,
        )
    user = authenticate(username, password)
    if user is None:
        return _login_form_response("Usuário ou senha inválidos.", status_code=401)

    token, _csrf = create_session(user.id)
    response = RedirectResponse(_login_location(user), status_code=303)
    _set_session_cookie(response, token)
    response.delete_cookie(LOGIN_CSRF_COOKIE, path="/login", samesite="strict")
    return response


@router.get("/recuperar-senha", response_class=HTMLResponse)
def password_recovery_page() -> Response:
    csrf_token = secrets.token_urlsafe(32)
    response = render_password_recovery(csrf_token)
    _set_recovery_csrf(response, csrf_token, "/recuperar-senha")
    return response


@router.post("/recuperar-senha", response_class=HTMLResponse)
def request_password_recovery(
    request: Request,
    background_tasks: BackgroundTasks,
    email: str = Form(..., max_length=254),
    csrf_token: str = Form(..., max_length=128),
) -> Response:
    if not _anonymous_csrf_matches(request, csrf_token):
        raise HTTPException(status_code=403, detail="Token de segurança inválido.")

    try:
        issued = issue_password_reset_token(email, _requester_address(request))
    except ValueError:
        issued = None
    if issued is not None:
        token, recipient = issued
        background_tasks.add_task(_deliver_password_reset_email, recipient, token)

    response = render_password_recovery(csrf_token, submitted=True)
    _set_recovery_csrf(response, csrf_token, "/recuperar-senha")
    return response


@router.get("/redefinir-senha", response_class=HTMLResponse)
def password_reset_page() -> Response:
    csrf_token = secrets.token_urlsafe(32)
    response = render_password_reset(csrf_token)
    _set_recovery_csrf(response, csrf_token, "/redefinir-senha")
    return response


@router.post("/redefinir-senha", response_class=HTMLResponse)
def submit_password_reset(
    request: Request,
    token: str = Form(default="", max_length=128),
    csrf_token: str = Form(..., max_length=128),
    password: str = Form(..., min_length=12, max_length=256),
    confirmation: str = Form(..., min_length=12, max_length=256),
) -> Response:
    if not _anonymous_csrf_matches(request, csrf_token):
        raise HTTPException(status_code=403, detail="Token de segurança inválido.")
    if not allow_password_reset_attempt(_requester_address(request)):
        return render_password_reset(
            csrf_token,
            error="Muitas tentativas. Aguarde antes de tentar novamente.",
        )
    if password != confirmation:
        return render_password_reset(
            csrf_token,
            token,
            "As senhas não conferem.",
        )
    try:
        reset = reset_password_with_token(token, password)
    except ValueError as error:
        return render_password_reset(csrf_token, token, str(error))
    if not reset:
        return render_password_reset(
            csrf_token,
            error="O link é inválido, expirou ou já foi utilizado. Solicite outro link.",
        )
    response = render_password_reset(csrf_token, success=True)
    response.delete_cookie(
        RECOVERY_CSRF_COOKIE,
        path="/redefinir-senha",
        samesite="strict",
    )
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
    return render_user_admin(list_users(), csrf_token, actor_id=user.id)


@router.post("/admin/usuarios", response_class=HTMLResponse)
def add_user(
    request: Request,
    csrf_token: str = Form(..., max_length=128),
    username: str = Form(..., max_length=80),
    role: str = Form(..., max_length=20),
    unit: str = Form(default="", max_length=180),
    email: str = Form(default="", max_length=254),
    password: str = Form(..., min_length=12, max_length=256),
) -> Response:
    user, csrf = _csrf_or_forbid(request, csrf_token)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Acesso restrito ao administrador.")
    try:
        create_user(username, password, role, unit, email)
    except ValueError as error:
        return render_user_admin(list_users(), csrf, str(error), actor_id=user.id)
    return render_user_admin(
        list_users(),
        csrf,
        success="Conta criada. A pessoa deverá trocar a senha no primeiro acesso.",
        actor_id=user.id,
    )


@router.post("/admin/usuarios/{user_id}/email", response_class=HTMLResponse)
def update_user_recovery_email(
    user_id: int,
    request: Request,
    csrf_token: str = Form(..., max_length=128),
    email: str = Form(default="", max_length=254),
) -> Response:
    user, csrf = _csrf_or_forbid(request, csrf_token)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Acesso restrito ao administrador.")
    try:
        set_user_recovery_email(user_id, email)
    except ValueError as error:
        return render_user_admin(list_users(), csrf, str(error), actor_id=user.id)
    return render_user_admin(
        list_users(),
        csrf,
        success="E-mail de recuperação atualizado. Confirme com a pessoa que o endereço é autorizado e acessível.",
        actor_id=user.id,
    )


@router.post("/admin/usuarios/{user_id}/senha", response_class=HTMLResponse)
def reset_user_password(
    user_id: int,
    request: Request,
    csrf_token: str = Form(..., max_length=128),
    password: str = Form(..., min_length=12, max_length=256),
    confirmation: str = Form(..., min_length=12, max_length=256),
) -> Response:
    user, csrf = _csrf_or_forbid(request, csrf_token)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Acesso restrito ao administrador.")
    if password != confirmation:
        return render_user_admin(
            list_users(),
            csrf,
            "As senhas não conferem; nenhuma alteração foi feita.",
            actor_id=user.id,
        )
    try:
        admin_reset_user_password(user_id, password)
    except ValueError as error:
        return render_user_admin(list_users(), csrf, str(error), actor_id=user.id)
    return render_user_admin(
        list_users(),
        csrf,
        success=(
            "Senha temporária definida. A conta deverá escolher uma nova senha "
            "no próximo acesso; as sessões anteriores foram encerradas."
        ),
        actor_id=user.id,
    )


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
        return render_user_admin(list_users(), csrf, str(error), actor_id=user.id)
    return render_user_admin(
        list_users(),
        csrf,
        success="Conta desativada e sessões encerradas.",
        actor_id=user.id,
    )


@router.post("/admin/usuarios/{user_id}/excluir", response_class=HTMLResponse)
def remove_user(
    user_id: int,
    request: Request,
    csrf_token: str = Form(..., max_length=128),
) -> Response:
    user, csrf = _csrf_or_forbid(request, csrf_token)
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Acesso restrito ao administrador.")
    try:
        delete_user(user_id, user.id)
    except ValueError as error:
        return render_user_admin(list_users(), csrf, str(error), actor_id=user.id)
    return render_user_admin(
        list_users(),
        csrf,
        success=(
            "Conta excluída definitivamente. Os registros históricos de "
            "acompanhamento foram preservados."
        ),
        actor_id=user.id,
    )


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
    competencies = list_monthly_competences()
    records = tuple(
        record
        for agravo, competence in competencies
        for record in list_monthly_records(agravo=agravo, competence=competence)
    )
    for record in records:
        ensure_contact_followup(record)
    return render_vigilance(
        csrf_token=csrf_token,
        username=user.username,
        followups=list_monthly_followups(),
        followup_metrics=monthly_followup_metrics(),
    )


@router.get("/comunicacao", response_class=HTMLResponse)
def monthly_followup_dashboard(
    request: Request,
    agravo: str = Query(default="", max_length=30),
    competence: str = Query(default="", max_length=7),
    state: str = Query(default="", max_length=40),
    unit: str = Query(default="", max_length=100),
) -> Response:
    session = _session(request)
    if session is None:
        return RedirectResponse("/login", status_code=303)
    user, csrf = session
    if user.must_change_password:
        return RedirectResponse("/trocar-senha", status_code=303)
    if user.role not in {"unit", "surveillance", "admin"}:
        raise HTTPException(status_code=403, detail="Perfil sem acesso às comunicações.")
    if agravo and agravo not in {"tuberculose", "hanseniase"}:
        raise HTTPException(status_code=422, detail="Agravo inválido.")
    if state and state not in {
        "automatic_suggestion", "awaiting_unit", "responded", "under_review",
        "needs_more_info", "resolved",
    }:
        raise HTTPException(status_code=422, detail="Situação inválida.")
    if competence:
        try:
            competence = str(Competence.parse(competence))
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    competencies = list_monthly_competences()
    for item_agravo, item_competence in competencies:
        if agravo and item_agravo != agravo:
            continue
        if competence and item_competence != competence:
            continue
        for record in list_monthly_records(
            agravo=item_agravo,
            competence=item_competence,
            unit_ref=user.unit if user.role == "unit" else None,
        ):
            ensure_contact_followup(record)

    selected_unit = user.unit if user.role == "unit" else unit
    followups = list_monthly_followups(
        agravo=agravo or None,
        competence=competence or None,
        unit_ref=selected_unit or None,
        states={state} if state else None,
        include_automatic=user.role != "unit",
    )
    return render_monthly_followup_dashboard(
        followups=followups,
        csrf_token=csrf,
        role=user.role,
        username=user.username,
        selected_agravo=agravo,
        selected_competence=competence,
        selected_state=state,
        selected_unit=selected_unit or "",
        metrics=monthly_followup_metrics(
            agravo=agravo or None,
            competence=competence or None,
            unit_ref=selected_unit or None,
            state=state or None,
            include_automatic=user.role != "unit",
        ),
    )


@router.get("/comunicacao/{followup_id}", response_class=HTMLResponse)
def monthly_followup_detail(followup_id: int, request: Request) -> Response:
    session = _session(request)
    if session is None:
        return RedirectResponse("/login", status_code=303)
    user, csrf = session
    if user.must_change_password:
        return RedirectResponse("/trocar-senha", status_code=303)
    if user.role not in {"unit", "surveillance", "admin"}:
        raise HTTPException(status_code=403, detail="Perfil sem acesso às comunicações.")
    followup = get_monthly_followup(
        followup_id=followup_id,
        unit_ref=user.unit if user.role == "unit" else None,
    )
    if followup is None:
        raise HTTPException(status_code=404, detail="Comunicação não encontrada.")
    field_definition = next(
        (
            field for field in BULLETIN_FIELDS[followup.agravo]
            if field.key == followup.field_key
        ),
        None,
    )
    current_record = get_monthly_record(
        agravo=followup.agravo,
        patient_ref=followup.patient_ref,
        competence=followup.competence,
    )
    field_record = _editable_followup_record(followup, followup.unit_ref)
    if field_record is None:
        field_record = current_record
    previous_record = get_monthly_record(
        agravo=followup.agravo,
        patient_ref=followup.patient_ref,
        competence=str(Competence.parse(field_record.competence).previous()),
    )
    if user.role == "unit" and current_record is not None:
        if current_record.unit_ref.casefold() != (user.unit or "").casefold():
            raise HTTPException(status_code=404, detail="Comunicação não encontrada.")
    if (
        user.role == "unit"
        and previous_record is not None
        and previous_record.unit_ref.casefold() != (user.unit or "").casefold()
    ):
        previous_record = None
    return render_monthly_followup(
        followup=followup,
        history=get_monthly_followup_history(followup_id),
        role=user.role,
        csrf_token=csrf,
        username=user.username,
        field_definition=field_definition,
        previous_value=(
            previous_record.values.get(followup.field_key)
            if previous_record is not None and followup.field_key else None
        ),
        current_value=(
            field_record.values.get(followup.field_key)
            if field_record is not None and followup.field_key else None
        ),
        field_competence=field_record.competence if field_record is not None else "",
        can_edit_field=(
            user.role == "unit"
            and bool(followup.field_key)
            and field_record is not None
        ),
    )


@router.post("/comunicacao/manual")
async def create_manual_monthly_followup(request: Request) -> Response:
    session = _session(request)
    if session is None:
        raise HTTPException(status_code=401, detail="Faça login para continuar.")
    user, csrf = session
    if user.role != "surveillance":
        raise HTTPException(status_code=403, detail="Somente a Vigilância pode criar comunicações.")
    if user.must_change_password:
        raise HTTPException(status_code=403, detail="Altere a senha antes de continuar.")
    form = await request.form(max_files=0, max_fields=8)
    csrf_value = form.get("csrf_token")
    if not isinstance(csrf_value, str) or not validate_csrf(csrf_value, csrf):
        raise HTTPException(status_code=403, detail="Token de segurança inválido.")
    agravo, competence, patient_ref = (
        form.get("agravo"), form.get("competence"), form.get("patient_ref")
    )
    text, priority = form.get("text"), form.get("priority", "normal")
    field_key = form.get("field_key", "")
    if (
        agravo not in {"tuberculose", "hanseniase"}
        or not isinstance(competence, str)
        or not isinstance(patient_ref, str)
        or not isinstance(text, str)
        or not isinstance(priority, str)
        or not isinstance(field_key, str)
    ):
        raise HTTPException(status_code=422, detail="Dados da comunicação inválidos.")
    try:
        competence = str(Competence.parse(competence))
        record = next(
            (
                item for item in list_monthly_records(
                    agravo=agravo, competence=competence
                )
                if item.patient_ref == patient_ref.strip()
            ),
            None,
        )
        if record is None:
            raise ValueError("Registro mensal não encontrado.")
        followup = create_manual_followup(
            agravo=agravo,
            patient_ref=patient_ref.strip(),
            competence=competence,
            unit_ref=record.unit_ref,
            actor=user.username,
            text=text,
            field_key=field_key,
            priority=priority,
        )
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return RedirectResponse(f"/comunicacao/{followup.id}", status_code=303)


@router.post("/comunicacao/{followup_id}/revisar")
async def review_monthly_followup_route(followup_id: int, request: Request) -> Response:
    session = _session(request)
    if session is None:
        raise HTTPException(status_code=401, detail="Faça login para continuar.")
    user, csrf = session
    if user.role != "surveillance":
        raise HTTPException(status_code=403, detail="Somente a Vigilância pode revisar comunicações.")
    if user.must_change_password:
        raise HTTPException(status_code=403, detail="Altere a senha antes de continuar.")
    form = await request.form(max_files=0, max_fields=8)
    csrf_value = form.get("csrf_token")
    if not isinstance(csrf_value, str) or not validate_csrf(csrf_value, csrf):
        raise HTTPException(status_code=403, detail="Token de segurança inválido.")
    action, text, priority = form.get("action"), form.get("text"), form.get("priority", "normal")
    if not isinstance(action, str) or not isinstance(text, str) or not isinstance(priority, str):
        raise HTTPException(status_code=422, detail="Dados da revisão inválidos.")
    try:
        review_monthly_followup(
            followup_id=followup_id,
            actor=user.username,
            action=action,
            text=text,
            priority=priority,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return RedirectResponse(f"/comunicacao/{followup_id}", status_code=303)


@router.post("/comunicacao/{followup_id}/responder")
async def save_monthly_followup_response_route(
    followup_id: int, request: Request
) -> Response:
    session = _session(request)
    if session is None:
        raise HTTPException(status_code=401, detail="Faça login para continuar.")
    user, csrf = session
    if user.role != "unit":
        raise HTTPException(status_code=403, detail="Somente a unidade pode responder.")
    if user.must_change_password:
        raise HTTPException(status_code=403, detail="Altere a senha antes de continuar.")
    form = await request.form(max_files=0, max_fields=8)
    csrf_value = form.get("csrf_token")
    if not isinstance(csrf_value, str) or not validate_csrf(csrf_value, csrf):
        raise HTTPException(status_code=403, detail="Token de segurança inválido.")
    text, submit = form.get("text"), form.get("submit")
    if not isinstance(text, str) or submit not in {"draft", "submitted"}:
        raise HTTPException(status_code=422, detail="Dados da resposta inválidos.")
    try:
        saved = save_monthly_followup_response(
            followup_id=followup_id,
            unit_ref=user.unit or "",
            actor=user.username,
            text=text,
            submit=submit == "submitted",
        )
    except PermissionError as error:
        raise HTTPException(status_code=404, detail="Comunicação não encontrada.") from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return RedirectResponse(f"/comunicacao/{saved.id}", status_code=303)


@router.post("/comunicacao/{followup_id}/atualizar-campo")
async def update_followup_field(followup_id: int, request: Request) -> Response:
    session = _session(request)
    if session is None:
        raise HTTPException(status_code=401, detail="Faça login para continuar.")
    user, csrf = session
    if user.role != "unit":
        raise HTTPException(status_code=403, detail="Somente a unidade pode atualizar o campo.")
    if user.must_change_password:
        raise HTTPException(status_code=403, detail="Altere a senha antes de continuar.")
    followup = get_monthly_followup(
        followup_id=followup_id,
        unit_ref=user.unit or "",
    )
    if followup is None:
        raise HTTPException(status_code=404, detail="Comunicação não encontrada.")
    if not followup.field_key:
        raise HTTPException(status_code=422, detail="A comunicação não está vinculada a um campo.")
    form = await request.form(max_files=0, max_fields=4)
    csrf_value = form.get("csrf_token")
    if not isinstance(csrf_value, str) or not validate_csrf(csrf_value, csrf):
        raise HTTPException(status_code=403, detail="Token de segurança inválido.")
    if set(form.keys()) != {"csrf_token", followup.field_key}:
        raise HTTPException(status_code=422, detail="O formulário deve atualizar apenas o campo relacionado.")
    raw_value = form.get(followup.field_key)
    if not isinstance(raw_value, str):
        raise HTTPException(status_code=422, detail="Valor de campo inválido.")
    target_record = _editable_followup_record(followup, user.unit or "")
    if target_record is None:
        raise HTTPException(
            status_code=422,
            detail="Não há competência aberta da unidade para atualizar este campo.",
        )
    try:
        validated = validate_form_values(
            followup.agravo,
            {followup.field_key: raw_value},
        )
        update_monthly_draft(
            agravo=followup.agravo,
            patient_ref=followup.patient_ref,
            competence=target_record.competence,
            unit_ref=user.unit or "",
            actor=user.username,
            values=prepare_updated_values(followup.agravo, validated),
        )
    except PermissionError as error:
        raise HTTPException(status_code=404, detail="Registro mensal não encontrado.") from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return RedirectResponse(f"/comunicacao/{followup_id}", status_code=303)


def _known_units(agravo: str) -> tuple[str, ...]:
    units: dict[str, str] = {}
    for unit in list_monthly_units(agravo):
        if unit.strip():
            units.setdefault(unit.strip().casefold(), unit.strip())
    for user in list_users():
        if user.active and user.role == "unit" and user.unit and user.unit.strip():
            units.setdefault(user.unit.strip().casefold(), user.unit.strip())
    return tuple(sorted(units.values(), key=str.casefold))


@router.get("/monitoramento-mensal", response_class=HTMLResponse)
def monthly_unit_monitoring_page(
    request: Request,
    agravo: str = Query(default="", max_length=30),
    competence: str = Query(default="", max_length=7),
    unit: str = Query(default="", max_length=100),
    state: str = Query(default="", max_length=40),
    pending: bool = Query(default=False),
    silent: bool = Query(default=False),
    patient_state: str = Query(default="", max_length=30),
    saved: str = Query(default="", max_length=20),
) -> Response:
    session = _session(request)
    if session is None:
        return RedirectResponse("/login", status_code=303)
    user, csrf = session
    if user.must_change_password:
        return RedirectResponse("/trocar-senha", status_code=303)
    if user.role not in {"unit", "surveillance", "admin"}:
        raise HTTPException(status_code=403, detail="Perfil sem acesso ao monitoramento mensal.")
    if user.role == "unit" and not user.unit:
        raise HTTPException(status_code=403, detail="A conta não está vinculada a uma unidade.")
    if agravo and agravo not in {"tuberculose", "hanseniase"}:
        raise HTTPException(status_code=422, detail="Agravo inválido.")
    if state and state not in {
        "data_unavailable", "awaiting", "no_update", "partial", "complete",
        "silent_pending", "silent_confirmed", "reconciliation_required",
    }:
        raise HTTPException(status_code=422, detail="Situação de unidade inválida.")
    if patient_state and patient_state not in {
        "complete", "partial", "no_update", "awaiting",
    }:
        raise HTTPException(status_code=422, detail="Situação de paciente inválida.")
    all_competences = list_monthly_competences()
    available_competences = sorted(
        {
            comp for item_agravo, comp in all_competences
            if not agravo or item_agravo == agravo
        },
        reverse=True,
    )
    if competence:
        try:
            competence = str(Competence.parse(competence))
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
    elif available_competences:
        competence = available_competences[0]
    else:
        today = date.today()
        competence = str(Competence(today.year, today.month))
    if competence not in available_competences:
        available_competences.insert(0, competence)

    agravos = (agravo,) if agravo else ("tuberculose", "hanseniase")
    all_rows: list[dict[str, object]] = []
    for selected_agravo in agravos:
        selected_units = (user.unit,) if user.role == "unit" else _known_units(selected_agravo)
        for monthly_record in list_monthly_records(
            agravo=selected_agravo,
            competence=competence,
            unit_ref=user.unit if user.role == "unit" else None,
        ):
            ensure_contact_followup(monthly_record)
        all_rows.extend(
            monthly_unit_monitoring(
                agravo=selected_agravo,
                competence=competence,
                units=selected_units,
            )
        )
    scoped_units = user.unit if user.role == "unit" else unit
    if scoped_units:
        all_rows = [
            row for row in all_rows
            if str(row["unit_ref"]).casefold() == scoped_units.casefold()
        ]
    followups_by_patient: dict[tuple[str, str, str], list[MonthlyFollowup]] = {}
    for selected_agravo in agravos:
        for followup in list_monthly_followups(
            agravo=selected_agravo,
            unit_ref=user.unit if user.role == "unit" else None,
            include_automatic=user.role != "unit",
        ):
            followups_by_patient.setdefault(
                (
                    selected_agravo,
                    followup.patient_ref,
                    followup.unit_ref.casefold(),
                ), []
            ).append(followup)
    for row in all_rows:
        patient_communications = {}
        previous_competence = str(Competence.parse(str(row["competence"])).previous())
        for patient in row["patients"]:
            patient_ref = str(patient["patient_ref"])
            patient["can_respond"] = (
                user.role == "unit"
                and get_monthly_competence_state(
                    agravo=str(row["agravo"]),
                    competence=str(row["competence"]),
                ) == "open"
            )
            patient_communications[patient_ref] = tuple(
                followups_by_patient.get(
                    (
                        str(row["agravo"]),
                        patient_ref,
                        str(row["unit_ref"]).casefold(),
                    ),
                    (),
                )
            )
            current_record = get_monthly_record(
                agravo=str(row["agravo"]),
                patient_ref=patient_ref,
                competence=str(row["competence"]),
            )
            previous_record = get_monthly_record(
                agravo=str(row["agravo"]),
                patient_ref=patient_ref,
                competence=previous_competence,
            )
            if (
                user.role == "unit"
                and previous_record is not None
                and previous_record.unit_ref.casefold() != (user.unit or "").casefold()
            ):
                previous_record = None
            if current_record is not None:
                patient["current_values"] = current_record.values
                patient["updated_values"] = current_record.updated_values
                patient["can_edit"] = (
                    user.role == "unit"
                    and current_record.state in {"draft", "returned"}
                    and get_monthly_competence_state(
                        agravo=current_record.agravo,
                        competence=current_record.competence,
                    ) == "open"
                )
                patient["comparison"] = compare_monthly_record_fields(
                    current_record,
                    previous_record,
                )
                patient["revisions"] = get_record_revisions(
                    agravo=current_record.agravo,
                    patient_ref=patient_ref,
                    competence=current_record.competence,
                )
                patient["vigilance_notes"] = get_monthly_vigilance_notes(
                    agravo=current_record.agravo,
                    patient_ref=patient_ref,
                    competence=current_record.competence,
                )
            else:
                patient["current_values"] = {}
                patient["updated_values"] = {}
                patient["can_edit"] = False
                patient["comparison"] = {}
                patient["revisions"] = ()
                patient["vigilance_notes"] = ()
            patient["previous_values"] = (
                previous_record.values if previous_record is not None else {}
            )
        row["patient_communications"] = patient_communications
        row["confirmation_history"] = get_monthly_unit_confirmation_history(
            agravo=str(row["agravo"]),
            competence=str(row["competence"]),
            unit_ref=str(row["unit_ref"]),
        )
    filtered_rows = [
        row for row in all_rows
        if (not state or row["situation"] == state)
        and (not pending or int(row["patients_pending"]) > 0)
        and (
            not patient_state
            or any(
                patient["situation"] == patient_state
                for patient in row["patients"]
            )
        )
        and (
            not silent
            or row["situation"] in {
                "silent_pending", "silent_confirmed", "reconciliation_required",
            }
        )
    ]
    return render_monthly_monitoring(
        rows=tuple(filtered_rows),
        all_rows=tuple(all_rows),
        role=user.role,
        username=user.username,
        csrf_token=csrf,
        selected_agravo=agravo,
        selected_competence=competence,
        selected_unit=scoped_units or "",
        selected_state=state,
        selected_patient_state=patient_state,
        saved_state=saved if saved in {"draft", "submitted"} else "",
        pending_only=pending,
        silent_only=silent,
        available_competences=tuple(available_competences),
        deadline=(
            get_monthly_monitoring_deadline(agravo=agravo, competence=competence)
            if agravo else None
        ),
    )


@router.post(
    "/monitoramento-mensal/{agravo}/{competence}/{patient_ref}/atualizar"
)
async def update_monthly_record_from_monitoring(
    agravo: Literal["tuberculose", "hanseniase"],
    competence: str,
    patient_ref: str,
    request: Request,
) -> Response:
    session = _session(request)
    if session is None:
        return RedirectResponse("/login", status_code=303)
    user, csrf = session
    if user.role != "unit":
        raise HTTPException(
            status_code=403,
            detail="Somente a unidade pode atualizar e enviar a ficha.",
        )
    if user.must_change_password:
        return RedirectResponse("/trocar-senha", status_code=303)
    if not user.unit:
        raise HTTPException(status_code=403, detail="A conta não está vinculada a uma unidade.")

    form = await request.form(max_files=0, max_fields=64)
    csrf_value = form.get("csrf_token")
    if not isinstance(csrf_value, str) or not validate_csrf(csrf_value, csrf):
        raise HTTPException(status_code=403, detail="Token de segurança inválido.")
    action = form.get("action")
    if action not in {"draft", "submit"}:
        raise HTTPException(status_code=422, detail="Ação de atualização inválida.")
    editable_fields = monthly_editable_field_keys(agravo)
    submitted_fields = set(form.keys()) - {"csrf_token", "action"}
    if not submitted_fields or submitted_fields - editable_fields:
        raise HTTPException(status_code=422, detail="Campos ausentes ou não reconhecidos.")
    raw_values: dict[str, str] = {}
    for key in submitted_fields:
        value = form.get(key)
        if not isinstance(value, str):
            raise HTTPException(status_code=422, detail="Valor de campo inválido.")
        raw_values[key] = value
    try:
        parsed_competence = str(Competence.parse(competence))
        validated_values = validate_form_values(agravo, raw_values)
        update_monthly_draft(
            agravo=agravo,
            patient_ref=patient_ref,
            competence=parsed_competence,
            unit_ref=user.unit,
            actor=user.username,
            values=prepare_updated_values(agravo, validated_values),
        )
        if action == "submit":
            submit_monthly_record(
                agravo=agravo,
                patient_ref=patient_ref,
                competence=parsed_competence,
                unit_ref=user.unit,
                actor=user.username,
            )
    except PermissionError as error:
        raise HTTPException(status_code=404, detail="Registro mensal não encontrado.") from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    query = urlencode(
        {
            "agravo": agravo,
            "competence": parsed_competence,
            "saved": "submitted" if action == "submit" else "draft",
        }
    )
    return RedirectResponse(
        f"/monitoramento-mensal?{query}#patient-{quote(patient_ref, safe='')}",
        status_code=303,
    )


@router.post("/monitoramento-mensal/prazo")
async def configure_monthly_monitoring_deadline(request: Request) -> Response:
    session = _session(request)
    if session is None:
        raise HTTPException(status_code=401, detail="Faça login para continuar.")
    user, csrf = session
    if user.role != "surveillance":
        raise HTTPException(status_code=403, detail="Somente a Vigilância pode configurar prazos.")
    if user.must_change_password:
        raise HTTPException(status_code=403, detail="Altere a senha antes de continuar.")
    form = await request.form(max_files=0, max_fields=8)
    csrf_value = form.get("csrf_token")
    if not isinstance(csrf_value, str) or not validate_csrf(csrf_value, csrf):
        raise HTTPException(status_code=403, detail="Token de segurança inválido.")
    agravo = form.get("agravo")
    competence = form.get("competence")
    opened_on = form.get("opened_on")
    due_on = form.get("due_on")
    extension_due_on = form.get("extension_due_on")
    if (
        agravo not in {"tuberculose", "hanseniase"}
        or not isinstance(competence, str)
        or not isinstance(opened_on, str)
        or not isinstance(due_on, str)
        or extension_due_on is not None and not isinstance(extension_due_on, str)
    ):
        raise HTTPException(status_code=422, detail="Dados do prazo inválidos.")
    try:
        set_monthly_monitoring_deadline(
            agravo=agravo,
            competence=str(Competence.parse(competence)),
            opened_on=opened_on,
            due_on=due_on,
            extension_due_on=extension_due_on or None,
            actor=user.username,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return RedirectResponse(
        f"/monitoramento-mensal?agravo={agravo}&competence={competence}",
        status_code=303,
    )


@router.post("/monitoramento-mensal/confirmar")
async def unit_confirm_silence(request: Request) -> Response:
    session = _session(request)
    if session is None:
        raise HTTPException(status_code=401, detail="Faça login para continuar.")
    user, csrf = session
    if user.role != "unit":
        raise HTTPException(status_code=403, detail="Somente a unidade vinculada pode responder.")
    if user.must_change_password:
        raise HTTPException(status_code=403, detail="Altere a senha antes de continuar.")
    form = await request.form(max_files=0, max_fields=8)
    csrf_value = form.get("csrf_token")
    if not isinstance(csrf_value, str) or not validate_csrf(csrf_value, csrf):
        raise HTTPException(status_code=403, detail="Token de segurança inválido.")
    agravo, competence = form.get("agravo"), form.get("competence")
    action, note = form.get("action"), form.get("note", "")
    if (
        agravo not in {"tuberculose", "hanseniase"}
        or not isinstance(competence, str)
        or action not in {"confirm_absence", "report_missing_patients", "request_review"}
        or not isinstance(note, str)
    ):
        raise HTTPException(status_code=422, detail="Resposta de ausência inválida.")
    try:
        parsed = str(Competence.parse(competence))
        row = monthly_unit_monitoring(
            agravo=agravo,
            competence=parsed,
            units=(user.unit or "",),
        )[0]
        if row["situation"] not in {
            "silent_pending", "silent_confirmed", "reconciliation_required",
        }:
            raise ValueError("A confirmação só está disponível para unidade silenciosa.")
        update_monthly_unit_confirmation(
            agravo=agravo,
            competence=parsed,
            unit_ref=user.unit or "",
            actor=user.username,
            actor_role="unit",
            action=action,
            note=note,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return RedirectResponse(
        f"/monitoramento-mensal?agravo={agravo}&competence={parsed}",
        status_code=303,
    )


@router.post("/vigilancia/monitoramento-mensal/acao")
async def surveillance_silence_action(request: Request) -> Response:
    session = _session(request)
    if session is None:
        raise HTTPException(status_code=401, detail="Faça login para continuar.")
    user, csrf = session
    if user.role != "surveillance":
        raise HTTPException(status_code=403, detail="Somente a Vigilância pode revisar a confirmação.")
    if user.must_change_password:
        raise HTTPException(status_code=403, detail="Altere a senha antes de continuar.")
    form = await request.form(max_files=0, max_fields=8)
    csrf_value = form.get("csrf_token")
    if not isinstance(csrf_value, str) or not validate_csrf(csrf_value, csrf):
        raise HTTPException(status_code=403, detail="Token de segurança inválido.")
    agravo, competence = form.get("agravo"), form.get("competence")
    unit_ref, action = form.get("unit_ref"), form.get("action")
    note = form.get("note", "")
    if (
        agravo not in {"tuberculose", "hanseniase"}
        or not isinstance(competence, str)
        or not isinstance(unit_ref, str)
        or action not in {
            "request_confirmation", "confirm_absence", "resolve_reconciliation",
        }
        or not isinstance(note, str)
    ):
        raise HTTPException(status_code=422, detail="Ação da Vigilância inválida.")
    if not any(
        unit.casefold() == unit_ref.strip().casefold()
        for unit in _known_units(agravo)
    ):
        raise HTTPException(status_code=404, detail="Unidade não encontrada.")
    try:
        parsed = str(Competence.parse(competence))
        row = monthly_unit_monitoring(
            agravo=agravo,
            competence=parsed,
            units=(unit_ref,),
        )[0]
        if row["situation"] not in {
            "silent_pending", "silent_confirmed", "reconciliation_required",
        }:
            raise ValueError("A ação só está disponível para unidade silenciosa.")
        if action == "resolve_reconciliation" and row["situation"] != "reconciliation_required":
            raise ValueError("Não há divergência pendente para concluir.")
        update_monthly_unit_confirmation(
            agravo=agravo,
            competence=parsed,
            unit_ref=unit_ref,
            actor=user.username,
            actor_role="surveillance",
            action=action,
            note=note,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return RedirectResponse(
        f"/monitoramento-mensal?agravo={agravo}&competence={parsed}",
        status_code=303,
    )


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
    communications = list_monthly_followups(
        agravo=module_key,
        unit_ref=user.unit if user.role == "unit" else (selected_unit or None),
        include_automatic=user.role != "unit",
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
        communications=communications,
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


@router.get("/api/historico/{agravo}/{competence}")
def monthly_history(
    agravo: Literal["tuberculose", "hanseniase"],
    competence: str,
    request: Request,
) -> dict[str, object]:
    session = _session(request)
    if session is None:
        raise HTTPException(status_code=401, detail="Faça login para continuar.")
    user, _ = session
    if user.must_change_password:
        raise HTTPException(status_code=403, detail="Altere a senha antes de continuar.")
    if user.role not in {"unit", "surveillance"}:
        raise HTTPException(status_code=403, detail="Perfil sem acesso ao histórico mensal.")
    try:
        parsed_competence = Competence.parse(competence)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    unit_ref = user.unit if user.role == "unit" else None
    current_records = list_monthly_records(
        agravo=agravo,
        competence=str(parsed_competence),
        unit_ref=unit_ref,
    )
    previous_records = list_monthly_records(
        agravo=agravo,
        competence=str(parsed_competence.previous()),
        unit_ref=unit_ref,
    )
    previous_by_ref = {record.patient_ref: record for record in previous_records}
    current_refs = {record.patient_ref for record in current_records}
    return {
        "agravo": agravo,
        "competencia": str(parsed_competence),
        "situacao_competencia": get_monthly_competence_state(
            agravo=agravo,
            competence=str(parsed_competence),
        ),
        "registros": [
            {
                "identificador": record.patient_ref,
                "unidade": record.unit_ref,
                "situacao": record.state,
                "versao": record.version,
                "valores_originais": record.original_values,
                "valores_atualizados": record.updated_values,
                "valores_atuais": record.values,
                "competencia_anterior": (
                    previous_by_ref[record.patient_ref].values
                    if record.patient_ref in previous_by_ref
                    else None
                ),
                "comparacao": compare_monthly_record_fields(
                    record,
                    previous_by_ref.get(record.patient_ref),
                ),
                "observacao_vigilancia": record.reviewer_note,
                "historico_observacoes_vigilancia": get_monthly_vigilance_notes(
                    agravo=agravo,
                    patient_ref=record.patient_ref,
                    competence=record.competence,
                ),
                "atualizado_por": record.updated_by,
                "atualizado_em": record.updated_at,
            }
            for record in current_records
        ],
        "registros_anteriores_ausentes_no_mes_atual": [
            {
                "identificador": record.patient_ref,
                "unidade": record.unit_ref,
                "situacao": "ausente_no_boletim_atual_conferir",
                "valores_anteriores": record.values,
                "nao_classificar_automaticamente": True,
            }
            for record in previous_records
            if record.patient_ref not in current_refs
        ],
    }


@router.post("/api/historico/{agravo}/{competence}/{patient_ref}/rascunho")
async def save_monthly_draft(
    agravo: Literal["tuberculose", "hanseniase"],
    competence: str,
    patient_ref: str,
    request: Request,
) -> dict[str, object]:
    session = _session(request)
    if session is None:
        raise HTTPException(status_code=401, detail="Faça login para continuar.")
    user, csrf = session
    if user.role != "unit":
        raise HTTPException(status_code=403, detail="Somente a unidade pode editar o rascunho.")
    if user.must_change_password:
        raise HTTPException(status_code=403, detail="Altere a senha antes de continuar.")
    form = await request.form(max_files=0, max_fields=64)
    csrf_value = form.get("csrf_token")
    if not isinstance(csrf_value, str) or not validate_csrf(csrf_value, csrf):
        raise HTTPException(status_code=403, detail="Token de segurança inválido.")

    allowed_fields = monthly_editable_field_keys(agravo)
    submitted_fields = set(form.keys()) - {"csrf_token"}
    if not submitted_fields or submitted_fields - allowed_fields:
        raise HTTPException(status_code=422, detail="Campos ausentes ou não reconhecidos.")
    raw_values: dict[str, str] = {}
    for key in submitted_fields:
        value = form.get(key)
        if not isinstance(value, str):
            raise HTTPException(status_code=422, detail="Valor de campo inválido.")
        raw_values[key] = value
    try:
        validated_values = validate_form_values(agravo, raw_values)
        saved = update_monthly_draft(
            agravo=agravo,
            patient_ref=patient_ref,
            competence=competence,
            unit_ref=user.unit or "",
            actor=user.username,
            values=prepare_updated_values(agravo, validated_values),
        )
    except PermissionError as error:
        raise HTTPException(status_code=404, detail="Registro mensal não encontrado.") from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return {
        "identificador": saved.patient_ref,
        "competencia": saved.competence,
        "situacao": saved.state,
        "versao": saved.version,
        "valores_atualizados": saved.updated_values,
    }


@router.post("/api/historico/{agravo}/{competence}/{patient_ref}/enviar")
async def submit_monthly_update(
    agravo: Literal["tuberculose", "hanseniase"],
    competence: str,
    patient_ref: str,
    request: Request,
) -> dict[str, str]:
    session = _session(request)
    if session is None:
        raise HTTPException(status_code=401, detail="Faça login para continuar.")
    user, csrf = session
    if user.role != "unit":
        raise HTTPException(status_code=403, detail="Somente a unidade pode enviar atualizações.")
    form = await request.form(max_files=0, max_fields=4)
    csrf_value = form.get("csrf_token")
    if not isinstance(csrf_value, str) or not validate_csrf(csrf_value, csrf):
        raise HTTPException(status_code=403, detail="Token de segurança inválido.")
    try:
        submitted = submit_monthly_record(
            agravo=agravo,
            patient_ref=patient_ref,
            competence=competence,
            unit_ref=user.unit or "",
            actor=user.username,
        )
    except PermissionError as error:
        raise HTTPException(status_code=404, detail="Registro mensal não encontrado.") from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return {"situacao": submitted.state, "competencia": submitted.competence}


@router.post("/api/vigilancia/competencias/{agravo}/{competence}/abrir")
async def open_monthly_period(
    agravo: Literal["tuberculose", "hanseniase"],
    competence: str,
    request: Request,
) -> dict[str, str]:
    session = _session(request)
    if session is None:
        raise HTTPException(status_code=401, detail="Faça login para continuar.")
    user, csrf = session
    if user.role != "surveillance":
        raise HTTPException(status_code=403, detail="Apenas a Vigilância pode abrir competências.")
    form = await request.form(max_files=0, max_fields=4)
    csrf_value = form.get("csrf_token")
    if not isinstance(csrf_value, str) or not validate_csrf(csrf_value, csrf):
        raise HTTPException(status_code=403, detail="Token de segurança inválido.")
    try:
        open_monthly_competence(
            agravo=agravo,
            competence=competence,
            actor=user.username,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return {"agravo": agravo, "competencia": competence, "situacao": "open"}


@router.post("/api/vigilancia/competencias/{agravo}/{competence}/encerrar")
async def close_monthly_period(
    agravo: Literal["tuberculose", "hanseniase"],
    competence: str,
    request: Request,
) -> dict[str, str]:
    session = _session(request)
    if session is None:
        raise HTTPException(status_code=401, detail="Faça login para continuar.")
    user, csrf = session
    if user.role != "surveillance":
        raise HTTPException(status_code=403, detail="Apenas a Vigilância pode encerrar competências.")
    form = await request.form(max_files=0, max_fields=4)
    csrf_value = form.get("csrf_token")
    if not isinstance(csrf_value, str) or not validate_csrf(csrf_value, csrf):
        raise HTTPException(status_code=403, detail="Token de segurança inválido.")
    try:
        close_monthly_competence(
            agravo=agravo,
            competence=competence,
            actor=user.username,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return {"agravo": agravo, "competencia": competence, "situacao": "closed"}


@router.post("/api/vigilancia/historico/{agravo}/{competence}/{patient_ref}/revisar")
async def review_monthly_update(
    agravo: Literal["tuberculose", "hanseniase"],
    competence: str,
    patient_ref: str,
    request: Request,
) -> dict[str, str]:
    session = _session(request)
    if session is None:
        raise HTTPException(status_code=401, detail="Faça login para continuar.")
    user, csrf = session
    if user.role != "surveillance":
        raise HTTPException(status_code=403, detail="Apenas a Vigilância pode revisar atualizações.")
    form = await request.form(max_files=0, max_fields=4)
    csrf_value = form.get("csrf_token")
    if not isinstance(csrf_value, str) or not validate_csrf(csrf_value, csrf):
        raise HTTPException(status_code=403, detail="Token de segurança inválido.")
    approved_value = form.get("approved")
    if approved_value not in {"true", "false"}:
        raise HTTPException(status_code=422, detail="Informe se a atualização foi validada.")
    note = form.get("note", "")
    if not isinstance(note, str):
        raise HTTPException(status_code=422, detail="Observação inválida.")
    try:
        reviewed = review_monthly_record(
            agravo=agravo,
            patient_ref=patient_ref,
            competence=competence,
            actor=user.username,
            approved=approved_value == "true",
            note=note,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return {"situacao": reviewed.state, "competencia": reviewed.competence}


@router.post("/api/boletins/analisar")
def analyze_bulletin_upload(
    request: Request,
    csrf_token: str = Form(..., max_length=128),
    agravo: Literal["tuberculose", "hanseniase"] = Form(...),
    boletim: UploadFile = File(...),
) -> HTMLResponse:
    user, csrf = _csrf_or_forbid(request, csrf_token)
    if user.role != "surveillance":
        raise HTTPException(
            status_code=403,
            detail="Somente a Vigilância Epidemiológica pode importar boletins.",
        )
    if user.must_change_password:
        raise HTTPException(status_code=403, detail="Altere a senha antes de continuar.")
    try:
        content = boletim.file.read(MAX_PDF_BYTES + 1)
        report = analyze_bulletin(content, agravo)
    except PdfAnalysisError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    finally:
        boletim.file.close()

    return render_bulletin_summary(agravo, report, csrf_token=csrf)


@router.get("/api/status")
def status() -> dict[str, str | list[str]]:
    return {
        "sistema": "Monitoramento Ativo de Tuberculose e Hanseníase",
        "status": "Funcionando",
        "modulos": ["Tuberculose", "Hanseníase"],
        "dados": "Demonstrativos; campos ainda não validados oficialmente",
    }
