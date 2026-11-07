from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class BulletinField:
    key: str
    label: str
    section: str
    kind: str = "text"
    choices: tuple[str, ...] = ()


TB_BACILLOSCOPY_CHOICES = (
    "1 - Positivo",
    "2 - Negativo",
    "3 - Não realizado",
    "4 - Não se aplica",
)

BULLETIN_FIELDS: dict[str, tuple[BulletinField, ...]] = {
    "tuberculose": (
        BulletinField("uf", "UF", "Identificação"),
        BulletinField("municipio_notificacao", "Município de notificação atual", "Identificação"),
        BulletinField("unidade", "Unidade de saúde", "Identificação"),
        BulletinField("numero_notificacao", "Nº da notificação", "Identificação"),
        BulletinField("data_notificacao", "Data da notificação", "Identificação", "date"),
        BulletinField("nome", "Nome", "Identificação"),
        BulletinField("data_ultimo_comparecimento", "Data do último comparecimento", "Acompanhamento", "date"),
        BulletinField("forma", "Forma", "Acompanhamento"),
        BulletinField("bac_1_mes", "Baciloscopia do 1º mês", "Exames", "select", TB_BACILLOSCOPY_CHOICES),
        BulletinField("bac_2_mes", "Baciloscopia do 2º mês", "Exames", "select", TB_BACILLOSCOPY_CHOICES),
        BulletinField("bac_3_mes", "Baciloscopia do 3º mês", "Exames", "select", TB_BACILLOSCOPY_CHOICES),
        BulletinField("bac_4_mes", "Baciloscopia do 4º mês", "Exames", "select", TB_BACILLOSCOPY_CHOICES),
        BulletinField("bac_5_mes", "Baciloscopia do 5º mês", "Exames", "select", TB_BACILLOSCOPY_CHOICES),
        BulletinField("bac_6_mes", "Baciloscopia do 6º mês", "Exames", "select", TB_BACILLOSCOPY_CHOICES),
        BulletinField("bac_apos_6_mes", "Baciloscopia após o 6º mês", "Exames", "select", TB_BACILLOSCOPY_CHOICES),
        BulletinField("contatos_identificados", "Total de contatos identificados", "Contatos", "number"),
        BulletinField("contatos_examinados", "Total de contatos examinados", "Contatos", "number"),
        BulletinField("hiv", "HIV", "Exames", "select", ("1 - Positiva", "2 - Negativa", "3 - Em andamento", "4 - Não realizada")),
        BulletinField("tarv", "TARV", "Tratamento", "select", ("1 - Sim", "2 - Não", "9 - Ignorado")),
        BulletinField("cultura", "Cultura", "Exames", "select", ("1 - Positiva", "2 - Negativa", "3 - Em andamento", "4 - Não realizada")),
        BulletinField("trm_tb", "TRM-TB", "Exames", "select", ("1 - Detectável sensível à rifampicina", "2 - Detectável resistente à rifampicina", "3 - Não detectável", "4 - Inconclusivo", "5 - Não realizado")),
        BulletinField("histopatologia", "Histopatologia", "Exames", "select", ("1 - BAAR positivo", "2 - Sugestivo de TB", "3 - Não sugestivo de TB", "4 - Em andamento", "5 - Não realizado")),
        BulletinField("teste_sensibilidade", "Teste de sensibilidade", "Exames", "select", ("1 - Resistente somente à isoniazida", "2 - Resistente somente à rifampicina", "3 - Resistente à isoniazida e rifampicina", "4 - Resistente a outras drogas de 1ª linha", "5 - Sensível", "6 - Em andamento", "7 - Não realizado")),
        BulletinField("tdo_realizado", "TDO realizado?", "Tratamento", "select", ("1 - Sim", "2 - Não", "9 - Ignorado")),
        BulletinField("situacao_encerramento", "Situação de encerramento", "Encerramento", "select", ("1 - Cura", "2 - Abandono", "3 - Óbito por TB", "4 - Óbito por outras causas", "5 - Transferência", "6 - Mudança de diagnóstico", "7 - TBDR", "8 - Mudança de esquema", "9 - Falência", "10 - Abandono primário")),
        BulletinField("tipo_transferencia", "Se transferência", "Encerramento", "select", ("1 - Mesmo município", "2 - Município diferente (mesma UF)", "3 - UF diferente", "4 - País diferente")),
        BulletinField("local_transferencia", "Local de transferência (município/UF)", "Encerramento"),
        BulletinField("data_encerramento", "Data do encerramento", "Encerramento", "date"),
    ),
    "hanseniase": (
        BulletinField("uf", "UF", "Identificação"),
        BulletinField("municipio_notificacao", "Município de notificação atual", "Identificação"),
        BulletinField("unidade", "Unidade de saúde", "Identificação"),
        BulletinField("numero_notificacao", "Nº da notificação", "Identificação"),
        BulletinField("data_notificacao", "Data da notificação", "Identificação", "date"),
        BulletinField("nome", "Nome", "Identificação"),
        BulletinField("municipio_residencia", "Município de residência", "Residência"),
        BulletinField("distrito_residencia", "Distrito de residência", "Residência"),
        BulletinField("bairro_residencia", "Bairro de residência", "Residência"),
        BulletinField("data_ultimo_comparecimento", "Data do último comparecimento", "Acompanhamento", "date"),
        BulletinField("data_mudanca", "Data da mudança", "Acompanhamento", "date"),
        BulletinField("classificacao_operacional", "Classificação operacional atual", "Tratamento", "select", ("1 - PB (paucibacilar)", "2 - MB (multibacilar)")),
        BulletinField("incapacidade_na_cura", "Avaliação de incapacidade física no momento da cura", "Avaliação", "select", ("0 - Grau zero", "1 - Grau I", "2 - Grau II", "3 - Não avaliado")),
        BulletinField("esquema_terapeutico", "Esquema terapêutico atual", "Tratamento", "select", ("1 - PQT/PB/6 doses", "2 - PQT/MB/12 doses", "3 - Outros esquemas substitutivos")),
        BulletinField("doses_supervisionadas", "Número de doses supervisionadas", "Tratamento", "number"),
        BulletinField("episodio_reacional", "Episódio reacional durante o tratamento", "Avaliação", "select", ("1 - Reação tipo 1", "2 - Reação tipo 2", "3 - Reação tipo 1 e 2", "4 - Sem reação")),
        BulletinField("contatos_identificados", "Contatos identificados", "Contatos", "number"),
        BulletinField("contatos_examinados", "Contatos examinados", "Contatos", "number"),
        BulletinField("tipo_saida", "Tipo de saída", "Encerramento", "select", ("1 - Cura", "2 - Transferência para o mesmo município", "3 - Transferência para outro município", "4 - Transferência para outro estado", "5 - Transferência para outro país", "6 - Óbito", "7 - Abandono", "8 - Erro diagnóstico")),
        BulletinField("data_alta", "Data da alta", "Encerramento", "date"),
    ),
}


def validate_form_values(agravo: str, values: dict[str, str]) -> dict[str, str]:
    fields = {field.key: field for field in BULLETIN_FIELDS[agravo]}
    if values.keys() - fields.keys():
        raise ValueError("O formulário contém campos desconhecidos.")

    validated: dict[str, str] = {}
    for key, raw_value in values.items():
        field = fields[key]
        value = raw_value.strip()
        if len(value) > 250:
            raise ValueError(f"O campo “{field.label}” excede 250 caracteres.")
        if field.kind == "number" and value:
            try:
                number = int(value)
            except ValueError as error:
                raise ValueError(f"O campo “{field.label}” deve ser um número inteiro.") from error
            if number < 0:
                raise ValueError(f"O campo “{field.label}” não pode ser negativo.")
        if field.kind == "select" and value and value not in field.choices:
            raise ValueError(f"Opção inválida para o campo “{field.label}”.")
        if field.kind == "date" and value:
            try:
                date.fromisoformat(value)
            except ValueError as error:
                raise ValueError(f"Data inválida no campo “{field.label}”.") from error
        validated[key] = value
    return validated
