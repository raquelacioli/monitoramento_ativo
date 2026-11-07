import json
from html import escape

from fastapi.responses import HTMLResponse

from monitoramento.data import ModuleDemo, PatientDemo
from monitoramento.bulletin_forms import BULLETIN_FIELDS, BulletinField
from monitoramento.auth import User
from monitoramento.pdf_analysis import BulletinSummary
from monitoramento.services import (
    all_patients,
    monthly_comparison_demo,
    monthly_updates_missing,
    module_alerts,
    unit_summary,
)
from monitoramento.tracking_store import FOLLOWUP_STATUSES

HOME_HTML = """
<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta name="theme-color" content="#f5f8fc">
    <meta name="description" content="Painel demonstrativo de monitoramento em vigilância em saúde.">
    <title>Monitoramento Ativo | Vigilância em Saúde</title>
    <style>
        :root { color-scheme: light; --ink:#172b4d; --muted:#64748b; --blue:#176b87;
            --blue-soft:#e8f4f7; --green:#2b7565; --green-soft:#eaf5f0;
            --line:#e4eaf1; --surface:#fff; --page:#f5f8fc; }
        * { box-sizing:border-box; }
        body { margin:0; background:var(--page); color:var(--ink);
            font-family:"Segoe UI",Arial,sans-serif; line-height:1.5; }
        .topbar { height:72px; display:flex; align-items:center; justify-content:space-between;
            gap:20px; padding:0 max(24px,calc((100% - 1120px)/2));
            background:var(--surface); border-bottom:1px solid var(--line); }
        .brand { display:flex; align-items:center; gap:12px; font-weight:700; }
        .brand-mark { display:grid; width:38px; height:38px; place-items:center;
            border-radius:12px; background:var(--blue-soft); color:var(--blue); font-size:19px; }
        .topbar-label,.section-note { color:var(--muted); font-size:14px; }
        main { width:min(100% - 48px,1040px); margin:58px auto 72px; }
        .eyebrow { margin:0 0 10px; color:var(--blue); font-size:12px; font-weight:700;
            letter-spacing:.12em; text-transform:uppercase; }
        h1 { margin:0; font-size:clamp(30px,5vw,42px); letter-spacing:-.035em; }
        .intro { max-width:650px; margin:14px 0 0; color:var(--muted); font-size:17px; }
        .demo-banner { margin-top:25px; padding:14px 16px; border:1px solid #ead9a6;
            border-radius:12px; background:#fff9e9; color:#684e14; font-size:14px; }
        .section-heading { display:flex; align-items:end; justify-content:space-between;
            gap:16px; margin:38px 0 18px; }
        h2 { margin:0; font-size:20px; }
        .section-note { margin:0; }
        .cards { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:20px; }
        .card { position:relative; overflow:hidden; min-height:230px; padding:27px;
            background:var(--surface); border:1px solid var(--line); border-radius:18px;
            box-shadow:0 8px 26px rgb(23 43 77 / 5%); text-decoration:none; color:inherit;
            transition:transform .15s ease,box-shadow .15s ease; }
        .card:hover { transform:translateY(-2px); box-shadow:0 12px 30px rgb(23 43 77 / 10%); }
        .card:focus-visible { outline:3px solid #91c8d7; outline-offset:3px; }
        .card::before { position:absolute; inset:0 auto 0 0; width:4px;
            background:var(--blue); content:""; }
        .card.hanseniase::before { background:var(--green); }
        .card-icon { display:grid; width:46px; height:46px; place-items:center;
            border-radius:14px; background:var(--blue-soft); color:var(--blue); font-size:21px; }
        .hanseniase .card-icon { background:var(--green-soft); color:var(--green); }
        .card h3 { margin:19px 0 7px; font-size:21px; }
        .card p { max-width:390px; margin:0; color:var(--muted); }
        .card-caption { display:inline-flex; margin-top:21px; color:var(--blue);
            font-size:14px; font-weight:700; }
        .hanseniase .card-caption { color:var(--green); }
        footer { margin-top:36px; padding-top:18px; border-top:1px solid var(--line);
            color:var(--muted); font-size:13px; }
        @media (max-width:640px) {
            .topbar { height:64px; padding:0 20px; }
            .topbar-label { display:none; }
            main { width:min(100% - 36px,480px); margin:38px auto 52px; }
            .section-heading { align-items:start; flex-direction:column; margin-top:30px; }
            .cards { grid-template-columns:1fr; gap:14px; }
            .card { min-height:210px; padding:23px; }
        }
    </style>
</head>
<body>
    <header class="topbar"><div class="brand">
        <span class="brand-mark" aria-hidden="true">+</span><span>Vigilância em Saúde</span>
    </div><a class="topbar-label" href="/login">Acesso da equipe</a></header>
    <main>
        <p class="eyebrow">Painel de acompanhamento</p>
        <h1>Monitoramento Ativo</h1>
        <p class="intro">Acesse os módulos demonstrativos de vigilância e acompanhamento
            de tuberculose e hanseníase.</p>
        <p class="demo-banner"><strong>Ambiente demonstrativo:</strong>
            todos os registros e indicadores são fictícios. Não use dados reais de pacientes.</p>
        <section aria-labelledby="modulos-titulo">
            <div class="section-heading"><h2 id="modulos-titulo">Módulos de monitoramento</h2>
                <p class="section-note">Selecione um módulo para visualizar o painel</p></div>
            <div class="cards">
                <a class="card tuberculose" href="/tuberculose">
                    <span class="card-icon" aria-hidden="true">◎</span>
                    <h3>Tuberculose</h3>
                    <p>Indicadores fictícios e tabela demonstrativa de acompanhamento.</p>
                    <span class="card-caption">Abrir módulo <span aria-hidden="true">→</span></span>
                </a>
                <a class="card hanseniase" href="/hanseniase">
                    <span class="card-icon" aria-hidden="true">✳</span>
                    <h3>Hanseníase</h3>
                    <p>Indicadores fictícios e tabela demonstrativa de acompanhamento.</p>
                    <span class="card-caption">Abrir módulo <span aria-hidden="true">→</span></span>
                </a>
                <a class="card" href="/vigilancia">
                    <span class="card-icon" aria-hidden="true">▦</span>
                    <h3>Visão da Vigilância</h3>
                    <p>Consolidação demonstrativa por unidade e pendências.</p>
                    <span class="card-caption">Abrir painel <span aria-hidden="true">→</span></span>
                </a>
            </div>
        </section>
        <footer>Protótipo local sem conexão com Firebase ou outros sistemas.</footer>
    </main>
</body>
</html>
"""

MODULE_CSS = """
<style>
    :root { color-scheme:light; --ink:#172b4d; --muted:#64748b; --blue:#176b87;
        --green:#2b7565; --line:#e4eaf1; --surface:#fff; --page:#f5f8fc; }
    * { box-sizing:border-box; }
    body { margin:0; background:var(--page); color:var(--ink);
        font-family:"Segoe UI",Arial,sans-serif; line-height:1.5; }
    a { color:inherit; }
    .topbar { height:68px; display:flex; align-items:center; justify-content:space-between;
        gap:18px; padding:0 max(24px,calc((100% - 1240px)/2)); background:var(--surface);
        border-bottom:1px solid var(--line); }
    .brand { font-weight:700; text-decoration:none; }
    .back { color:var(--blue); font-size:14px; font-weight:600; text-decoration:none; }
    main { width:min(100% - 48px,1240px); margin:36px auto 64px; }
    .eyebrow { margin:0 0 7px; color:var(--accent); font-size:12px; font-weight:700;
        letter-spacing:.12em; text-transform:uppercase; }
    h1 { margin:0; font-size:clamp(29px,4vw,38px); letter-spacing:-.03em; }
    .intro { margin:9px 0 0; color:var(--muted); }
    .demo-banner { margin:20px 0 24px; padding:13px 16px; border:1px solid #ead9a6;
        border-radius:12px; background:#fff9e9; color:#684e14; font-size:14px; }
    .notice { margin:0 0 20px; color:var(--muted); font-size:13px; }
    .metrics { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:14px; }
    .metric { min-height:126px; padding:19px; background:var(--surface);
        border:1px solid var(--line); border-radius:15px;
        box-shadow:0 5px 20px rgb(23 43 77 / 4%); }
    .metric-label { display:block; min-height:40px; color:var(--muted); font-size:13px;
        font-weight:600; }
    .metric-value { display:block; margin-top:8px; color:var(--ink); font-size:29px;
        font-weight:750; line-height:1.1; }
    .metric-detail { display:block; margin-top:7px; color:var(--muted); font-size:12px; }
    .section-heading { display:flex; align-items:end; justify-content:space-between;
        gap:16px; margin:34px 0 14px; }
    h2 { margin:0; font-size:20px; }
    .section-note { margin:0; color:var(--muted); font-size:13px; }
    .table-wrap { overflow:auto; background:var(--surface); border:1px solid var(--line);
        border-radius:14px; box-shadow:0 5px 20px rgb(23 43 77 / 4%); }
    table { width:100%; min-width:1180px; border-collapse:collapse; text-align:left; }
    th,td { padding:13px 14px; border-bottom:1px solid var(--line); vertical-align:top; }
    th { background:#f8fafc; color:#52627a; font-size:11px; letter-spacing:.045em;
        text-transform:uppercase; }
    td { color:#34445c; font-size:13px; }
    tbody tr:last-child td { border-bottom:0; }
    .identifier { color:var(--accent); font-weight:700; white-space:nowrap; }
    .status { display:inline-block; padding:4px 8px; border-radius:20px;
        background:#eef2f7; font-size:12px; font-weight:600; }
    .editable { min-width:160px; max-width:260px; border-radius:5px; outline:none; }
    .editable:focus { box-shadow:0 0 0 2px var(--accent); }
    .save-state { min-height:20px; margin:10px 0 0; color:var(--muted); font-size:12px; }
    .units { margin-top:26px; padding:18px 20px; background:var(--surface);
        border:1px solid var(--line); border-radius:14px; }
    .units h2 { font-size:16px; }
    .units p { margin:8px 0 0; color:var(--muted); font-size:14px; }
    .footer { margin-top:28px; color:var(--muted); font-size:12px; }
    .app-shell { display:grid; grid-template-columns:190px minmax(0,1fr); gap:24px;
        width:min(100% - 40px,1440px); margin:24px auto 50px; }
    .sidebar { align-self:start; position:sticky; top:20px; padding:16px 10px;
        background:var(--surface); border:1px solid var(--line); border-radius:14px; }
    .sidebar a { display:block; padding:10px 12px; border-radius:8px;
        color:var(--muted); font-size:13px; font-weight:600; text-decoration:none; }
    .sidebar a:hover,.sidebar a.active { background:#edf5f8; color:var(--accent); }
    .content { width:100%; max-width:none; margin:0; }
    .filter-form { display:flex; flex-wrap:wrap; align-items:end; gap:10px;
        margin:20px 0; padding:16px; background:var(--surface);
        border:1px solid var(--line); border-radius:14px; }
    .filter-field { display:grid; gap:5px; color:var(--muted); font-size:12px; font-weight:600; }
    .filter-field input,.filter-field select { min-width:155px; min-height:38px; padding:7px 9px;
        border:1px solid #d5dee8; border-radius:8px; background:#fff; color:var(--ink); }
    .filter-form button,.reset-link { min-height:38px; padding:8px 14px; border:0;
        border-radius:8px; background:var(--accent); color:#fff; font-weight:700;
        text-decoration:none; cursor:pointer; }
    .reset-link { display:inline-flex; align-items:center; background:#edf1f5; color:var(--ink); }
    .panel-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:15px;
        margin-top:24px; }
    .panel { padding:18px; background:var(--surface); border:1px solid var(--line);
        border-radius:14px; box-shadow:0 5px 20px rgb(23 43 77 / 4%); }
    .panel h2 { margin:0 0 15px; font-size:16px; }
    .bar-row { display:grid; grid-template-columns:minmax(90px,1fr) 2fr 28px;
        align-items:center; gap:10px; margin:11px 0; color:var(--muted); font-size:12px; }
    .bar-track { height:10px; overflow:hidden; border-radius:8px; background:#edf1f5; }
    .bar-fill { height:100%; border-radius:8px; background:var(--accent); }
    .bar-row strong { color:var(--ink); text-align:right; }
    .month-summary { display:flex; flex-wrap:wrap; gap:12px; }
    .month-chip { flex:1 1 110px; padding:12px; border-radius:10px; background:#f4f7fa; }
    .month-chip strong { display:block; font-size:21px; }
    .month-chip span { color:var(--muted); font-size:11px; }
    .upload-panel { margin:22px 0; padding:20px; background:var(--surface);
        border:1px solid var(--line); border-left:4px solid var(--accent);
        border-radius:14px; box-shadow:0 5px 20px rgb(23 43 77 / 4%); }
    .upload-panel h2 { margin:0 0 7px; font-size:18px; }
    .upload-panel p { margin:0 0 14px; color:var(--muted); font-size:13px; }
    .upload-controls { display:grid; grid-template-columns:minmax(0,1fr); gap:12px;
        width:min(100%,520px); }
    .upload-controls .filter-field { width:100%; }
    .upload-controls input[type=file] { display:block; width:100%; max-width:100%;
        min-height:44px; padding:8px; border:1px solid #d5dee8; border-radius:8px;
        background:#fff; }
    .upload-controls button { display:block; visibility:visible; opacity:1;
        width:100%; min-height:48px; padding:11px 18px; border:0;
        border-radius:8px; background:var(--accent); color:#fff;
        font-size:15px; font-weight:700; cursor:pointer; }
    .upload-controls button:hover { filter:brightness(.92); }
    .upload-controls button:disabled { cursor:wait; opacity:.72; }
    .upload-controls button:focus-visible { outline:3px solid #91c8d7; outline-offset:2px; }
    .observation-input { width:240px; min-height:65px; padding:8px;
        border:1px solid #d5dee8; border-radius:7px; font:inherit; }
    .edit-control { width:100%; min-width:125px; min-height:38px; padding:7px;
        border:1px solid #d5dee8; border-radius:7px; background:#fff; color:var(--ink);
        font:inherit; }
    .numeric-control { width:90px; min-width:70px; margin:2px; }
    .save-row { margin-top:8px; padding:8px 10px; border:0; border-radius:7px;
        background:var(--accent); color:#fff; font-weight:700; cursor:pointer; }
    .sr-only { position:absolute; width:1px; height:1px; padding:0; margin:-1px;
        overflow:hidden; clip:rect(0,0,0,0); white-space:nowrap; border:0; }
    .form-grid { display:grid; grid-template-columns:repeat(2,minmax(180px,1fr)); gap:10px; }
    fieldset { margin:14px 0; padding:14px; border:1px solid var(--line); border-radius:10px; }
    legend { padding:0 6px; color:var(--ink); font-weight:700; }
    .form-field { display:grid; gap:5px; color:var(--muted); font-size:12px; font-weight:600; }
    .form-warning { padding:10px; border-radius:8px; background:#fff5d8; color:#684e14; }
    .auth-card { width:min(100% - 32px,520px); margin:54px auto; padding:28px;
        background:var(--surface); border:1px solid var(--line); border-radius:16px;
        box-shadow:0 8px 26px rgb(23 43 77 / 6%); }
    .auth-card h1 { font-size:28px; }
    .auth-form { display:grid; gap:14px; margin-top:20px; }
    .auth-form input,.auth-form select { min-height:42px; padding:9px;
        border:1px solid #d5dee8; border-radius:8px; font:inherit; }
    .auth-form button { min-height:44px; border:0; border-radius:8px;
        background:var(--blue); color:white; font-weight:700; cursor:pointer; }
    .auth-error { padding:10px; border-radius:8px; background:#fde8e7; color:#9b2c2c; }
    .account-table { width:100%; min-width:600px; border-collapse:collapse; }
    .account-table th,.account-table td { padding:10px; border-bottom:1px solid var(--line); text-align:left; }
    .alert-table { width:100%; min-width:740px; border-collapse:collapse; text-align:left; }
    .alert-table th,.alert-table td { padding:10px; border-bottom:1px solid var(--line);
        vertical-align:top; font-size:12px; }
    .alert-level { display:inline-block; padding:4px 8px; border-radius:20px;
        background:#fff2cf; color:#775600; font-weight:700; white-space:nowrap; }
    .alert-level.green { background:#e4f4eb; color:#27624b; }
    .alert-level.red { background:#fde8e7; color:#9b2c2c; }
    .table-wrap th button { padding:0; border:0; background:none; color:inherit;
        font:inherit; text-align:left; text-transform:inherit; cursor:pointer; }
    .no-results { padding:24px; color:var(--muted); text-align:center; }
    @media (max-width:760px) {
        .topbar { height:60px; padding:0 18px; }
        .app-shell { grid-template-columns:1fr; width:min(100% - 28px,620px); gap:10px; }
        .sidebar { position:static; display:flex; overflow:auto; gap:2px; padding:5px; }
        .sidebar a { flex:none; white-space:nowrap; }
        main.content { width:100%; margin:0; }
        .metrics { grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; }
        .metric { min-height:120px; padding:15px; }
        .section-heading { align-items:start; flex-direction:column; }
        .panel-grid { grid-template-columns:1fr; }
        .filter-field { flex:1 1 140px; }
        .filter-field input,.filter-field select { min-width:0; width:100%; }
    }
    @media (max-width:420px) { .metrics { grid-template-columns:1fr; } }
</style>
"""


def _patient_row(
    module_key: str,
    module_name: str,
    patient: PatientDemo,
    csrf_token: str,
    editable: bool,
) -> str:
    form_id = f"update-{module_key}-{patient.identifier}"
    status_options = "".join(
        f'<option value="{escape(status)}" '
        f'{"selected" if status == patient.followup_status else ""}>'
        f'{escape(status)}</option>'
        for status in FOLLOWUP_STATUSES
    )
    form_values = dict(patient.form_values)
    form_values.setdefault("unidade", patient.unit)
    form_values.setdefault("contatos_identificados", str(patient.contacts_registered))
    form_values.setdefault("contatos_examinados", str(patient.contacts_examined))
    last_attendance_field = next(
        field
        for field in BULLETIN_FIELDS[module_key]
        if field.key == "data_ultimo_comparecimento"
    )
    fields_by_section: dict[str, list[str]] = {}
    for field in BULLETIN_FIELDS[module_key]:
        if field.key == "data_ultimo_comparecimento":
            continue
        field_html = _bulletin_field_input(
            form_id, field, form_values.get(field.key, ""), editable
        )
        fields_by_section.setdefault(field.section, []).append(field_html)
    sections_html = "".join(
        f'<fieldset><legend>{escape(section)}</legend><div class="form-grid">'
        f'{"".join(fields)}</div></fieldset>'
        for section, fields in fields_by_section.items()
    )
    save_button = (
        f'<button class="save-row" type="submit" form="{escape(form_id)}">'
        "Salvar alterações</button>"
        if editable
        else ""
    )
    return f"""
        <tr data-start="{patient.treatment_start.isoformat()}">
            <td class="identifier">{escape(patient.identifier)}
                <form id="{escape(form_id)}" method="post"
                    action="/api/acompanhamento/{escape(module_key)}/{escape(patient.identifier)}">
                    <input type="hidden" name="csrf_token" value="{escape(csrf_token)}">
                </form>
            </td>
            <td>{escape(patient.unit)}<br><small>{escape(patient.district)}</small></td>
            <td>{escape(module_name)}</td>
            <td data-sort-value="{patient.treatment_start.isoformat()}">
                {patient.treatment_start.strftime("%d/%m/%Y")}</td>
            <td>{escape(patient.month_reference)}</td>
            <td><select class="edit-control" form="{escape(form_id)}" name="followup_status"
                {"disabled" if not editable else ""}
                aria-label="Situação de acompanhamento de {escape(patient.identifier)}">
                {status_options}</select></td>
            <td data-sort-value="{patient.expected_end.isoformat()}">
                {patient.expected_end.strftime("%d/%m/%Y")}</td>
            <td>{patient.contacts_registered} / {patient.contacts_examined}</td>
            <td class="pending-cell"><input class="edit-control" form="{escape(form_id)}"
                type="text" name="pending_items" maxlength="250" value="{escape(patient.pending_items)}"
                aria-label="Pendências para {escape(patient.identifier)}"
                {"disabled" if not editable else ""}></td>
            <td><details><summary>Ver nota</summary>{escape(patient.automatic_note)}</details></td>
            <td><textarea class="edit-control observation-input" form="{escape(form_id)}"
                name="observation" maxlength="1000"
                aria-label="Observação da unidade para {escape(patient.identifier)}"
                placeholder="Registre informações relevantes do acompanhamento"
                {"disabled" if not editable else ""}>{escape(patient.observation)}</textarea></td>
            <td>{patient.last_updated.strftime("%d/%m/%Y")}</td>
            <td><details><summary>Ficha completa</summary>
                <p class="form-warning">Campos reproduzidos de modelo reconstruído, não oficial.
                    Use somente valores inventados neste protótipo.</p>
                {sections_html}
                <p>Distrito: {escape(patient.district)}</p>
                <p>Início: {patient.treatment_start.strftime("%d/%m/%Y")}</p>
                <p>Término previsto (demonstrativo): {patient.expected_end.strftime("%d/%m/%Y")}</p>
            </details>{save_button}</td>
            <td>{_bulletin_field_input(
                form_id,
                last_attendance_field,
                form_values.get(last_attendance_field.key, ""),
                editable,
            )}</td>
        </tr>
    """


def _bulletin_field_input(
    form_id: str,
    field: BulletinField,
    value: str,
    editable: bool,
) -> str:
    field_id = f"{form_id}-{field.key}"
    label = escape(field.label)
    escaped_value = escape(value)
    if field.kind == "select":
        options = ['<option value="">Não informado</option>']
        options.extend(
            f'<option value="{escape(choice)}" '
            f'{"selected" if choice == value else ""}>{escape(choice)}</option>'
            for choice in field.choices
        )
        control = (
            f'<select id="{escape(field_id)}" name="{escape(field.key)}" '
            f'form="{escape(form_id)}" class="edit-control" '
            f'{"disabled" if not editable else ""}>{"".join(options)}</select>'
        )
    else:
        input_type = field.kind if field.kind in {"date", "number"} else "text"
        min_value = ' min="0"' if field.kind == "number" else ""
        control = (
            f'<input id="{escape(field_id)}" name="{escape(field.key)}" '
            f'form="{escape(form_id)}" class="edit-control" type="{input_type}" '
            f'value="{escaped_value}" maxlength="250"{min_value} '
            f'{"disabled" if not editable else ""}>'
        )
    return f'<label class="form-field" for="{escape(field_id)}">{label}{control}</label>'


def _metric(label: str, value: int, detail: str) -> str:
    return (
        '<article class="metric">'
        f'<span class="metric-label">{escape(label)}</span>'
        f'<strong class="metric-value">{value}</strong>'
        f'<span class="metric-detail">{escape(detail)}</span>'
        "</article>"
    )


def render_home() -> HTMLResponse:
    return HTMLResponse(content=HOME_HTML)


def render_login(csrf_token: str, error: str = "") -> HTMLResponse:
    error_html = f'<p class="auth-error" role="alert">{escape(error)}</p>' if error else ""
    return HTMLResponse(
        f"""<!DOCTYPE html><html lang="pt-BR"><head><meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>Acesso da equipe | Monitoramento Ativo</title>{MODULE_CSS}</head><body>
        <header class="topbar"><a class="brand" href="/">Monitoramento Ativo</a></header>
        <main class="auth-card"><p class="eyebrow">Acesso restrito</p><h1>Entrar</h1>
        <p>Use a conta fornecida pelo administrador. Não há cadastro público.</p>
        {error_html}<form class="auth-form" method="post" action="/login">
        <input type="hidden" name="csrf_token" value="{escape(csrf_token)}">
        <label class="form-field">Usuário<input name="username" autocomplete="username"
            required maxlength="80"></label>
        <label class="form-field">Senha<input type="password" name="password"
            autocomplete="current-password" required maxlength="256"></label>
        <button type="submit">Entrar</button></form>
        <p class="form-warning">Protótipo: use somente dados fictícios. Os formulários ainda não
            foram validados com documentação oficial para uso assistencial.</p></main></body></html>"""
    )


def render_password_change(
    csrf_token: str,
    error: str = "",
    forced: bool = False,
) -> HTMLResponse:
    error_html = f'<p class="auth-error" role="alert">{escape(error)}</p>' if error else ""
    notice = (
        "<p>Defina uma nova senha antes de continuar.</p>"
        if forced
        else "<p>Escolha uma senha nova para sua conta.</p>"
    )
    return HTMLResponse(
        f"""<!DOCTYPE html><html lang="pt-BR"><head><meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>Alterar senha | Monitoramento Ativo</title>{MODULE_CSS}</head><body>
        <main class="auth-card"><p class="eyebrow">Segurança da conta</p>
        <h1>Alterar senha</h1>{notice}{error_html}
        <form class="auth-form" method="post" action="/trocar-senha">
        <input type="hidden" name="csrf_token" value="{escape(csrf_token)}">
        <label class="form-field">Nova senha<input type="password" name="password"
            autocomplete="new-password" minlength="12" maxlength="256" required></label>
        <label class="form-field">Confirmar nova senha<input type="password"
            name="confirmation" autocomplete="new-password" minlength="12"
            maxlength="256" required></label>
        <button type="submit">Salvar senha</button></form></main></body></html>"""
    )


def render_user_admin(
    users: tuple[User, ...],
    csrf_token: str,
    error: str = "",
    success: str = "",
) -> HTMLResponse:
    error_html = f'<p class="auth-error" role="alert">{escape(error)}</p>' if error else ""
    success_html = f'<p class="save-state" role="status">{escape(success)}</p>' if success else ""
    role_names = {"unit": "Unidade", "surveillance": "Vigilância", "admin": "Administrador"}
    rows = "".join(
        f"""<tr><td>{escape(user.username)}</td><td>{role_names[user.role]}</td>
        <td>{escape(user.unit or "—")}</td><td>{"Ativa" if user.active else "Desativada"}</td>
        <td>{"Troca de senha obrigatória" if user.must_change_password else "—"}</td>
        <td>{"".join(()) if not user.active else f'<form method="post" action="/admin/usuarios/{user.id}/desativar">'
            f'<input type="hidden" name="csrf_token" value="{escape(csrf_token)}">'
            '<button type="submit">Desativar</button></form>'}</td></tr>"""
        for user in users
    )
    return HTMLResponse(
        f"""<!DOCTYPE html><html lang="pt-BR"><head><meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>Contas | Monitoramento Ativo</title>{MODULE_CSS}</head><body>
        <header class="topbar"><a class="brand" href="/">Monitoramento Ativo</a>
        <form method="post" action="/logout"><input type="hidden" name="csrf_token"
            value="{escape(csrf_token)}"><button type="submit">Sair</button></form></header>
        <main class="content" style="width:min(100% - 40px,1100px);margin:38px auto">
        <p class="eyebrow">Administração</p><h1>Contas de acesso</h1>
        <p>O administrador cria as contas. Não compartilhe senhas temporárias pelo sistema.</p>
        <p class="form-warning">Acesso à aplicação não significa autorização para usar dados reais.
            Campos e regras aguardam validação oficial; mantenha a demonstração fictícia.</p>
        {error_html}{success_html}
        <section class="panel"><h2>Criar conta</h2><form class="auth-form" method="post"
            action="/admin/usuarios"><input type="hidden" name="csrf_token"
            value="{escape(csrf_token)}">
        <label class="form-field">Usuário<input name="username" required maxlength="80"></label>
        <label class="form-field">Perfil<select name="role" required>
            <option value="unit">Profissional da unidade</option>
            <option value="surveillance">Vigilância</option>
            <option value="admin">Administrador</option></select></label>
        <label class="form-field">Unidade vinculada (obrigatória para perfil Unidade)
            <input name="unit" maxlength="180"></label>
        <label class="form-field">Senha temporária (mínimo 12 caracteres)
            <input type="password" name="password" minlength="12" maxlength="256"
                autocomplete="new-password" required></label>
        <button type="submit">Criar conta</button></form></section>
        <section class="panel" style="margin-top:20px"><h2>Usuários cadastrados</h2>
        <div class="table-wrap"><table class="account-table"><thead><tr>
        <th>Usuário</th><th>Perfil</th><th>Unidade</th><th>Estado</th>
        <th>Senha</th><th>Ação</th></tr></thead><tbody>{rows}</tbody></table></div></section>
        </main></body></html>"""
    )


def _bar(label: str, value: int, maximum: int) -> str:
    width = min(100, round(value / max(maximum, 1) * 100))
    return (
        '<div class="bar-row">'
        f'<span>{escape(label)}</span><div class="bar-track"><div class="bar-fill" '
        f'style="width:{width}%"></div></div><strong>{value}</strong></div>'
    )


def _comparison_panel(module: ModuleDemo) -> str:
    comparison = monthly_comparison_demo(module)
    return f"""
        <section class="panel" aria-labelledby="comparacao-titulo">
            <h2 id="comparacao-titulo">Comparação mensal demonstrativa</h2>
            <p class="section-note">{escape(str(comparison['previous']))} versus
                {escape(str(comparison['current']))}; dados fictícios, sem boletins importados.</p>
            <div class="month-summary">
                <div class="month-chip"><strong>{comparison['new']}</strong><span>Novos no mês (demo)</span></div>
                <div class="month-chip"><strong>{comparison['maintained']}</strong><span>Mantidos (demo)</span></div>
                <div class="month-chip"><strong>{comparison['absent_needs_verification']}</strong>
                    <span>Ausentes no exemplo; verificar, não classificar</span></div>
            </div>
        </section>
    """


def _alert_table(module: ModuleDemo, patients: tuple[PatientDemo, ...]) -> str:
    filtered_module = ModuleDemo(
        module.key,
        module.name,
        module.accent,
        patients,
        module.units_without_monthly_update,
    )
    alerts = module_alerts(filtered_module)
    if not alerts:
        return '<tr><td colspan="5" class="no-results">Nenhum alerta demonstrativo para este filtro.</td></tr>'
    return "".join(
        f"""<tr>
            <td><span class="alert-level {'green' if alert.level == 'verde' else ''}">
                {escape(alert.level.title())}</span></td>
            <td>{escape(alert.patient.identifier)}</td>
            <td>{escape(alert.patient.unit)}</td>
            <td>{escape(alert.reason)}</td>
            <td>{escape(alert.suggested_action)}</td>
        </tr>"""
        for alert in alerts
    )


def render_module(
    module: ModuleDemo,
    patients: tuple[PatientDemo, ...] | None = None,
    search: str = "",
    unit_filter: str = "",
    status_filter: str = "",
    month_filter: str = "",
    saved: bool = False,
    csrf_token: str = "",
    editable: bool = True,
    username: str = "",
) -> HTMLResponse:
    patients = module.patients if patients is None else patients
    contacts_registered = sum(patient.contacts_registered for patient in patients)
    contacts_examined = sum(patient.contacts_examined for patient in patients)
    pending_count = sum(patient.followup_status == "Acompanhamento pendente" for patient in patients)
    ending_count = sum(patient.ending_soon_demo for patient in patients)
    review_count = sum(patient.review_signal_demo for patient in patients)
    new_count = sum(patient.new_this_month_demo for patient in patients)
    units_missing = len(module.units_without_monthly_update)
    units = sorted({patient.unit for patient in module.patients})
    statuses = sorted({patient.followup_status for patient in module.patients})
    unit_options = "".join(
        f'<option value="{escape(unit)}" {"selected" if unit == unit_filter else ""}>{escape(unit)}</option>'
        for unit in units
    )
    status_options = "".join(
        f'<option value="{escape(status)}" {"selected" if status == status_filter else ""}>{escape(status)}</option>'
        for status in statuses
    )
    month_options = "".join(
        f'<option value="{month}" {"selected" if month == month_filter else ""}>{month}</option>'
        for month in ("Novembro/2026", "Outubro/2026")
    )
    metrics_list = [
        ("Pacientes em acompanhamento", len(patients), "Registros fictícios"),
        ("Casos novos no mês", new_count, "Marcadores fictícios"),
        ("Mantidos em acompanhamento", len(patients) - new_count, "Comparação demonstrativa"),
        ("Término previsto", ending_count, "Sinal de calendário fictício"),
        ("Acompanhamento pendente", pending_count, "Pendências fictícias da tabela"),
        ("Possíveis situações para investigar", review_count, "Sinal fictício; não classifica abandono"),
        ("Contatos registrados", contacts_registered, "Soma fictícia"),
        ("Contatos examinados", contacts_examined, "Soma fictícia"),
        ("Contatos pendentes", contacts_registered - contacts_examined, "Cálculo demonstrativo"),
        ("Unidades sem atualização mensal", units_missing, "Sinalização fictícia"),
    ]
    if module.key == "hanseniase":
        metrics_list.insert(
            3,
            ("Em poliquimioterapia", len(patients), "Regime exclusivamente demonstrativo"),
        )
    metrics = "".join(
        _metric(label, value, detail) for label, value, detail in metrics_list
    )
    rows = "".join(
        _patient_row(module.key, module.name, patient, csrf_token, editable)
        for patient in patients
    )
    if not rows:
        rows = '<tr><td colspan="14" class="no-results">Nenhum registro corresponde aos filtros.</td></tr>'
    unit_counts = {
        unit: sum(patient.unit == unit for patient in patients)
        for unit in units
    }
    unit_chart = "".join(_bar(unit, count, max(unit_counts.values(), default=0)) for unit, count in unit_counts.items())
    status_counts = {
        status: sum(patient.followup_status == status for patient in patients)
        for status in sorted({patient.followup_status for patient in patients})
    }
    status_chart = "".join(
        _bar(status, count, max(status_counts.values(), default=0))
        for status, count in status_counts.items()
    )
    title = escape(module.name)
    html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta name="theme-color" content="#f5f8fc">
    <title>{title} | Monitoramento Ativo</title>
    <style>:root {{ --accent: var(--{module.accent}); }}</style>{MODULE_CSS}
</head>
<body>
    <header class="topbar">
        <a class="brand" href="/">Monitoramento Ativo</a>
        <a class="back" href="/vigilancia">Painel geral da Vigilância</a>
        <form method="post" action="/logout"><input type="hidden" name="csrf_token"
            value="{escape(csrf_token)}"><span>{escape(username)}</span>
            <button type="submit">Sair</button></form>
    </header>
    <div class="app-shell">
    <aside class="sidebar" aria-label="Navegação principal">
        <a href="/">Início</a>
        <a href="/tuberculose" class="{'active' if module.key == 'tuberculose' else ''}">Tuberculose</a>
        <a href="/hanseniase" class="{'active' if module.key == 'hanseniase' else ''}">Hanseníase</a>
        <a href="/vigilancia">Visão da Vigilância</a>
    </aside>
    <main class="content">
        <p class="eyebrow">Módulo demonstrativo</p>
        <h1>{title}</h1>
        <p class="intro">Visão demonstrativa de acompanhamento, contatos e pendências.</p>
        <p class="demo-banner"><strong>Dados fictícios:</strong> todos os indicadores e registros
            desta página são apenas demonstrativos. Não há classificação clínica implementada.
            Não insira dados reais ou identificáveis: este protótipo ainda não possui login nem
            controle de acesso para uso real. Campos, códigos e regras ainda aguardam validação
            com documentação oficial. As alterações são salvas no SQLite local.</p>
        {'<p class="save-state" role="status">Alterações salvas no servidor local.</p>' if saved else ''}
        <section class="upload-panel" aria-labelledby="upload-titulo">
            <h2 id="upload-titulo">Importar boletim de {title}</h2>
            <p>Selecione o PDF deste agravo e clique no botão azul para gerar um resumo agregado por unidade e contatos
                pendentes. O arquivo não é salvo permanentemente pelo aplicativo. Limite: 20 MB.
                PDFs digitalizados sem texto selecionável não são analisados.</p>
            <form class="upload-controls" method="post" action="/api/boletins/analisar"
                enctype="multipart/form-data">
                <input type="hidden" name="csrf_token" value="{escape(csrf_token)}">
                <input type="hidden" name="agravo" value="{module.key}">
                <label class="filter-field">Arquivo PDF
                    <input type="file" name="boletim" accept=".pdf,application/pdf" required>
                </label>
                <button type="submit">Analisar boletim de {title}</button>
            </form>
            <p id="upload-status" role="status" aria-live="polite"
                style="min-height:20px;margin:10px 0 0;color:var(--muted);font-size:13px">
                Escolha um arquivo PDF e clique em “Analisar boletim de {title}”.</p>
            <p style="margin:12px 0 0">O resumo não importa automaticamente as linhas para as fichas.
                Confira e preencha manualmente os campos de demonstração.
                O resultado não mostra nomes ou números de notificação.
                Pendências de contatos são apenas uma conferência demonstrativa dos totais do boletim,
                não uma classificação clínica.</p>
        </section>
        <p class="notice">A ausência de um registro em boletim posterior não significa,
            por si só, abandono ou cura. Os critérios oficiais ainda não foram configurados.</p>
        <section class="metrics" aria-label="Indicadores demonstrativos">{metrics}</section>
        <form class="filter-form" method="get" aria-label="Filtros da tabela demonstrativa">
            <label class="filter-field">Pesquisar identificador
                <input type="search" name="search" value="{escape(search)}" placeholder="Ex.: DEMO-TB-001">
            </label>
            <label class="filter-field">Unidade de saúde
                <select name="unit"><option value="">Todas</option>{unit_options}</select>
            </label>
            <label class="filter-field">Situação
                <select name="followup_status"><option value="">Todas</option>{status_options}</select>
            </label>
            <label class="filter-field">Mês de referência
                <select name="month"><option value="">Todos</option>{month_options}</select>
            </label>
            <button type="submit">Aplicar filtros</button>
            <a class="reset-link" href="/{module.key}">Limpar</a>
        </form>
        <div class="panel-grid">
            <section class="panel"><h2>Distribuição por unidade</h2>
                {unit_chart or '<p class="section-note">Sem registros para exibir.</p>'}</section>
            <section class="panel"><h2>Situação do acompanhamento</h2>
                {status_chart or '<p class="section-note">Sem registros para exibir.</p>'}</section>
            {_comparison_panel(module)}
            <section class="panel"><h2>Pendências identificadas</h2>
                {_bar("Acompanhamento", pending_count, max(len(patients), 1))}
                {_bar("Sinais para revisão", review_count, max(len(patients), 1))}
                <p class="section-note">Indicadores fictícios para conferência da equipe.</p>
            </section>
            <section class="panel"><h2>Contatos examinados</h2>
                {_bar("Examinados", contacts_examined, max(contacts_registered, 1))}
                {_bar("Pendentes", contacts_registered - contacts_examined, max(contacts_registered, 1))}
                <p class="section-note">Valores fictícios, sem interpretação clínica.</p>
            </section>
        </div>
        <section class="panel" style="margin-top:20px">
            <h2>Alertas demonstrativos</h2>
            <p class="section-note">
                <span class="alert-level red">Vermelho</span> critérios prioritários a validar;
                não ativado nesta versão.
                <span class="alert-level">Amarelo</span> verificar registro.
                <span class="alert-level green">Verde</span> sem pendência fictícia.
            </p>
            <div class="table-wrap"><table class="alert-table">
                <thead><tr><th>Nível</th><th>Identificador fictício</th><th>Unidade</th>
                    <th>Motivo</th><th>Ação sugerida</th></tr></thead>
                <tbody>{_alert_table(module, patients)}</tbody>
            </table></div>
        </section>
        <section aria-labelledby="tabela-titulo">
            <div class="section-heading">
                <h2 id="tabela-titulo">Acompanhamento demonstrativo</h2>
                <p class="section-note">Ordene clicando no cabeçalho; role horizontalmente para ver colunas.</p>
            </div>
            <div class="table-wrap">
                <table>
                    <thead><tr>
                        <th><button type="button" data-sort="0">Identificador fictício</button></th>
                        <th><button type="button" data-sort="1">Unidade / distrito</button></th>
                        <th>Agravo</th><th><button type="button" data-sort="3">Início do tratamento</button></th>
                        <th><button type="button" data-sort="4">Mês de referência</button></th>
                        <th><button type="button" data-sort="5">Situação</button></th>
                        <th><button type="button" data-sort="6">Término previsto</button></th>
                        <th>Contatos registrados / examinados</th><th>Pendências</th>
                        <th>Observação automática</th><th>Observação da Vigilância</th>
                        <th>Última atualização</th><th>Detalhes</th>
                        <th>Data do último comparecimento</th>
                    </tr></thead>
                    <tbody>{rows}</tbody>
                </table>
            </div>
            <p class="save-state" role="status" aria-live="polite">
                Edite os campos do registro e clique em “Salvar alterações”. Use observações sem
                nomes, números de notificação ou outros dados que identifiquem pessoas.</p>
        </section>
        <section class="units" aria-labelledby="unidades-titulo">
            <h2 id="unidades-titulo">Unidades sem atualização mensal</h2>
            <p>{", ".join(escape(unit) for unit in module.units_without_monthly_update)
                if units_missing else "Nenhuma unidade fictícia sinalizada neste exemplo."}</p>
        </section>
        <p class="footer">Protótipo local. Sem autenticação, integração Firebase ou processamento
            de dados reais. Filtros de interface não substituem controle de acesso.</p>
    </main>
    </div>
    <script>
        (() => {{
            const uploadForm = document.querySelector(".upload-controls");
            const uploadInput = uploadForm.querySelector('input[type="file"]');
            const uploadStatus = document.getElementById("upload-status");
            const uploadButton = uploadForm.querySelector('button[type="submit"]');
            uploadInput.addEventListener("change", () => {{
                uploadStatus.textContent = uploadInput.files.length
                    ? "PDF selecionado. Clique no botão azul para iniciar a análise."
                    : "Nenhum PDF selecionado.";
            }});
            uploadForm.addEventListener("submit", () => {{
                uploadButton.disabled = true;
                uploadButton.textContent = "Analisando PDF...";
                uploadStatus.textContent = "Processando localmente. Aguarde o resumo.";
            }});
            document.querySelectorAll("[data-sort]").forEach((button) => {{
                button.addEventListener("click", () => {{
                    const tbody = document.querySelector("tbody");
                    const rows = Array.from(tbody.querySelectorAll("tr"));
                    const index = Number(button.dataset.sort);
                    const ascending = button.dataset.direction !== "asc";
                    button.dataset.direction = ascending ? "asc" : "desc";
                    rows.sort((a, b) => {{
                        const left = a.cells[index].dataset.sortValue || a.cells[index].textContent.trim();
                        const right = b.cells[index].dataset.sortValue || b.cells[index].textContent.trim();
                        return left.localeCompare(right, "pt-BR", {{numeric:true}}) * (ascending ? 1 : -1);
                    }});
                    rows.forEach((row) => tbody.appendChild(row));
                }});
            }});
        }})();
    </script>
</body>
</html>"""
    return HTMLResponse(content=html, headers={"Cache-Control": "no-store"})


def render_vigilance(csrf_token: str = "", username: str = "") -> HTMLResponse:
    entries = all_patients()
    patients = [patient for _, patient in entries]
    units = unit_summary()
    missing_updates = monthly_updates_missing()
    pending_patients = [
        (module, patient)
        for module, patient in entries
        if patient.followup_status == "Acompanhamento pendente" or patient.review_signal_demo
    ]
    metrics = "".join(
        (
            _metric("Pacientes demonstrativos", len(patients), "Tuberculose e hanseníase"),
            _metric("Pendências de acompanhamento", sum(
                patient.followup_status == "Acompanhamento pendente" for patient in patients
            ), "Soma fictícia"),
            _metric("Sinais para revisão humana", sum(
                patient.review_signal_demo for patient in patients
            ), "Não representam classificação clínica"),
            _metric("Contatos ainda não examinados", sum(
                patient.contacts_registered - patient.contacts_examined for patient in patients
            ), "Soma fictícia"),
            _metric("Unidades sem atualização", len(missing_updates), "Demonstração mensal"),
            _metric("Unidades no painel", len(units), "Agrupadas por distrito"),
        )
    )
    unit_rows = "".join(
        f"""<tr>
            <td>{escape(str(item['district']))}</td><td>{escape(str(item['unit']))}</td>
            <td>{item['tuberculose']}</td><td>{item['hanseniase']}</td>
            <td>{item['pending']}</td><td>{item['review']}</td><td>{item['contacts_pending']}</td>
            <td><span class="alert-level {'green' if item['updated'] else ''}">
                {'Atualizada (demo)' if item['updated'] else 'Sem atualização (demo)'}</span></td>
        </tr>"""
        for item in units
    )
    alert_rows = "".join(
        f"""<tr>
            <td><span class="alert-level">Amarelo</span></td>
            <td>{escape(module.name)}</td><td>{escape(patient.identifier)}</td>
            <td>{escape(patient.unit)}</td><td>{escape(patient.followup_status)}</td>
            <td>Conferir registro demonstrativo com a unidade.</td>
        </tr>"""
        for module, patient in pending_patients
    )
    missing_rows = "".join(
        f"<li>{escape(agravo)} — {escape(district)} — {escape(unit)}</li>"
        for agravo, district, unit in missing_updates
    )
    html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Vigilância | Monitoramento Ativo</title>
    <style>:root {{ --accent:var(--blue); }}</style>{MODULE_CSS}
</head>
<body>
    <header class="topbar"><a class="brand" href="/">Monitoramento Ativo</a>
        <a class="back" href="/">Página inicial</a>
        <form method="post" action="/logout"><input type="hidden" name="csrf_token"
            value="{escape(csrf_token)}"><span>{escape(username)}</span>
            <button type="submit">Sair</button></form></header>
    <div class="app-shell">
        <aside class="sidebar" aria-label="Navegação principal">
            <a href="/">Início</a><a href="/tuberculose">Tuberculose</a>
            <a href="/hanseniase">Hanseníase</a>
            <a class="active" href="/vigilancia">Visão da Vigilância</a>
        </aside>
        <main class="content">
            <p class="eyebrow">Consolidação demonstrativa</p>
            <h1>Painel geral da Vigilância</h1>
            <p class="intro">Resumo fictício por agravo, distrito e unidade de saúde.</p>
            <p class="demo-banner"><strong>Ambiente demonstrativo:</strong> todos os registros
                são fictícios. Não use esta visão para decisões clínicas ou de gestão real.</p>
            <p class="notice">A ausência em um boletim posterior exige verificação e não indica
                automaticamente abandono, cura, óbito ou transferência.</p>
            <section class="metrics" aria-label="Indicadores consolidados">{metrics}</section>
            <section class="panel" style="margin-top:24px">
                <h2>Indicadores por unidade e distrito</h2>
                <div class="table-wrap"><table class="alert-table">
                    <thead><tr><th>Distrito</th><th>Unidade</th><th>Tuberculose</th>
                        <th>Hanseníase</th><th>Pendências</th><th>Sinais para revisão</th>
                        <th>Contatos pendentes</th><th>Atualização mensal</th></tr></thead>
                    <tbody>{unit_rows}</tbody>
                </table></div>
            </section>
            <section class="panel" style="margin-top:20px">
                <h2>Alertas demonstrativos</h2>
                <p class="section-note">
                    <span class="alert-level red">Vermelho</span> reservado para critérios
                    prioritários a validar; sem classificação real nesta versão.
                    <span class="alert-level">Amarelo</span> verificar registro.
                    <span class="alert-level green">Verde</span> sem pendência fictícia.
                </p>
                <div class="table-wrap"><table class="alert-table">
                    <thead><tr><th>Nível</th><th>Agravo</th><th>Identificador fictício</th>
                        <th>Unidade</th><th>Situação</th><th>Ação sugerida</th></tr></thead>
                    <tbody>{alert_rows or '<tr><td colspan="6">Sem alertas demonstrativos.</td></tr>'}</tbody>
                </table></div>
            </section>
            <section class="units">
                <h2>Unidades sem atualização mensal</h2>
                <ul>{missing_rows or '<li>Nenhuma unidade fictícia sinalizada.</li>'}</ul>
            </section>
            <section class="units">
                <h2>Comparação e histórico mensal</h2>
                <p>Outubro/2026 versus Novembro/2026: comparação ilustrativa preparada.
                    Histórico real, importação de PDFs e identificação de novos/mantidos/ausentes
                    dependem de arquivos e regras validados; ausências apenas indicam necessidade
                    de verificação.</p>
            </section>
            <section class="units">
                <h2>Perfis de acesso futuros</h2>
                <p>Unidade de saúde, Vigilância distrital e Gestão central são apenas perfis
                    planejados. Esta página não implementa autenticação ou autorização; filtros
                    e navegação não são barreiras de segurança.</p>
            </section>
            <p class="footer">Protótipo local sem conexão Firebase ou envio externo de dados.</p>
        </main>
    </div>
</body>
</html>"""
    return HTMLResponse(content=html, headers={"Cache-Control": "no-store"})


def render_bulletin_summary(
    agravo: str,
    report: BulletinSummary,
    csrf_token: str = "",
) -> HTMLResponse:
    title = "Tuberculose" if agravo == "tuberculose" else "Hanseníase"
    total_records = sum(unit.records for unit in report.units) + report.records_without_unit
    observation_rows = "".join(
        f"""<tr>
            <td>{escape(unit.unit)}</td>
            <td>{unit.records}</td>
            <td>{unit.contacts_registered if report.contact_columns_found else "Não identificado"}</td>
            <td>{unit.contacts_examined if report.contact_columns_found else "Não identificado"}</td>
            <td>{unit.pending_contact_records if report.contact_columns_found else "Não calculado"}</td>
            <td>{unit.contact_records_to_check if report.contact_columns_found else "Layout não reconhecido"}</td>
            <td><textarea class="observation-input" data-observation-key="{escape(unit.unit)}"
                aria-label="Observação profissional para {escape(unit.unit)}"
                placeholder="Escreva uma observação local para esta unidade"></textarea></td>
        </tr>"""
        for unit in report.units
    )
    if report.records_without_unit:
        observation_rows += f"""<tr>
            <td>Unidade não identificada</td><td>{report.records_without_unit}</td>
            <td colspan="4">Conferir identificação da unidade no documento original.</td>
            <td><textarea class="observation-input" data-observation-key="sem-unidade"
                aria-label="Observação profissional para registros sem unidade identificada"
                placeholder="Escreva uma observação local"></textarea></td>
        </tr>"""
    if not observation_rows and report.empty_bulletin:
        observation_rows = (
            '<tr><td colspan="7">Boletim reconhecido sem linhas de casos; '
            "nenhum registro foi listado nesta competência.</td></tr>"
        )
    agravo_warning = "" if report.agravo_confirmed else (
        '<p class="demo-banner"><strong>Atenção:</strong> não foi possível confirmar o agravo '
        "pelo título extraído. Confira se selecionou o módulo correto.</p>"
    )
    contacts_note = (
        "As colunas de contatos foram reconhecidas. Pendentes significa somente que contatos "
        "registrados superam contatos examinados nos campos legíveis."
        if report.contact_columns_found
        else "Não foi possível reconhecer com segurança as colunas de contatos. Os totais e "
        "pendências de contato não foram calculados; confira o boletim manualmente."
    )
    storage_prefix_json = json.dumps(f"monitoramento-demo:boletim-observacao:{agravo}:")
    html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Resultado do boletim | {title}</title>
    <style>:root {{ --accent:var(--blue); }}</style>{MODULE_CSS}
</head>
<body>
    <header class="topbar"><a class="brand" href="/">Monitoramento Ativo</a>
        <a class="back" href="/{agravo}">Voltar ao módulo {title}</a>
        <form method="post" action="/logout"><input type="hidden" name="csrf_token"
            value="{escape(csrf_token)}"><button type="submit">Sair</button></form></header>
    <main class="content">
        <p class="eyebrow">Leitura local concluída</p>
        <h1>Resumo do boletim de {title}</h1>
        <p class="intro">Resumo agregado; o documento e os identificadores individuais não são exibidos.</p>
        {'<p class="demo-banner"><strong>Boletim em branco reconhecido:</strong> não foram encontradas linhas de casos. Isso indica somente que nenhum caso foi listado neste arquivo; não altera nem encerra registros anteriores.</p>' if report.empty_bulletin else ''}
        <p class="demo-banner"><strong>Privacidade:</strong> o aplicativo não grava o PDF como arquivo
            permanente. Durante a requisição, o FastAPI pode usar armazenamento temporário local.
            Observações abaixo ficam no armazenamento local deste navegador.</p>
        {agravo_warning}
        <section class="metrics" aria-label="Resumo do boletim">
            {_metric("Páginas lidas", report.pages, "Processamento local")}
            {_metric("Unidades identificadas", len(report.units), "Agrupamento demonstrativo")}
            {_metric("Registros contabilizados", total_records, "Sem exibir identificadores")}
            {_metric("Registros sem unidade", report.records_without_unit, "Conferir manualmente")}
        </section>
        <section class="units">
            <h2>Resumo por unidade e pendências</h2>
            <p>{escape(contacts_note)}</p>
            <div class="table-wrap"><table class="alert-table">
                <thead><tr><th>Unidade</th><th>Registros</th><th>Contatos registrados</th>
                    <th>Contatos examinados</th><th>Registros com contatos pendentes</th>
                    <th>Registros para conferir</th><th>Observação do profissional</th></tr></thead>
                <tbody>{observation_rows or '<tr><td colspan="7">Nenhuma unidade foi reconhecida; confira o PDF.</td></tr>'}</tbody>
            </table></div>
            <p id="observation-status" class="save-state" role="status" aria-live="polite">
                Observações são locais e demonstrativas; não são enviadas nem compartilhadas.</p>
        </section>
        <section class="units">
            <h2>Limites desta análise</h2>
            <p>O sistema conta registros reconhecidos e, quando identifica as colunas, compara
                contatos registrados e examinados. Isso não valida a completude clínica nem define
                abandono, cura, óbito ou transferência. Ausências e inconsistências precisam de
                revisão profissional. PDFs digitalizados exigem OCR, não incluído.</p>
        </section>
    </main>
    <script>
        (() => {{
            const prefix = {storage_prefix_json};
            const status = document.getElementById("observation-status");
            try {{
                document.querySelectorAll("[data-observation-key]").forEach((field) => {{
                    const key = prefix + field.dataset.observationKey;
                    const saved = localStorage.getItem(key);
                    if (saved !== null) field.value = saved;
                    field.addEventListener("input", () => {{
                        try {{
                            localStorage.setItem(key, field.value);
                            status.textContent = "Observação salva apenas neste navegador.";
                        }} catch (error) {{
                            status.textContent = "Falha ao salvar localmente: " + error.message;
                        }}
                    }});
                }});
            }} catch (error) {{
                status.textContent = "Falha ao acessar armazenamento local: " + error.message;
            }}
        }})();
    </script>
</body>
</html>"""
    return HTMLResponse(content=html, headers={"Cache-Control": "no-store"})
