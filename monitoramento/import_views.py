from html import escape
from urllib.parse import urlencode

from fastapi.responses import HTMLResponse

from monitoramento.bulletin_forms import BULLETIN_FIELDS
from monitoramento.import_previews import PendingImport
from monitoramento.views import MODULE_CSS


def _page(title: str, body: str, csrf: str, status_code: int = 200) -> HTMLResponse:
    return HTMLResponse(
        f'''<!DOCTYPE html><html lang="pt-BR"><head><meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>{escape(title)} | Monitoramento Ativo</title>{MODULE_CSS}
        <style>:root {{ --accent:var(--blue); }}</style></head><body>
        <header class="topbar"><a class="brand" href="/vigilancia">Monitoramento Ativo</a>
        <form method="post" action="/logout"><input type="hidden" name="csrf_token"
        value="{escape(csrf)}"><button type="submit">Sair</button></form></header>
        <main><p><a href="/vigilancia">Voltar à Vigilância</a></p>
        <h1>{escape(title)}</h1>{body}</main></body></html>''',
        status_code=status_code,
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
    )


def render_import_form(units: tuple[str, ...], csrf: str, *, error: str = "",
                       status_code: int = 200) -> HTMLResponse:
    options = "".join(f'<option value="{escape(unit)}">{escape(unit)}</option>' for unit in units)
    message = f'<p class="auth-error" role="alert">{escape(error)}</p>' if error else ""
    form = f'''
        <form class="filter-form" method="post" action="/api/boletins/previsualizar"
              enctype="multipart/form-data">
        <input type="hidden" name="csrf_token" value="{escape(csrf)}">
        <label class="filter-field">Competência<input type="month" name="competence" required></label>
        <label class="filter-field">Unidade cadastrada<select name="unit" required>
            <option value="">Selecione a unidade</option>{options}</select></label>
        <label class="filter-field">Boletim de Tuberculose em PDF
            <input type="file" name="boletim" accept=".pdf,application/pdf" required></label>
        <button type="submit">Ler e conferir registros</button></form>''' if units else '''
        <p role="status">Cadastre uma conta de unidade ativa antes de importar um boletim.</p>'''
    return _page("Importar boletim de Tuberculose", f'''
        <p class="intro">Informe a competência e a unidade do documento. Confira a leitura antes de confirmar.</p>
        <p class="demo-banner">Use amostras fictícias nesta versão. O leitor aceita somente o layout
        reconhecido de 16 colunas. Forma, baciloscopias e transferência de células mescladas não são importadas.
        Hanseníase continua disponível no resumo agregado.</p>
        {message}{form}<p>A primeira leitura não grava fichas. A prévia vale por 10 minutos.
        A confirmação registra os campos apresentados no histórico mensal.</p>''', csrf, status_code)


def render_import_preview(item: PendingImport, token: str, csrf: str) -> HTMLResponse:
    fields = {field.key: field for field in BULLETIN_FIELDS["tuberculose"]}
    records_html = ""
    for index, record in enumerate(item.bulletin.records, start=1):
        values = record["values"]
        rows = ""
        for key, value in values.items():
            field = fields[key]
            option = next((choice for choice in field.choices if choice.code == value), None)
            shown = f"{option.code} - {option.description}" if option else (value or "Em branco")
            rows += f'<tr><th>{escape(field.label)}</th><td>{escape(str(shown))}</td></tr>'
        records_html += f'''<details class="panel" open>
            <summary>Registro {index} — Nº da Notificação Atual: {escape(str(record['patient_ref']))}</summary>
            <div class="table-wrap"><table class="alert-table"><tbody>{rows}</tbody></table></div></details>'''
    warnings = "".join(f"<li>{escape(warning)}</li>" for warning in item.bulletin.warnings)
    return _page("Conferir importação", f'''
        <p><strong>Competência:</strong> {escape(item.competence)} —
        <strong>Unidade:</strong> {escape(item.unit)}</p>
        <p><strong>{len(item.bulletin.records)} registros reconhecidos.</strong> Nenhuma ficha foi gravada ainda.</p>
        <ul class="demo-banner">{warnings}</ul>{records_html}
        <form class="filter-form" method="post" action="/api/boletins/confirmar">
            <input type="hidden" name="csrf_token" value="{escape(csrf)}">
            <input type="hidden" name="preview_token" value="{escape(token)}">
            <button type="submit">Conferi os registros — confirmar importação</button>
            <button type="submit" formaction="/api/boletins/cancelar">Descartar prévia sem importar</button>
        </form><p>Fichas existentes com dados originais diferentes geram conflitos para conferência;
        suas alterações não são sobrescritas. Esta leitura não substitui a validação documental.</p>''', csrf)


def render_import_result(result: dict, item: PendingImport, csrf: str) -> HTMLResponse:
    query = urlencode({"agravo": "tuberculose", "competence": item.competence})
    return _page("Resultado da importação", f'''
        <p role="status">{result['inserted']} registros importados;
        {result['conflicts']} conflitos para conferência.</p>
        {"<p>Este arquivo já havia sido importado. Não foram criadas cópias.</p>" if result['duplicate'] else ''}
        <p>Competência: {escape(item.competence)} — Unidade: {escape(item.unit)}</p>
        <p><a href="/monitoramento-mensal?{escape(query)}">Abrir fichas no monitoramento mensal</a></p>
        <p><a href="/vigilancia/importar">Importar outro boletim</a></p>''', csrf)
