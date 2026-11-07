import json
from html import escape

from fastapi.responses import HTMLResponse

from monitoramento.data import ModuleDemo, PatientDemo

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
    </div><span class="topbar-label">Monitoramento epidemiológico</span></header>
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
    @media (max-width:760px) {
        .topbar { height:60px; padding:0 18px; }
        main { width:min(100% - 32px,560px); margin:28px auto 48px; }
        .metrics { grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; }
        .metric { min-height:120px; padding:15px; }
        .section-heading { align-items:start; flex-direction:column; }
    }
    @media (max-width:420px) { .metrics { grid-template-columns:1fr; } }
</style>
"""


def _patient_row(module_key: str, patient: PatientDemo) -> str:
    observation_key = f"{module_key}:{patient.identifier}"
    return f"""
        <tr>
            <td class="identifier">{escape(patient.identifier)}</td>
            <td>{escape(patient.unit)}<br><small>{escape(patient.district)}</small></td>
            <td>{patient.treatment_start.strftime("%d/%m/%Y")}</td>
            <td><span class="status">{escape(patient.followup_status)}</span></td>
            <td>{patient.expected_end.strftime("%d/%m/%Y")}</td>
            <td>{patient.contacts_registered} / {patient.contacts_examined}</td>
            <td>{escape(patient.pending_items)}</td>
            <td class="editable" contenteditable="true" role="textbox"
                aria-label="Observação local para {escape(patient.identifier)}"
                data-observation-key="{escape(observation_key)}">{escape(patient.observation)}</td>
        </tr>
    """


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


def render_module(module: ModuleDemo) -> HTMLResponse:
    patients = module.patients
    contacts_registered = sum(patient.contacts_registered for patient in patients)
    contacts_examined = sum(patient.contacts_examined for patient in patients)
    metrics = "".join(
        (
            _metric("Pacientes em acompanhamento", len(patients), "Registros fictícios"),
            _metric(
                "Tratamento próximo do término",
                sum(patient.ending_soon_demo for patient in patients),
                "Marcador demonstrativo, não regra clínica",
            ),
            _metric(
                "Acompanhamento pendente",
                sum(patient.followup_status == "Acompanhamento pendente" for patient in patients),
                "Pendências fictícias da tabela",
            ),
            _metric(
                "Possíveis situações de abandono",
                sum(patient.review_signal_demo for patient in patients),
                "Sinal fictício para revisão, sem classificação clínica",
            ),
            _metric("Contatos registrados", contacts_registered, "Soma dos registros fictícios"),
            _metric(
                "Contatos ainda não examinados",
                contacts_registered - contacts_examined,
                f"{contacts_examined} examinados (demonstrativo)",
            ),
        )
    )
    rows = "".join(_patient_row(module.key, patient) for patient in patients)
    units = ", ".join(escape(unit) for unit in module.units_without_monthly_update)
    title = escape(module.name)
    storage_prefix_json = json.dumps(f"monitoramento-demo:observacao:{module.key}:")
    html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta name="theme-color" content="#f5f8fc">
    <title>{title} | Monitoramento Ativo</title>
    <style>:root {{ --accent: var(--{module.accent}); }}{MODULE_CSS}</style>
</head>
<body>
    <header class="topbar">
        <a class="brand" href="/">Monitoramento Ativo</a>
        <a class="back" href="/">← Página inicial</a>
    </header>
    <main>
        <p class="eyebrow">Módulo demonstrativo</p>
        <h1>{title}</h1>
        <p class="intro">Visão demonstrativa de acompanhamento, contatos e pendências.</p>
        <p class="demo-banner"><strong>Dados fictícios:</strong> todos os indicadores e registros
            desta página são apenas demonstrativos. Não há classificação clínica implementada.</p>
        <p class="notice">A ausência de um registro em boletim posterior não significa,
            por si só, abandono ou cura. Os critérios oficiais ainda não foram configurados.</p>
        <section class="metrics" aria-label="Indicadores demonstrativos">{metrics}</section>
        <section aria-labelledby="tabela-titulo">
            <div class="section-heading">
                <h2 id="tabela-titulo">Acompanhamento demonstrativo</h2>
                <p class="section-note">Role horizontalmente para ver todas as colunas.</p>
            </div>
            <div class="table-wrap">
                <table>
                    <thead><tr>
                        <th>Identificador fictício</th><th>Unidade de saúde / distrito</th>
                        <th>Início do tratamento</th><th>Situação do acompanhamento</th>
                        <th>Término previsto</th><th>Contatos registrados / examinados</th>
                        <th>Pendências</th><th>Observações da Vigilância Epidemiológica</th>
                    </tr></thead>
                    <tbody>{rows}</tbody>
                </table>
            </div>
            <p class="save-state" id="save-state" role="status" aria-live="polite">
                Clique em uma observação para editar. As alterações ficam somente neste navegador.
            </p>
        </section>
        <section class="units" aria-labelledby="unidades-titulo">
            <h2 id="unidades-titulo">Unidades sem atualização mensal</h2>
            <p>{units if units else "Nenhuma unidade fictícia sinalizada neste exemplo."}</p>
        </section>
        <p class="footer">Protótipo local. Sem importação de boletins, autenticação,
            integração Firebase ou processamento de dados reais.</p>
    </main>
    <script>
        (() => {{
            const storagePrefix = {storage_prefix_json};
            const state = document.getElementById("save-state");
            const cells = document.querySelectorAll("[data-observation-key]");
            try {{
                cells.forEach((cell) => {{
                    const saved = localStorage.getItem(storagePrefix + cell.dataset.observationKey);
                    if (saved !== null) cell.textContent = saved;
                    cell.addEventListener("input", () => {{
                        try {{
                            localStorage.setItem(
                                storagePrefix + cell.dataset.observationKey,
                                cell.textContent || ""
                            );
                            state.textContent = "Observação salva localmente neste navegador.";
                        }} catch (error) {{
                            state.textContent = "Não foi possível salvar localmente: " + error.message;
                        }}
                    }});
                }});
            }} catch (error) {{
                state.textContent = "Não foi possível acessar o armazenamento local: " + error.message;
            }}
        }})();
    </script>
</body>
</html>"""
    return HTMLResponse(content=html)
