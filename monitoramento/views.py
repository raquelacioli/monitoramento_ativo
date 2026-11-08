import json
from html import escape
from urllib.parse import quote, urlencode

from fastapi.responses import HTMLResponse

from monitoramento.data import ModuleDemo, PatientDemo
from monitoramento.bulletin_forms import BULLETIN_FIELDS, BulletinField, BulletinOption
from monitoramento.auth import User
from monitoramento.monthly_store import MonthlyFollowup
from monitoramento.pdf_analysis import BulletinSummary
from monitoramento.services import (
    all_patients,
    monthly_comparison_demo,
    monthly_updates_missing,
    module_alerts,
    unit_summary,
)
from monitoramento.tracking_store import FOLLOWUP_STATUSES

NOTIFICATION_NUMBER_LABEL = next(
    field.label
    for field in BULLETIN_FIELDS["tuberculose"]
    if field.key == "numero_notificacao"
)

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
    .inline-response { display:grid; gap:8px; min-width:260px; margin-top:12px;
        padding:12px; border:1px solid var(--line); border-radius:10px; background:#f8fafc; }
    .inline-response textarea { width:100%; min-height:72px; padding:8px;
        border:1px solid #d5dee8; border-radius:7px; font:inherit; }
    .inline-response .actions { display:flex; flex-wrap:wrap; gap:7px; }
    .inline-response button { padding:8px 11px; border:0; border-radius:7px;
        background:var(--accent); color:#fff; font-weight:650; cursor:pointer; }
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
    .password-control { display:flex; position:relative; }
    .password-control input { flex:1; min-width:0; padding-right:48px !important; }
    .password-toggle { position:absolute; right:4px; top:4px; width:36px; height:34px;
        display:grid; place-items:center; padding:0; border:0; border-radius:6px;
        background:transparent !important; color:var(--muted) !important; cursor:pointer; }
    .password-toggle:focus-visible { outline:2px solid var(--blue); outline-offset:1px; }
    .password-toggle svg { width:20px; height:20px; }
    .password-toggle .eye-off { display:none; }
    .password-toggle[aria-pressed="true"] .eye-open { display:none; }
    .password-toggle[aria-pressed="true"] .eye-off { display:block; }
    .auth-link { color:var(--blue); font-weight:600; }
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
                <p class="form-warning">Campos e códigos transcritos das fichas em branco fornecidas.
                    A confirmação destes rótulos não equivale à validação integral do dicionário SINAN.
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
            f'<option value="{escape(choice.code)}" '
            f'{"selected" if _choice_matches_value(choice, value) else ""}>'
            f'{escape(choice.code)} - {escape(choice.description)}</option>'
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
    conditional_attributes = (
        f' data-transfer-field="{escape(form_id)}" hidden'
        if field.key == "tipo_transferencia"
        else ""
    )
    return (
        f'<label class="form-field" for="{escape(field_id)}"{conditional_attributes}>'
        f'{label}{control}</label>'
    )


def _choice_matches_value(choice: BulletinOption, value: str) -> bool:
    return value in (
        choice.code,
        f"{choice.code} - {choice.description}",
    )


def _field_input_value(value: object) -> str:
    if isinstance(value, dict):
        code = value.get("codigo", "")
        return str(code) if code is not None else ""
    return "" if value is None else str(value)


def _format_bulletin_value(value: object) -> str:
    if value is None or value == "":
        return "Não informado"
    if isinstance(value, dict):
        code = value.get("codigo", "")
        description = value.get("descricao", "")
        return f"{code} — {description}" if description else str(code)
    return str(value)


def _metric(label: str, value: int | str, detail: str) -> str:
    return (
        '<article class="metric">'
        f'<span class="metric-label">{escape(label)}</span>'
        f'<strong class="metric-value">{escape(str(value))}</strong>'
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
        <meta name="referrer" content="no-referrer">
        <title>Acesso da equipe | Monitoramento Ativo</title>{MODULE_CSS}</head><body>
        <header class="topbar"><a class="brand" href="/">Monitoramento Ativo</a></header>
        <main class="auth-card"><p class="eyebrow">Acesso restrito</p><h1>Entrar</h1>
        <p>Use a conta fornecida pelo administrador. Não há cadastro público.</p>
        {error_html}<form class="auth-form" method="post" action="/login">
        <input type="hidden" name="csrf_token" value="{escape(csrf_token)}">
        <label class="form-field">Usuário<input name="username" autocomplete="username"
            required maxlength="80"></label>
        <label class="form-field">Senha{_password_control("login-password", "password", "current-password")}</label>
        <a class="auth-link" href="/recuperar-senha">Esqueceu sua senha?</a>
        <button type="submit">Entrar</button></form>
        <p class="form-warning">Protótipo: use somente dados fictícios. Os formulários ainda não
            foram validados com documentação oficial para uso assistencial.</p></main>
        {_password_toggle_script()}</body></html>""",
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
    )


def _password_control(input_id: str, name: str, autocomplete: str) -> str:
    return f"""<span class="password-control">
        <input id="{escape(input_id)}" type="password" name="{escape(name)}"
            autocomplete="{escape(autocomplete)}" required minlength="12" maxlength="256">
        <button class="password-toggle" type="button" aria-label="Mostrar senha"
            aria-pressed="false" aria-controls="{escape(input_id)}">
            <svg class="eye-open" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
                aria-hidden="true"><path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7-10-7-10-7Z"/>
                <circle cx="12" cy="12" r="3"/></svg>
            <svg class="eye-off" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
                aria-hidden="true"><path d="M3 3l18 18M10.6 10.6a2 2 0 0 0 2.8 2.8"/>
                <path d="M9.9 5.2A10.7 10.7 0 0 1 12 5c6.4 0 10 7 10 7a14 14 0 0 1-3.1 3.8M6.2 6.2C3.5 8 2 12 2 12s3.6 7 10 7a10 10 0 0 0 4-.8"/></svg>
        </button></span>"""


def _password_toggle_script() -> str:
    return """<script>
        document.querySelectorAll(".password-toggle").forEach((button) => {
            button.addEventListener("click", () => {
                const input = document.getElementById(button.getAttribute("aria-controls"));
                const visible = input.type === "password";
                input.type = visible ? "text" : "password";
                button.setAttribute("aria-pressed", String(visible));
                button.setAttribute("aria-label", visible ? "Ocultar senha" : "Mostrar senha");
                input.focus();
            });
        });
    </script>"""


def render_password_recovery(
    csrf_token: str,
    submitted: bool = False,
) -> HTMLResponse:
    notice = (
        "Se o e-mail informado estiver cadastrado, você receberá as instruções para redefinir sua senha."
        if submitted
        else "Informe o e-mail cadastrado no sistema. Se existir uma conta vinculada a esse endereço, "
        "você receberá um link para redefinir sua senha."
    )
    return HTMLResponse(
        f"""<!DOCTYPE html><html lang="pt-BR"><head><meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <meta name="referrer" content="no-referrer">
        <title>Recuperar senha | Monitoramento Ativo</title>{MODULE_CSS}</head><body>
        <header class="topbar"><a class="brand" href="/">Monitoramento Ativo</a></header>
        <main class="auth-card"><p class="eyebrow">Acesso restrito</p><h1>Recuperar senha</h1>
        <p role="status">{escape(notice)}</p>
        <form class="auth-form" method="post" action="/recuperar-senha">
        <input type="hidden" name="csrf_token" value="{escape(csrf_token)}">
        <label class="form-field">E-mail cadastrado<input type="email" name="email"
            autocomplete="email" maxlength="254" required></label>
        <button type="submit">Enviar link de recuperação</button></form>
        <p><a class="auth-link" href="/login">Voltar para o login</a></p>
        </main></body></html>""",
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
    )


def render_password_reset(
    csrf_token: str,
    token: str = "",
    error: str = "",
    success: bool = False,
) -> HTMLResponse:
    if success:
        body = """<p role="status">Senha redefinida com sucesso. Você já pode acessar o sistema
            com sua nova senha.</p><p><a class="auth-link" href="/login">Voltar para o login</a></p>"""
    else:
        error_html = f'<p class="auth-error" role="alert">{escape(error)}</p>' if error else ""
        body = f"""{error_html}<p>Escolha uma nova senha com pelo menos 12 caracteres.</p>
        <form class="auth-form" method="post" action="/redefinir-senha">
        <input type="hidden" name="csrf_token" value="{escape(csrf_token)}">
        <input type="hidden" id="reset-token" name="token" value="{escape(token)}">
        <label class="form-field">Nova senha{_password_control("new-password", "password", "new-password")}</label>
        <label class="form-field">Confirmar nova senha{_password_control("confirm-password", "confirmation", "new-password")}</label>
        <button type="submit">Definir nova senha</button></form>
        <p><a class="auth-link" href="/login">Voltar para o login</a></p>
        <script>
            const params = new URLSearchParams(window.location.hash.slice(1));
            const resetToken = params.get("token") || "";
            if (resetToken) document.getElementById("reset-token").value = resetToken;
            history.replaceState(null, "", window.location.pathname);
        </script>{_password_toggle_script()}"""
    return HTMLResponse(
        f"""<!DOCTYPE html><html lang="pt-BR"><head><meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <meta name="referrer" content="no-referrer">
        <title>Definir nova senha | Monitoramento Ativo</title>{MODULE_CSS}</head><body>
        <header class="topbar"><a class="brand" href="/">Monitoramento Ativo</a></header>
        <main class="auth-card"><p class="eyebrow">Segurança da conta</p>
        <h1>Definir nova senha</h1>{body}</main></body></html>""",
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
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
    actor_id: int | None = None,
) -> HTMLResponse:
    error_html = f'<p class="auth-error" role="alert">{escape(error)}</p>' if error else ""
    success_html = f'<p class="save-state" role="status">{escape(success)}</p>' if success else ""
    role_names = {"unit": "Unidade", "surveillance": "Vigilância", "admin": "Administrador"}
    rows = "".join(
        f"""<tr><td>{escape(user.username)}</td><td>{role_names[user.role]}</td>
        <td>{escape(user.unit or "—")}</td><td>{"Ativa" if user.active else "Desativada"}</td>
        <td>{'<span>Não cadastrado</span>' if not user.email else escape(user.email)}
            <form method="post" action="/admin/usuarios/{user.id}/email">
            <input type="hidden" name="csrf_token" value="{escape(csrf_token)}">
            <label class="sr-only" for="recovery-email-{user.id}">E-mail autorizado de {escape(user.username)}</label>
            <input id="recovery-email-{user.id}" type="email" name="email"
                value="{escape(user.email or '')}" maxlength="254"
                aria-label="E-mail autorizado de {escape(user.username)}">
            <button type="submit">Salvar e-mail</button></form></td>
        <td>{"Troca de senha obrigatória" if user.must_change_password else "—"}</td>
        <td>{"—" if user.id == actor_id else ("".join(()) if not user.active else f'<details><summary>Redefinir senha</summary>'
            f'<form method="post" action="/admin/usuarios/{user.id}/senha">'
            f'<input type="hidden" name="csrf_token" value="{escape(csrf_token)}">'
            f'<label class="form-field" for="new-password-{user.id}">Nova senha temporária (mínimo 12 caracteres)</label>'
            f'<input id="new-password-{user.id}" type="password" name="password" '
            'minlength="12" maxlength="256" autocomplete="new-password" required>'
            f'<label class="form-field" for="confirm-password-{user.id}">Confirme a senha temporária</label>'
            f'<input id="confirm-password-{user.id}" type="password" name="confirmation" '
            'minlength="12" maxlength="256" autocomplete="new-password" required>'
            '<button type="submit">Definir senha temporária</button></form></details>'
            f'<form method="post" action="/admin/usuarios/{user.id}/desativar">'
            f'<input type="hidden" name="csrf_token" value="{escape(csrf_token)}">'
            '<button type="submit">Desativar</button></form>')}
        {"—" if user.id == actor_id else f'<form method="post" action="/admin/usuarios/{user.id}/excluir" '
            'onsubmit="return confirm(&quot;Excluir esta conta permanentemente? Esta ação não pode ser desfeita.&quot;);">'
            f'<input type="hidden" name="csrf_token" value="{escape(csrf_token)}">'
            '<button type="submit">Excluir usuário</button></form>'}</td></tr>"""
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
        <p>O administrador cria contas e pode definir uma senha temporária para uma conta ativa.
            No próximo acesso, a pessoa deverá cadastrar sua própria senha. Não compartilhe
            senhas temporárias pelo sistema.</p>
        <p>Também é possível excluir definitivamente outra conta. A exclusão remove o acesso,
            mas preserva o histórico de acompanhamento. Confira a confirmação antes de prosseguir;
            essa ação não pode ser desfeita.</p>
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
        <label class="form-field">E-mail autorizado para recuperação (opcional)
            <input type="email" name="email" autocomplete="email" maxlength="254"></label>
        <label class="form-field">Senha temporária (mínimo 12 caracteres)
            <input type="password" name="password" minlength="12" maxlength="256"
                autocomplete="new-password" required></label>
        <button type="submit">Criar conta</button></form></section>
        <section class="panel" style="margin-top:20px"><h2>Usuários cadastrados</h2>
        <div class="table-wrap"><table class="account-table"><thead><tr>
        <th>Usuário</th><th>Perfil</th><th>Unidade</th><th>Estado</th>
        <th>E-mail de recuperação</th><th>Senha</th><th>Ações</th></tr></thead><tbody>{rows}</tbody></table></div></section>
        </main></body></html>"""
    )


def _bar(label: str, value: int, maximum: int) -> str:
    width = min(100, round(value / max(maximum, 1) * 100))
    return (
        '<div class="bar-row">'
        f'<span>{escape(label)}</span><div class="bar-track"><div class="bar-fill" '
        f'style="width:{width}%"></div></div><strong>{value}</strong></div>'
    )


def _comparison_panel(module: ModuleDemo, patients: tuple[PatientDemo, ...]) -> str:
    scoped_module = ModuleDemo(
        module.key,
        module.name,
        module.accent,
        patients,
        module.units_without_monthly_update,
    )
    comparison = monthly_comparison_demo(scoped_module)
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
    communications: tuple[MonthlyFollowup, ...] = (),
) -> HTMLResponse:
    patients = module.patients if patients is None else patients
    contacts_registered = sum(patient.contacts_registered for patient in patients)
    contacts_examined = sum(patient.contacts_examined for patient in patients)
    pending_count = sum(patient.followup_status == "Acompanhamento pendente" for patient in patients)
    ending_count = sum(patient.ending_soon_demo for patient in patients)
    review_count = sum(patient.review_signal_demo for patient in patients)
    new_count = sum(patient.new_this_month_demo for patient in patients)
    visible_units = (
        [unit_filter]
        if editable and unit_filter
        else sorted({patient.unit for patient in patients})
    )
    units_without_update = tuple(
        unit for unit in module.units_without_monthly_update if unit in visible_units
    )
    units_missing = len(units_without_update)
    units = visible_units if editable else sorted({patient.unit for patient in module.patients})
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
        if editable:
            rows = f"""<tr><td colspan="14" class="no-results">
                <strong>Nenhum registro corresponde aos filtros desta unidade.</strong>
                <p>Esta lista contém os registros demonstrativos da unidade.
                As fichas importadas pela Vigilância ficam no painel de envio mensal.</p>
                <a class="monthly-update-button" href="/monitoramento-mensal?agravo={escape(module.key)}">
                    Abrir painel de envio mensal</a>
                </td></tr>"""
        else:
            rows = (
                '<tr><td colspan="14" class="no-results">'
                "Nenhum registro corresponde aos filtros."
                "</td></tr>"
            )
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
    monthly_update_panel = f"""
        <section class="panel monthly-update-entry" aria-labelledby="monthly-update-title">
            <h2 id="monthly-update-title">Envio do boletim mensal</h2>
            <p>Para atualizar uma ficha oficial e encaminhá-la à Vigilância, abra o painel mensal.
                As alterações demonstrativas desta página não enviam o boletim.</p>
            <a class="monthly-update-button" href="/monitoramento-mensal?agravo={module.key}">
                Abrir fichas mensais para atualizar e enviar</a>
        </section>"""
    upload_panel = "" if editable else f"""
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
        </section>"""
    vigilance_link = '<a href="/vigilancia">Visão da Vigilância</a>' if not editable else ""
    vigilance_back_link = (
        '<a class="back" href="/vigilancia">Painel geral da Vigilância</a>'
        if not editable
        else ""
    )
    unit_update_heading = (
        "Atualização da minha unidade" if editable else "Unidades sem atualização mensal"
    )
    communication_rows_list = []
    for item in communications:
        field_label = next(
            (
                field.label for field in BULLETIN_FIELDS[item.agravo]
                if field.key == item.field_key
            ),
            "Observações gerais",
        )
        response_form = ""
        if editable and item.state in {"awaiting_unit", "needs_more_info", "responded"}:
            response_form = f"""
                <form class="inline-response" method="post"
                    action="/comunicacao/{item.id}/responder">
                    <input type="hidden" name="csrf_token" value="{escape(csrf_token)}">
                    <label class="filter-field">Resposta / justificativa da unidade
                        <textarea name="text" maxlength="4000" rows="3"
                            placeholder="Escreva sua resposta neste campo do boletim">{escape(item.draft_text or item.response_text)}</textarea>
                    </label>
                    <div class="actions">
                        <button name="submit" value="draft" type="submit">Salvar rascunho</button>
                        <button name="submit" value="submitted" type="submit">Enviar resposta</button>
                    </div>
                </form>"""
        elif editable:
            response_form = (
                "<p class=\"section-note\">A resposta fica disponível quando a Vigilância "
                "enviar a solicitação.</p>"
            )
        communication_rows_list.append(
            f"""<tr><td>{escape(item.competence)}</td><td>{escape(item.patient_ref)}</td>
                <td>{escape(item.unit_ref)}</td><td>{escape(field_label)}</td>
                <td>{escape(item.state.replace("_", " ").title())}</td>
                <td><p><strong>Observação da Vigilância:</strong><br>
                    {escape(item.vigilance_text or item.automatic_text)}</p>
                    <p><strong>Resposta da unidade:</strong><br>
                    {escape(item.response_text or "Ainda não enviada.")}</p>
                    {response_form}</td>
                <td><a href="/comunicacao/{item.id}">Ver campo e histórico</a></td></tr>"""
        )
    communication_rows = "".join(communication_rows_list)
    communication_panel = f"""
        <section class="panel" style="margin-top:20px">
            <h2>Observações da Vigilância e resposta da unidade</h2>
            <p class="section-note">As solicitações vinculadas ao boletim aparecem aqui.
                Responda no mesmo local; a justificativa não substitui nem altera o valor oficial do campo.</p>
            <div class="table-wrap"><table class="alert-table">
                <thead><tr><th>Competência</th><th>{escape(NOTIFICATION_NUMBER_LABEL)}</th><th>Unidade</th>
                    <th>Campo do boletim</th><th>Situação</th>
                    <th>Orientação e resposta</th><th>Histórico</th></tr></thead>
                <tbody>{communication_rows or '<tr><td colspan="7">Nenhuma solicitação da Vigilância para esta unidade e agravo.</td></tr>'}</tbody>
            </table></div>
            <p><a href="/comunicacao">Ver todas as comunicações mensais</a></p>
        </section>"""
    units_without_update_text = (
        "Sua unidade está sem atualização mensal (demonstração)."
        if editable and units_without_update
        else (
            "Sua unidade sem sinalização de atraso (demonstração)."
            if editable
            else (
                ", ".join(escape(unit) for unit in units_without_update)
                if units_without_update
                else "Nenhuma unidade fictícia sinalizada neste exemplo."
            )
        )
    )
    html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta name="theme-color" content="#f5f8fc">
    <title>{title} | Monitoramento Ativo</title>
    <style>
        :root {{ --accent: var(--{module.accent}); }}
        .monthly-update-entry {{ margin-top:18px; border-left:4px solid var(--accent); }}
        .monthly-update-entry p {{ margin:0 0 12px; color:var(--muted); }}
        .monthly-update-button {{ display:inline-flex; min-height:42px; align-items:center;
            padding:9px 14px; border-radius:8px; background:var(--accent); color:#fff;
            font-weight:700; text-decoration:none; }}
        .monthly-update-button:hover {{ filter:brightness(.92); }}
    </style>{MODULE_CSS}
</head>
<body>
    <header class="topbar">
        <a class="brand" href="/">Monitoramento Ativo</a>
        {vigilance_back_link}
        <form method="post" action="/logout"><input type="hidden" name="csrf_token"
            value="{escape(csrf_token)}"><span>{escape(username)}</span>
            <button type="submit">Sair</button></form>
    </header>
    <div class="app-shell">
    <aside class="sidebar" aria-label="Navegação principal">
        <a href="/">Início</a>
        <a href="/tuberculose" class="{'active' if module.key == 'tuberculose' else ''}">Tuberculose</a>
        <a href="/hanseniase" class="{'active' if module.key == 'hanseniase' else ''}">Hanseníase</a>
        {vigilance_link}
        <a href="/comunicacao">Comunicações mensais</a>
            <a href="/monitoramento-mensal">Envio mensal de boletins</a>
    </aside>
    <main class="content">
        <p class="eyebrow">Módulo demonstrativo</p>
        <h1>{title}</h1>
        <p class="intro">Visão demonstrativa de acompanhamento, contatos e pendências.</p>
        {monthly_update_panel}
        <p class="demo-banner"><strong>Dados fictícios:</strong> todos os indicadores e registros
            desta página são apenas demonstrativos. Não há classificação clínica implementada.
            Não insira dados reais ou identificáveis: campos, códigos e regras aguardam validação
            com documentação oficial. As alterações são salvas no SQLite local.</p>
        {'<p class="save-state" role="status">Alterações salvas no servidor local.</p>' if saved else ''}
        {upload_panel}
        <p class="notice">A ausência de um registro em boletim posterior não significa,
            por si só, abandono ou cura. Os critérios oficiais ainda não foram configurados.</p>
        <section class="metrics" aria-label="Indicadores demonstrativos">{metrics}</section>
        <form class="filter-form" method="get" aria-label="Filtros da tabela demonstrativa">
            <label class="filter-field">Pesquisar {escape(NOTIFICATION_NUMBER_LABEL)}
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
            {_comparison_panel(module, patients)}
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
                <thead><tr><th>Nível</th><th>{escape(NOTIFICATION_NUMBER_LABEL)}</th><th>Unidade</th>
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
                        <th><button type="button" data-sort="0">{escape(NOTIFICATION_NUMBER_LABEL)}</button></th>
                        <th><button type="button" data-sort="1">Unidade / distrito</button></th>
                        <th>Agravo</th><th><button type="button" data-sort="3">Início do tratamento</button></th>
                        <th><button type="button" data-sort="4">Mês de referência</button></th>
                        <th><button type="button" data-sort="5">Situação</button></th>
                        <th><button type="button" data-sort="6">Término previsto</button></th>
                        <th>Contatos registrados / examinados</th><th>Pendências</th>
                        <th>Observação automática</th><th>Observação da unidade</th>
                        <th>Última atualização</th><th>Detalhes</th>
                        <th>Data do último comparecimento</th>
                    </tr></thead>
                    <tbody>{rows}</tbody>
                </table>
            </div>
            {communication_panel}
            <p class="save-state" role="status" aria-live="polite">
                {"Para registrar uma observação do profissional, use a coluna “Observação da unidade” e clique em “Salvar alterações”. Para responder à Vigilância, abra “Comunicações mensais” e preencha “Resposta da unidade”. Use somente dados fictícios nesta versão." if editable else "As observações e respostas da unidade ficam disponíveis em “Comunicações mensais”; a Vigilância não altera essas respostas."}</p>
        </section>
        <section class="units" aria-labelledby="unidades-titulo">
            <h2 id="unidades-titulo">{unit_update_heading}</h2>
            <p>{units_without_update_text}</p>
        </section>
        <p class="footer">Protótipo local sem integração Firebase ou processamento de dados reais.
            Os acessos são limitados pelo perfil e vínculo de unidade.</p>
    </main>
    </div>
    <script>
        (() => {{
            const uploadForm = document.querySelector(".upload-controls");
            if (uploadForm) {{
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
            }}
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
            document.querySelectorAll("[data-transfer-field]").forEach((field) => {{
                const closureSelect = Array.from(
                    document.querySelectorAll('select[name="situacao_encerramento"]')
                ).find((select) => select.form.id === field.dataset.transferField);
                if (!closureSelect) return;
                const updateTransferVisibility = () => {{
                    field.hidden = closureSelect.value !== "5";
                }};
                closureSelect.addEventListener("change", updateTransferVisibility);
                updateTransferVisibility();
            }});
        }})();
    </script>
</body>
</html>"""
    return HTMLResponse(content=html, headers={"Cache-Control": "no-store"})


def render_monthly_followup_dashboard(
    *,
    followups: tuple[MonthlyFollowup, ...],
    csrf_token: str,
    role: str,
    username: str,
    selected_agravo: str,
    selected_competence: str,
    selected_state: str,
    selected_unit: str,
    metrics: dict[str, object],
) -> HTMLResponse:
    state_labels = {
        "automatic_suggestion": "Sugestão automática — revisão pendente",
        "awaiting_unit": "Aguardando unidade",
        "responded": "Respondida — análise da Vigilância",
        "under_review": "Em análise",
        "needs_more_info": "Solicitada complementação",
        "resolved": "Concluída",
    }
    rows = "".join(
        f"""<tr><td>{escape(item.competence)}</td><td>{escape(item.agravo.title())}</td>
            <td>{escape(item.unit_ref)}</td><td>{escape(item.patient_ref)}</td>
            <td>{escape(next(
                (field.label for field in BULLETIN_FIELDS[item.agravo]
                 if field.key == item.field_key),
                "Observações gerais",
            ))}</td>
            <td>{escape(state_labels.get(item.state, item.state))}</td>
            <td>{escape(item.vigilance_text or item.automatic_text)}</td>
            <td>{escape(item.response_text)}</td>
            <td><a href="/comunicacao/{item.id}">Abrir</a></td></tr>"""
        for item in followups
    )
    agravo_options = "".join(
        f'<option value="{value}" {"selected" if selected_agravo == value else ""}>{label}</option>'
        for value, label in (("tuberculose", "Tuberculose"), ("hanseniase", "Hanseníase"))
    )
    state_options = "".join(
        f'<option value="{value}" {"selected" if selected_state == value else ""}>{label}</option>'
        for value, label in state_labels.items()
    )
    field_options = ['<option value="">Observação geral (sem campo)</option>']
    for agravo_key, fields in BULLETIN_FIELDS.items():
        field_options.extend(
            f'<option value="{escape(field.key)}" data-agravo="{agravo_key}">'
            f'{escape(field.label)} — {agravo_key.title()}</option>'
            for field in fields
            if field.monthly_editable
        )
    stat_cards = "".join(
        _metric(label, metrics.get(key, 0), "Conforme os filtros e o escopo do perfil")
        for key, label in (
            ("total", "Comunicações registradas"),
            ("respostas_enviadas", "Respostas enviadas"),
        )
    )
    manual_form = ""
    if role == "surveillance":
        manual_form = f"""
        <section class="panel" style="margin-top:20px">
            <h2>Nova solicitação da Vigilância</h2>
            <p>Use somente a competência e o identificador presentes em um registro mensal importado.
                A solicitação não atualiza nem substitui dados do SINAN.</p>
            <form class="filter-form" method="post" action="/comunicacao/manual">
                <input type="hidden" name="csrf_token" value="{escape(csrf_token)}">
                <label class="filter-field">Agravo
                    <select name="agravo" required>{agravo_options}</select></label>
                <label class="filter-field">Competência (AAAA-MM)
                    <input name="competence" value="{escape(selected_competence)}"
                        placeholder="2026-11" pattern="[0-9]{{4}}-(0[1-9]|1[0-2])" required></label>
                <label class="filter-field">{escape(NOTIFICATION_NUMBER_LABEL)}
                    <input name="patient_ref" maxlength="120" required></label>
                <label class="filter-field">Prioridade
                    <select name="priority"><option value="normal">Normal</option>
                        <option value="low">Baixa</option><option value="high">Alta</option></select></label>
                <label class="filter-field">Campo do boletim
                    <select id="manual-field-key" name="field_key">
                        {"".join(field_options)}</select></label>
                <label class="filter-field" style="grid-column:1/-1">Solicitação
                    <textarea name="text" maxlength="2000" rows="3" required></textarea></label>
                <button type="submit">Enviar solicitação à unidade</button>
            </form>
        </section>"""
    html = f"""<!DOCTYPE html>
<html lang="pt-BR"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Comunicações mensais | Monitoramento Ativo</title>{MODULE_CSS}</head>
<body><header class="topbar"><a class="brand" href="/">Monitoramento Ativo</a>
<a class="back" href="/vigilancia">Painel da Vigilância</a>
<form method="post" action="/logout"><input type="hidden" name="csrf_token" value="{escape(csrf_token)}">
<span>{escape(username)}</span><button type="submit">Sair</button></form></header>
<div class="app-shell"><aside class="sidebar" aria-label="Navegação principal">
<a href="/">Início</a><a href="/tuberculose">Tuberculose</a><a href="/hanseniase">Hanseníase</a>
<a href="/vigilancia">Visão da Vigilância</a><a class="active" href="/comunicacao">Comunicações mensais</a>
</aside><main class="content"><p class="eyebrow">Acompanhamento longitudinal</p>
<h1>Comunicações mensais</h1>
<p class="intro">Sugestões, solicitações da Vigilância e respostas das unidades, com trilha de auditoria.</p>
<p class="notice">A ausência de resposta não é interpretada como falta de atendimento, abandono ou encerramento.
As sugestões automáticas limitam-se à diferença objetiva entre contatos informados e examinados.</p>
<section class="metrics" aria-label="Resumo das comunicações">{stat_cards}</section>
<form class="filter-form" method="get" aria-label="Filtros de comunicações">
<label class="filter-field">Agravo<select name="agravo"><option value="">Todos</option>{agravo_options}</select></label>
<label class="filter-field">Competência (AAAA-MM)
<input name="competence" value="{escape(selected_competence)}" placeholder="2026-11"></label>
<label class="filter-field">Situação<select name="state"><option value="">Todas</option>{state_options}</select></label>
<label class="filter-field">Unidade<input name="unit" value="{escape(selected_unit)}" maxlength="100"
{"disabled" if role == "unit" else ""}></label>
<button type="submit">Filtrar</button></form>
<section class="panel"><h2>Histórico de solicitações e respostas</h2>
<div class="table-wrap"><table class="alert-table"><thead><tr><th>Competência</th><th>Agravo</th>
<th>Unidade</th><th>{escape(NOTIFICATION_NUMBER_LABEL)}</th><th>Campo do boletim</th><th>Situação</th><th>Solicitação</th><th>Resposta mais recente</th>
<th>Abrir</th></tr></thead><tbody>{rows or '<tr><td colspan="9">Nenhuma comunicação encontrada.</td></tr>'}
</tbody></table></div></section>{manual_form}
<script>
document.addEventListener("DOMContentLoaded", () => {{
    const agravo = document.querySelector('select[name="agravo"]');
    const field = document.getElementById("manual-field-key");
    if (!agravo || !field) return;
    const updateFields = () => {{
        for (const option of field.options) {{
            const optionAgravo = option.dataset.agravo;
            option.hidden = Boolean(optionAgravo && optionAgravo !== agravo.value);
            option.disabled = option.hidden;
        }}
        if (field.selectedOptions[0]?.disabled) field.value = "";
    }};
    agravo.addEventListener("change", updateFields);
    updateFields();
}});
</script>
<p class="footer">Ferramenta de apoio local; não atualiza o SINAN nem substitui a avaliação profissional.</p>
</main></div></body></html>"""
    return HTMLResponse(content=html, headers={"Cache-Control": "no-store"})


def render_monthly_monitoring(
    *,
    rows: tuple[dict[str, object], ...],
    all_rows: tuple[dict[str, object], ...],
    role: str,
    username: str,
    csrf_token: str,
    selected_agravo: str,
    selected_competence: str,
    selected_unit: str,
    selected_state: str,
    selected_patient_state: str,
    saved_state: str,
    pending_only: bool,
    silent_only: bool,
    available_competences: tuple[str, ...],
    deadline: dict[str, str | None] | None,
) -> HTMLResponse:
    status_labels = {
        "data_unavailable": "Dados indisponíveis",
        "awaiting": "Aguardando prazo",
        "no_update": "Vermelho · sem atualização após o prazo",
        "partial": "Amarelo · atualização parcial",
        "complete": "Verde · atualização concluída",
        "silent_pending": "Azul · unidade silenciosa, confirmação pendente",
        "silent_confirmed": "Azul · ausência confirmada",
        "reconciliation_required": "Amarelo · conferência de pacientes pendente",
    }
    status_classes = {
        "data_unavailable": "monitor-status unavailable",
        "awaiting": "monitor-status awaiting",
        "no_update": "monitor-status red",
        "partial": "monitor-status yellow",
        "complete": "monitor-status green",
        "silent_pending": "monitor-status blue",
        "silent_confirmed": "monitor-status blue",
        "reconciliation_required": "monitor-status yellow",
    }
    patient_labels = {
        "complete": "Verde · atualização enviada",
        "partial": "Amarelo · rascunho ou devolvido",
        "no_update": "Vermelho · não atualizado após o prazo",
        "awaiting": "Aguardando atualização",
    }
    patient_classes = {
        "complete": "monitor-status green",
        "partial": "monitor-status yellow",
        "no_update": "monitor-status red",
        "awaiting": "monitor-status awaiting",
    }
    agravo_labels = {"tuberculose": "Tuberculose", "hanseniase": "Hanseníase"}
    state_options = "".join(
        f'<option value="{escape(value)}" {"selected" if selected_state == value else ""}>'
        f'{escape(label)}</option>'
        for value, label in status_labels.items()
    )
    agravo_options = "".join(
        f'<option value="{value}" {"selected" if selected_agravo == value else ""}>'
        f'{label}</option>'
        for value, label in agravo_labels.items()
    )
    competence_options = "".join(
        f'<option value="{escape(value)}" {"selected" if value == selected_competence else ""}>'
        f'{escape(value)}</option>'
        for value in available_competences
    )
    by_agravo = {
        agravo: tuple(row for row in all_rows if row["agravo"] == agravo)
        for agravo in agravo_labels
    }
    def summary_link(label: str, value: str, query_key: str) -> str:
        params = {
            "agravo": selected_agravo,
            "competence": selected_competence,
            "unit": selected_unit,
            "state": selected_state if query_key == "patient_state" else "",
            "patient_state": selected_patient_state if query_key == "state" else "",
        }
        params[query_key] = value
        query = escape(urlencode({key: item for key, item in params.items() if item}))
        return (
            f'<a class="summary-link" href="/monitoramento-mensal?{query}">'
            f'{escape(label)}</a>'
        )

    summary_sections = []
    for agravo, label in agravo_labels.items():
        items = by_agravo[agravo]
        if selected_agravo and selected_agravo != agravo:
            continue
        expected = sum(int(item["patients_expected"]) for item in items)
        updated = sum(int(item["patients_updated"]) for item in items)
        reconciliation_count = sum(
            item["situation"] == "reconciliation_required" for item in items
        )
        overdue_count = sum(item["situation"] == "no_update" for item in items)
        partial_units = sum(item["situation"] == "partial" for item in items)
        complete_units = sum(item["situation"] == "complete" for item in items)
        silent_confirmed = sum(
            item["situation"] == "silent_confirmed" for item in items
        )
        percentage = round(updated * 100 / expected) if expected else 0
        patient_totals = {
            patient_state: sum(
                patient["situation"] == patient_state
                for item in items
                for patient in item["patients"]
            )
            for patient_state in patient_labels
        }
        summary_sections.append(
            f"""<section class="panel monitoring-summary">
            <h2>{label} · {escape(selected_competence)}</h2>
            <div class="metrics">
                {_metric("Unidades no escopo", len(items), "Contagem por unidade e agravo")}
                {_metric("Pacientes acompanhados", expected, "Linhas no histórico mensal")}
                {_metric("Enviados ou validados", updated, f"{percentage}% dos registros")}
                {_metric("Sem envio", sum(int(item["patients_pending"]) for item in items), "Inclui rascunhos e devolvidos")}
                {_metric("Unidades concluídas", complete_units, "Todos os pacientes enviados")}
                {_metric("Unidades parciais", partial_units, "Há pacientes enviados e pendentes")}
                {_metric("Unidades sem envio após prazo", overdue_count, "Nenhum envio nem rascunho iniciado")}
                {_metric("Unidades silenciosas confirmadas", silent_confirmed, "Sem pacientes e ausência confirmada")}
                {_metric("Reconciliações", reconciliation_count, "Ausências do histórico ou divergências informadas")}
            </div><div class="patient-summary" aria-label="Situação individual dos pacientes">
                <h3>Situação por paciente</h3>
                <div class="summary-links">
                {''.join(summary_link(f'{patient_labels[key]} ({patient_totals[key]})', key, 'patient_state') for key in patient_labels)}
                </div></div>
            <div class="summary-links unit-summary-links" aria-label="Filtrar por situação da unidade">
                {summary_link(f'Unidades concluídas ({complete_units})', 'complete', 'state')}
                {summary_link(f'Unidades parciais ({partial_units})', 'partial', 'state')}
                {summary_link(f'Unidades sem envio ({overdue_count})', 'no_update', 'state')}
                {summary_link(f'Unidades silenciosas confirmadas ({silent_confirmed})', 'silent_confirmed', 'state')}
                {summary_link(f'Aguardando ({sum(item["situation"] == "awaiting" for item in items)})', 'awaiting', 'state')}
                </div></section>"""
        )
    unit_rows: list[str] = []
    for row in rows:
        situation = str(row["situation"])
        label = status_labels.get(situation, situation)
        css_class = status_classes.get(situation, "monitor-status")
        unavailable_reason = ""
        if situation == "data_unavailable":
            unavailable_reason = (
                "Nenhuma ficha mensal foi importada para esta competência; não há registro para salvar ou enviar. A análise de PDF atual gera somente um resumo agregado."
                if not row["imported"]
                else (
                    "A unidade não está incluída na cobertura confirmada da importação."
                    if not row.get("coverage_confirmed")
                    else "Há conflito de reimportação que precisa ser revisado."
                )
            )
        patient_rows = []
        communications_by_patient = row.get("patient_communications", {})
        for patient in row.get("patients", ()):
            if not isinstance(patient, dict):
                continue
            if selected_patient_state and patient["situation"] != selected_patient_state:
                continue
            patient_ref = str(patient.get("patient_ref", ""))
            patient_state = str(patient.get("state", ""))
            updated_at = str(patient.get("updated_at") or "Sem alteração registrada")
            patient_situation = str(patient.get("situation", "awaiting"))
            current_values = patient.get("current_values", {})
            communication_items = ()
            if isinstance(communications_by_patient, dict):
                communication_items = communications_by_patient.get(patient_ref, ())
            communications_html = []
            for item in communication_items:
                if not isinstance(item, MonthlyFollowup):
                    continue
                field_label = next(
                    (field.label for field in BULLETIN_FIELDS[item.agravo]
                     if field.key == item.field_key),
                    "Observações gerais",
                )
                automatic = (
                    f'<p><strong>Sugestão automática:</strong> '
                    f'{escape(item.automatic_text)}</p>'
                    if item.automatic_text else ""
                )
                response_form = ""
                if (
                    role == "unit"
                    and bool(patient.get("can_respond"))
                    and item.competence == str(row["competence"])
                    and item.state in {
                    "awaiting_unit", "needs_more_info", "responded",
                    }
                ):
                    response_form = f"""<form class="patient-response" method="post"
                        action="/comunicacao/{item.id}/responder">
                        <input type="hidden" name="csrf_token" value="{escape(csrf_token)}">
                        <label class="filter-field">Resposta / justificativa
                        <textarea name="text" maxlength="4000" rows="2"
                            placeholder="Registre a resposta para esta orientação">{escape(item.draft_text or item.response_text)}</textarea></label>
                        <div class="actions">
                        <button name="submit" value="draft">Salvar rascunho</button>
                        <button name="submit" value="submitted">Enviar resposta</button></div></form>"""
                communications_html.append(
                    f"""<li><strong>{escape(field_label)}</strong> · {escape(item.competence)}
                    <span class="monitor-status">{escape(item.state.replace("_", " ").title())}</span>
                    {automatic}
                    <p><strong>Observação da Vigilância:</strong><br>
                    {escape(item.vigilance_text or "Sugestão aguardando revisão da Vigilância.")}</p>
                    <p><strong>Resposta / justificativa da unidade:</strong><br>
                    {escape(item.response_text or "Ainda não enviada.")}</p>
                    {response_form}
                    <a href="/comunicacao/{item.id}">Abrir histórico completo</a></li>"""
                )
            comparison = patient.get("comparison", {})
            previous_values = patient.get("previous_values", {})
            comparison_rows = []
            if isinstance(current_values, dict) and isinstance(previous_values, dict):
                for field in BULLETIN_FIELDS[str(row["agravo"])]:
                    difference = (
                        comparison.get(field.key, {})
                        if isinstance(comparison, dict)
                        else {}
                    )
                    comparison_status = (
                        difference.get("status")
                        if isinstance(difference, dict)
                        else "new"
                    )
                    status_label = {
                        "changed": "Alterado",
                        "unchanged": "Sem alteração",
                        "new": "Sem competência anterior",
                        "not_updated": "Não incluído no registro atual",
                    }.get(str(comparison_status), "Não disponível")
                    comparison_rows.append(
                        f"""<tr><th scope="row">{escape(field.label)}</th>
                        <td>{escape(_format_bulletin_value(previous_values.get(field.key)))}</td>
                        <td>{escape(_format_bulletin_value(current_values.get(field.key)))}</td>
                        <td>{escape(status_label)}</td></tr>"""
                    )
            comparison_html = (
                "<div class='table-wrap'><table class='comparison-table'>"
                "<thead><tr><th>Campo oficial</th><th>Competência anterior</th>"
                "<th>Competência atual</th><th>Situação</th></tr></thead><tbody>"
                + "".join(comparison_rows)
                + "</tbody></table></div>"
                if comparison_rows
                else "<p>Valores oficiais não disponíveis para esta ficha.</p>"
            )
            revision_rows = "".join(
                f'<li>Versão {escape(str(revision.get("version", "")))} · '
                f'{escape(str(revision.get("action", "")).replace("_", " "))} · '
                f'{escape(str(revision.get("actor", "")))} · '
                f'{escape(str(revision.get("occurred_at", "")))}</li>'
                for revision in patient.get("revisions", ())
                if isinstance(revision, dict)
            )
            note_rows = "".join(
                f'<li>{escape(str(note.get("occurred_at", "")))} · '
                f'{escape(str(note.get("actor", "")))}: {escape(str(note.get("note", "")))}</li>'
                for note in patient.get("vigilance_notes", ())
                if isinstance(note, dict)
            )
            patient_description = {
                "complete": "A atualização mensal foi enviada ou validada.",
                "partial": "Há um rascunho iniciado ou uma devolução; conclua e envie a ficha.",
                "no_update": "O prazo venceu sem envio e sem rascunho iniciado.",
                "awaiting": "O prazo ainda não venceu e não há atualização iniciada.",
            }.get(patient_situation, "Situação não disponível.")
            patient_form = ""
            if bool(patient.get("can_edit")) and isinstance(current_values, dict):
                form_id = f"monthly-{row['agravo']}-{row['competence']}-{patient_ref}"
                form_action = (
                    f"/monitoramento-mensal/{row['agravo']}/"
                    f"{row['competence']}/{quote(patient_ref, safe='')}/atualizar"
                )
                editable_fields = "".join(
                    _bulletin_field_input(
                        form_id,
                        field,
                        _field_input_value(current_values.get(field.key)),
                        True,
                    )
                    for field in BULLETIN_FIELDS[str(row["agravo"])]
                    if field.monthly_editable
                )
                editing_guidance = (
                    "<p>A Vigilância devolveu esta ficha. Corrija os campos indicados e envie novamente.</p>"
                    if patient_state == "returned"
                    else ""
                )
                patient_form = f"""<section class="patient-edit">
                <h4>Atualizar campos deste boletim</h4>
                {editing_guidance}
                <p>Salve como rascunho para continuar depois ou envie para a Vigilância.
                Após o envio, a ficha fica bloqueada até ser devolvida para correção.</p>
                <form id="{escape(form_id)}" method="post" action="{escape(form_action)}">
                <input type="hidden" name="csrf_token" value="{escape(csrf_token)}">
                <div class="form-grid">{editable_fields}</div>
                <div class="actions">
                <button name="action" value="draft">Salvar rascunho</button>
                <button name="action" value="submit"
                    onclick="return confirm('Enviar esta atualização para análise da Vigilância?');">
                    Enviar atualização</button></div></form></section>"""
            elif role == "unit" and patient_state in {"submitted", "validated"}:
                patient_form = """<p class="section-note">
                Esta ficha já foi enviada e está bloqueada. Se encontrar um erro,
                solicite à Vigilância que a devolva para correção; depois, edite e reenvie.</p>"""
            patient_rows.append(
                f"""<li id="patient-{escape(patient_ref)}" class="patient-monitor-item"><strong>{escape(NOTIFICATION_NUMBER_LABEL)}:
                {escape(patient_ref)}</strong>
                <span class="{patient_classes.get(patient_situation, 'monitor-status')}">
                    {escape(patient_labels.get(patient_situation, patient_state))}</span>
                <span>{escape(updated_at)}</span>
                <details><summary>Detalhes do acompanhamento</summary>
                <p>{escape(patient_description)} Estado da ficha: {escape(patient_state)}.
                Responsável: {escape(str(patient.get("updated_by") or "Nenhum"))}.</p>
                <h4>Campos oficiais e comparação mensal</h4>{comparison_html}
                {patient_form}
                <h4>Observações, respostas e justificativas</h4>
                <ul>{''.join(communications_html) or '<li>Nenhuma observação vinculada a este paciente nesta competência.</li>'}</ul>
                {f'<h4>Observações da Vigilância</h4><ul>{note_rows}</ul>' if note_rows else ''}
                {f'<h4>Histórico de alterações</h4><ol>{revision_rows}</ol>' if revision_rows else ''}
                </details>
                </li>"""
            )
        missing_rows = "".join(
            f'<li>{escape(NOTIFICATION_NUMBER_LABEL)}: '
            f'{escape(str(patient.get("patient_ref", "")))}</li>'
            for patient in row.get("previous_missing_patients", ())
            if isinstance(patient, dict)
        )
        history_rows = "".join(
            f'<li>{escape(str(event.get("occurred_at", "")))} · '
            f'{escape(str(event.get("actor", "")))} · '
            f'{escape(str(event.get("action", "")).replace("_", " "))}'
            f'{" — " + escape(str(event.get("note", ""))) if event.get("note") else ""}</li>'
            for event in row.get("confirmation_history", ())
            if isinstance(event, dict)
        )
        details = ""
        if bool(row["data_available"]):
            details = f"""<details class="monitor-details"><summary>Registros, pendências e histórico</summary>
            <p>{int(row['patients_updated'])} de {int(row['patients_expected'])} registros enviados ou validados;
            {int(row['patients_pending'])} aguardando envio.</p>
            <ul>{''.join(patient_rows) or '<li>Nenhum paciente listado no boletim desta unidade.</li>'}</ul>
            {f'<h3>Pacientes do mês anterior não localizados</h3><ul>{missing_rows}</ul>' if missing_rows else ''}
            {f'<h3>Histórico da confirmação</h3><ol>{history_rows}</ol>' if history_rows else ''}
            <p>Prazo efetivo: {escape(str(row.get('effective_due_on') or 'Não configurado'))}.
            Importação: {'registrada' if row['imported'] else 'não encontrada'}.
            Cobertura da unidade: {'confirmada' if row.get('coverage_confirmed') else 'não confirmada'}.</p>
            </details>"""
        action_forms = ""
        if role == "unit" and situation in {
            "silent_pending", "silent_confirmed", "reconciliation_required",
        }:
            unit_buttons = ""
            if int(row["previous_missing"]) == 0:
                unit_buttons += '<button name="action" value="confirm_absence">Confirmar ausência de pacientes</button>'
            unit_buttons += """<button name="action" value="report_missing_patients">Informar pacientes ausentes</button>
                <button name="action" value="request_review">Solicitar conferência da Vigilância</button>"""
            action_forms = f"""<form class="monitor-action" method="post" action="/monitoramento-mensal/confirmar">
            <input type="hidden" name="csrf_token" value="{escape(csrf_token)}">
            <input type="hidden" name="agravo" value="{escape(str(row['agravo']))}">
            <input type="hidden" name="competence" value="{escape(str(row['competence']))}">
            <label class="filter-field">Nota para a Vigilância (obrigatória para divergências)
            <textarea name="note" maxlength="2000" rows="2"></textarea></label>
            <div class="actions">{unit_buttons}</div></form>"""
        elif role == "surveillance" and situation in {
            "silent_pending", "silent_confirmed", "reconciliation_required",
        }:
            surveillance_buttons = ""
            if situation == "reconciliation_required":
                surveillance_buttons = '<button name="action" value="resolve_reconciliation">Registrar conferência e concluir</button>'
            else:
                surveillance_buttons = """<button name="action" value="request_confirmation">Solicitar confirmação à unidade</button>
                    <button name="action" value="confirm_absence">Confirmar ausência após análise</button>"""
            action_forms = f"""<form class="monitor-action" method="post" action="/vigilancia/monitoramento-mensal/acao">
            <input type="hidden" name="csrf_token" value="{escape(csrf_token)}">
            <input type="hidden" name="agravo" value="{escape(str(row['agravo']))}">
            <input type="hidden" name="competence" value="{escape(str(row['competence']))}">
            <input type="hidden" name="unit_ref" value="{escape(str(row['unit_ref']))}">
            <label class="filter-field">Registro da conferência
            <textarea name="note" maxlength="2000" rows="2"></textarea></label>
            <div class="actions">{surveillance_buttons}</div></form>"""
        unit_rows.append(
            f"""<tr><td>{escape(agravo_labels.get(str(row['agravo']), str(row['agravo'])))}</td>
            <td>{escape(str(row['unit_ref']))}</td>
            <td>{int(row['patients_expected'])}</td><td>{int(row['patients_updated'])} · {int(row['percentage'])}%</td>
            <td>{int(row['patients_pending'])}</td><td>{escape(str(row.get('effective_due_on') or '—'))}</td>
            <td><span class="{css_class}">{escape(label)}</span>
            {f'<p class="section-note">{escape(unavailable_reason)}</p>' if unavailable_reason else ''}
            <p>{details}</p>{action_forms}</td></tr>"""
        )
    deadline_form = ""
    if role == "surveillance":
        deadline_form = f"""<section class="panel monitoring-deadline">
        <h2>Configurar prazo da competência</h2>
        <p>A prorrogação, quando informada, substitui o prazo final inicial.</p>
        <form class="filter-form" method="post" action="/monitoramento-mensal/prazo">
        <input type="hidden" name="csrf_token" value="{escape(csrf_token)}">
        <label class="filter-field">Agravo<select name="agravo" required>{agravo_options}</select></label>
        <label class="filter-field">Competência<input name="competence" value="{escape(selected_competence)}"
            pattern="[0-9]{{4}}-(0[1-9]|1[0-2])" required></label>
        <label class="filter-field">Abertura<input type="date" name="opened_on"
            value="{escape((deadline or {}).get('opened_on') or '')}" required></label>
        <label class="filter-field">Prazo inicial<input type="date" name="due_on"
            value="{escape((deadline or {}).get('due_on') or '')}" required></label>
        <label class="filter-field">Prorrogação (opcional)<input type="date" name="extension_due_on"
            value="{escape((deadline or {}).get('extension_due_on') or '')}"></label>
        <button type="submit">Salvar prazo</button></form></section>"""
    saved_notice = {
        "draft": "Rascunho salvo. A atualização ainda não foi enviada à Vigilância.",
        "submitted": "Atualização enviada à Vigilância para análise.",
    }.get(saved_state, "")
    unit_guidance = (
        """<p class="notice"><strong>Unidade:</strong> o envio não é automático.
        Quando houver uma ficha mensal listada, abra “Registros, pendências e histórico”,
        depois “Detalhes do acompanhamento”; ali você pode salvar rascunho ou enviar à Vigilância.
        Após o envio, a ficha só pode ser corrigida se a Vigilância devolvê-la.
        Se não houver ficha listada, ainda não existe registro individual para atualizar.</p>"""
        if role == "unit"
        else ""
    )
    silent_checked = "checked" if silent_only else ""
    pending_checked = "checked" if pending_only else ""
    html = f"""<!DOCTYPE html><html lang="pt-BR"><head><meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Monitoramento mensal por unidade | Monitoramento Ativo</title>{MODULE_CSS}
    <style>
    .monitor-status {{ display:inline-block; padding:5px 9px; border-radius:20px; font-size:12px; font-weight:700; }}
    .monitor-status.red {{ color:#8f2525; background:#fdeaea; }}
    .monitor-status.yellow {{ color:#765900; background:#fff4cd; }}
    .monitor-status.green {{ color:#176449; background:#e4f5ec; }}
    .monitor-status.blue {{ color:#205c8a; background:#e5f2ff; }}
    .monitor-status.unavailable {{ color:#475569; background:#eef2f7; }}
    .monitor-status.awaiting {{ color:#5c6171; background:#f0f1f5; }}
    .monitoring-summary {{ margin-top:18px; }}
    .monitoring-summary .metrics {{ grid-template-columns:repeat(3,minmax(0,1fr)); }}
    .patient-summary {{ margin-top:20px; }}
    .summary-links {{ display:flex; flex-wrap:wrap; gap:9px; margin:10px 0; }}
    .summary-link {{ display:inline-flex; padding:8px 11px; border:1px solid #d8e1eb; border-radius:8px; background:#fff; color:#145b73; font-weight:650; text-decoration:none; }}
    .summary-link:hover {{ background:#eef7f8; }}
    .patient-monitor-item {{ margin:12px 0; padding:12px; border:1px solid #e1e8ef; border-radius:10px; }}
    .patient-monitor-item > span {{ margin-left:8px; }}
    .patient-monitor-item details {{ margin-top:10px; }}
    .patient-monitor-item li {{ margin:8px 0; }}
    .patient-edit {{ margin:16px 0; padding:14px; border:1px solid #d8e1eb; border-radius:10px; background:#f8fafc; }}
    .patient-edit .form-grid {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px; }}
    .patient-edit .form-field {{ display:grid; gap:5px; font-size:13px; font-weight:600; }}
    .patient-edit .edit-control {{ width:100%; min-height:38px; padding:7px; border:1px solid #cbd5e1; border-radius:6px; background:#fff; }}
    .patient-response {{ margin:10px 0; padding:12px; background:#f7fafc; border-radius:8px; }}
    .patient-response textarea {{ min-height:68px; }}
    .unit-summary-links {{ margin-top:14px; }}
    .monitoring-table {{ min-width:900px; }}
    .monitor-details p,.monitor-details ul,.monitor-details ol {{ margin:8px 0; }}
    .monitor-details li {{ margin:6px 0; }}
    .monitor-details li span {{ display:block; color:var(--muted); font-size:12px; }}
    .monitor-action {{ display:grid; gap:8px; max-width:540px; margin-top:10px; }}
    .monitor-action textarea {{ width:100%; min-height:58px; padding:8px; border:1px solid #d5dee8; border-radius:8px; font:inherit; }}
    .actions {{ display:flex; flex-wrap:wrap; gap:7px; }}
    .actions button {{ padding:8px 11px; border:0; border-radius:7px; background:var(--accent); color:#fff; font-weight:650; cursor:pointer; }}
    .monitoring-table td {{ min-width:120px; }}
    @media(max-width:720px) {{ .monitoring-summary .metrics {{ grid-template-columns:repeat(2,minmax(0,1fr)); }} .summary-links {{ align-items:stretch; }} .summary-link {{ flex:1 1 190px; }} .patient-edit .form-grid {{ grid-template-columns:1fr; }} }}
    </style></head>
    <body><header class="topbar"><a class="brand" href="/">Monitoramento Ativo</a>
    <a class="back" href="/vigilancia">Painel da Vigilância</a>
    <form method="post" action="/logout"><input type="hidden" name="csrf_token" value="{escape(csrf_token)}">
    <span>{escape(username)}</span><button type="submit">Sair</button></form></header>
    <div class="app-shell"><aside class="sidebar" aria-label="Navegação principal">
    <a href="/">Início</a><a href="/tuberculose">Tuberculose</a><a href="/hanseniase">Hanseníase</a>
    <a href="/vigilancia">Visão da Vigilância</a><a href="/comunicacao">Comunicações mensais</a>
    <a class="active" href="/monitoramento-mensal">Monitoramento mensal</a></aside>
    <main class="content"><p class="eyebrow">Competências e unidade de saúde</p>
    <h1>Monitoramento mensal por unidade</h1>
    {f'<p class="notice" role="status">{escape(saved_notice)}</p>' if saved_notice else ''}
    <p class="intro">Acompanhe envios, prazos, boletins sem pacientes e reconciliações sem classificar automaticamente situações clínicas.</p>
    <p class="demo-banner"><strong>Importante:</strong> ausência de pacientes não significa abandono, cura, óbito ou transferência.
    Somente boletins com cobertura explicitamente registrada e sem conflitos podem gerar situação de unidade silenciosa.</p>
    {unit_guidance}
    <section class="panel-grid">{''.join(summary_sections)}</section>
    <form class="filter-form" method="get" aria-label="Filtros do monitoramento mensal">
    <label class="filter-field">Agravo<select name="agravo"><option value="">Todos os agravos</option>{agravo_options}</select></label>
    <label class="filter-field">Competência<select name="competence">{competence_options}</select></label>
    <label class="filter-field">Situação<select name="state"><option value="">Todas</option>{state_options}</select></label>
    <label class="filter-field">Unidade<input name="unit" value="{escape(selected_unit)}" maxlength="100"
        {"disabled" if role == "unit" else ""}></label>
    <label class="filter-field"><span>Somente com pendências</span><input type="checkbox" name="pending" value="true" {pending_checked}></label>
    <label class="filter-field"><span>Somente silenciosas/reconciliação</span><input type="checkbox" name="silent" value="true" {silent_checked}></label>
    <button type="submit">Aplicar filtros</button><a class="reset-link" href="/monitoramento-mensal">Limpar</a>
    </form>
    {deadline_form}
    <section class="panel"><h2>Situação das unidades</h2>
    <div class="table-wrap"><table class="monitoring-table"><thead><tr>
    <th>Agravo</th><th>Unidade</th><th>Pacientes no boletim</th><th>Enviados/validados</th>
    <th>Pendentes</th><th>Prazo efetivo</th><th>Situação e ações</th>
    </tr></thead><tbody>{''.join(unit_rows) or '<tr><td colspan="7">Nenhuma unidade encontrada com estes filtros. Unidades sem cobertura confirmada permanecem fora da categoria silenciosa.</td></tr>'}</tbody></table></div></section>
    <p class="footer">Unidade silenciosa significa boletim importado com cobertura confirmada e zero pacientes listados. Divergências ficam pendentes para reconciliação; o sistema não altera nem elimina registros clínicos.</p>
    </main></div></body></html>"""
    return HTMLResponse(content=html, headers={"Cache-Control": "no-store"})


def render_monthly_followup(
    *,
    followup: MonthlyFollowup,
    history: tuple[dict[str, object], ...],
    role: str,
    csrf_token: str,
    username: str,
    field_definition: BulletinField | None,
    previous_value: object,
    current_value: object,
    field_competence: str,
    can_edit_field: bool,
) -> HTMLResponse:
    state_labels = {
        "automatic_suggestion": "Sugestão automática — revisão da Vigilância pendente",
        "awaiting_unit": "Aguardando resposta da unidade",
        "responded": "Resposta enviada — aguardando Vigilância",
        "under_review": "Em análise pela Vigilância",
        "needs_more_info": "Complementação solicitada",
        "resolved": "Concluída",
    }
    history_rows = ""
    for event in history:
        history_rows += f"""<li><strong>{escape(str(event.get('label', '')))}</strong>
            — {escape(str(event.get('actor', '')))} — {escape(str(event.get('occurred_at', '')))}
            <span>{escape(str(event.get('old_state') or ''))} → {escape(str(event.get('new_state') or ''))}</span>
            <p>{escape(str(event.get('text') or ''))}</p></li>"""
    vigilance_form = ""
    if role == "surveillance":
        action_buttons = ""
        if followup.state == "automatic_suggestion":
            action_buttons = '<button name="action" value="send">Enviar à unidade</button>'
        elif followup.state == "responded":
            action_buttons = """<button name="action" value="start_review">Iniciar análise</button>
                <button name="action" value="request_more_info">Solicitar complementação</button>
                <button name="action" value="resolve">Concluir</button>"""
        elif followup.state == "under_review":
            action_buttons = '<button name="action" value="finish_review">Concluir análise</button>'
        elif followup.state == "resolved":
            action_buttons = '<button name="action" value="reopen">Reabrir solicitação</button>'
        if followup.state != "resolved":
            action_buttons += '<button name="action" value="save_note">Salvar observação</button>'
        if action_buttons:
            vigilance_form = f"""<section class="panel" style="margin-top:20px"><h2>Ação da Vigilância</h2>
            <form method="post" action="/comunicacao/{followup.id}/revisar">
            <input type="hidden" name="csrf_token" value="{escape(csrf_token)}">
            <label class="filter-field">Mensagem à unidade / observação
                <textarea name="text" maxlength="2000" rows="4" required>{escape(followup.vigilance_text)}</textarea></label>
            <label class="filter-field">Prioridade<select name="priority">
                <option value="low" {"selected" if followup.priority == "low" else ""}>Baixa</option>
                <option value="normal" {"selected" if followup.priority == "normal" else ""}>Normal</option>
                <option value="high" {"selected" if followup.priority == "high" else ""}>Alta</option>
            </select></label><div class="actions">{action_buttons}</div></form></section>"""
    unit_form = ""
    if role == "unit" and followup.state in {"awaiting_unit", "needs_more_info", "responded"}:
        unit_form = f"""<section class="panel" style="margin-top:20px"><h2>Resposta da unidade</h2>
        <form method="post" action="/comunicacao/{followup.id}/responder">
        <input type="hidden" name="csrf_token" value="{escape(csrf_token)}">
        <label class="filter-field">Resposta ou rascunho
            <textarea name="text" maxlength="4000" rows="5">{escape(followup.draft_text)}</textarea></label>
        <div class="actions"><button name="submit" value="draft">Salvar rascunho</button>
            <button name="submit" value="submitted">Enviar resposta</button></div></form></section>"""
    response_text = (
        f"<p><strong>Última resposta enviada por {escape(followup.response_by or '')} "
        f"em {escape(followup.response_at or '')}:</strong><br>{escape(followup.response_text)}</p>"
        if followup.response_text else "<p>A unidade ainda não enviou resposta.</p>"
    )
    field_label = (
        field_definition.label
        if field_definition is not None
        else "Observações gerais da Vigilância"
    )
    field_context = ""
    if field_definition is not None:
        field_context = f"""
        <section class="panel field-context" style="margin-top:20px">
            <h2>Campo relacionado: {escape(field_label)}</h2>
            <div class="metrics">
                {_metric("Competência anterior", _format_bulletin_value(previous_value), "Somente leitura")}
                {_metric("Competência atual", _format_bulletin_value(current_value), f"Competência {field_competence}")}
            </div>
            {"<form method='post' id='field-update-form' action='/comunicacao/" + str(followup.id) + "/atualizar-campo'><input type='hidden' name='csrf_token' value='" + escape(csrf_token) + "'>" + _bulletin_field_input("field-update-form", field_definition, _field_input_value(current_value), True) + "<button type='submit'>Atualizar este campo</button></form>" if can_edit_field else ("<p class='section-note'>A competência está encerrada ou o campo não está disponível para edição pela unidade.</p>" if role == "unit" else "")}
        </section>"""
    elif role == "unit":
        field_context = """<section class="panel" style="margin-top:20px">
            <h2>Observações gerais da Vigilância</h2>
            <p>Esta comunicação não está vinculada a um único campo do boletim.</p>
        </section>"""
    if role == "surveillance" and followup.field_key:
        field_context += f"""<section class="panel" style="margin-top:20px">
            <h2>Campo do boletim: {escape(field_label)}</h2>
            <div class="metrics">
                {_metric("Competência anterior", _format_bulletin_value(previous_value), "Referência somente leitura")}
                {_metric("Competência atual", _format_bulletin_value(current_value), "Valor informado pela unidade")}
            </div></section>"""
    html = f"""<!DOCTYPE html><html lang="pt-BR"><head><meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Comunicação mensal | Monitoramento Ativo</title>{MODULE_CSS}</head>
    <body><header class="topbar"><a class="brand" href="/">Monitoramento Ativo</a>
    <a class="back" href="/comunicacao">Voltar às comunicações</a>
    <form method="post" action="/logout"><input type="hidden" name="csrf_token" value="{escape(csrf_token)}">
    <span>{escape(username)}</span><button type="submit">Sair</button></form></header>
    <div class="app-shell"><aside class="sidebar"><a href="/">Início</a>
    <a href="/tuberculose">Tuberculose</a><a href="/hanseniase">Hanseníase</a>
    <a href="/vigilancia">Visão da Vigilância</a><a class="active" href="/comunicacao">Comunicações mensais</a>
    </aside><main class="content"><p class="eyebrow">Histórico auditável</p>
    <h1>Comunicação mensal</h1><section class="metrics">
    {_metric("Competência", followup.competence, "Registro mensal")}
    {_metric("Agravo", followup.agravo.title(), "")}
    {_metric("Unidade", followup.unit_ref, "")}
    {_metric("Situação", state_labels.get(followup.state, followup.state), followup.priority.title())}
    </section><section class="panel"><h2>Solicitação original da automação</h2>
    <p>{escape(followup.automatic_text or "Comunicação registrada manualmente pela Vigilância.")}</p>
    <h2>{escape(field_label)}</h2><h3>Observação da Vigilância</h3>
    <p>{escape(followup.vigilance_text)}</p><h3>Resposta / Justificativa da Unidade</h3>{response_text}</section>
    {field_context}
    {vigilance_form}{unit_form}<section class="panel" style="margin-top:20px">
    <h2>Histórico de alterações</h2><ol>{history_rows or '<li>Sem eventos registrados.</li>'}</ol></section>
    <p class="footer">{escape(NOTIFICATION_NUMBER_LABEL)}: {escape(followup.patient_ref)}.
    Dados permanecem vinculados à unidade e competência.</p>
    </main></div></body></html>"""
    return HTMLResponse(content=html, headers={"Cache-Control": "no-store"})


def render_vigilance(
    csrf_token: str = "",
    username: str = "",
    followups: tuple[MonthlyFollowup, ...] = (),
    followup_metrics: dict[str, object] | None = None,
) -> HTMLResponse:
    followup_metrics = followup_metrics or {}
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
    communication_rows = "".join(
        f"""<tr><td>{escape(item.competence)}</td><td>{escape(item.agravo.title())}</td>
            <td>{escape(item.unit_ref)}</td><td>{escape(item.patient_ref)}</td>
            <td>{escape(item.state.replace("_", " ").title())}</td>
            <td>{escape(item.vigilance_text or item.automatic_text)}</td>
            <td><a href="/comunicacao/{item.id}">Revisar</a></td></tr>"""
        for item in followups
    )
    communication_panel = f"""
        <section class="panel" style="margin-top:24px">
            <h2>Comunicação com as unidades</h2>
            <p>As sugestões automáticas e respostas são armazenadas no histórico mensal.
                A falta de resposta não altera a situação clínica nem encerra o acompanhamento.</p>
            <section class="metrics" aria-label="Resumo das comunicações">
                {_metric("Comunicações", followup_metrics.get("total", 0), "Registros armazenados")}
                {_metric("Respostas enviadas", followup_metrics.get("respostas_enviadas", 0), "Histórico auditável")}
                {_metric("Aguardando unidade", followup_metrics.get("por_situacao", {}).get("awaiting_unit", 0), "Solicitações enviadas")}
                {_metric("Aguardando Vigilância", followup_metrics.get("por_situacao", {}).get("responded", 0), "Respostas recebidas")}
            </section>
            <p><a href="/comunicacao">Abrir painel e filtros de comunicação</a></p>
            <div class="table-wrap"><table class="alert-table"><thead><tr>
                <th>Competência</th><th>Agravo</th><th>Unidade</th><th>{escape(NOTIFICATION_NUMBER_LABEL)}</th>
                <th>Situação</th><th>Mensagem</th><th>Ação</th></tr></thead>
                <tbody>{communication_rows or '<tr><td colspan="7">Nenhuma comunicação mensal armazenada.</td></tr>'}</tbody>
            </table></div>
        </section>"""
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
            <a href="/comunicacao">Comunicações mensais</a>
            <a href="/monitoramento-mensal">Monitoramento mensal</a>
        </aside>
        <main class="content">
            <p class="eyebrow">Consolidação demonstrativa</p>
            <h1>Painel geral da Vigilância</h1>
            <p><a href="/vigilancia/importar">Importar fichas de Tuberculose com conferência</a></p>
            <p class="intro">Resumo fictício por agravo, distrito e unidade de saúde.</p>
            <p class="demo-banner"><strong>Ambiente demonstrativo:</strong> todos os registros
                são fictícios. Não use esta visão para decisões clínicas ou de gestão real.</p>
            <p class="notice">A ausência em um boletim posterior exige verificação e não indica
                automaticamente abandono, cura, óbito ou transferência.</p>
            <section class="metrics" aria-label="Indicadores consolidados">{metrics}</section>
            {communication_panel}
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
                    <thead><tr><th>Nível</th><th>Agravo</th><th>{escape(NOTIFICATION_NUMBER_LABEL)}</th>
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
                <p>Esta visão exige autenticação. O painel mensal aplica o escopo da unidade no
                    backend; administradores têm acesso de consulta e somente a Vigilância pode
                    criar, revisar e concluir comunicações.</p>
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
            <td>{unit.contact_records_to_check}</td>
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
    records_to_check = sum(unit.contact_records_to_check for unit in report.units)
    if records_to_check:
        contacts_note += (
            f" Registros com dados de contatos ausentes ou inconsistentes: {records_to_check}."
            " Esses registros não entram nos totais de contatos."
        )
        if report.contact_columns_found:
            contacts_note = "Totais parciais. " + contacts_note
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
