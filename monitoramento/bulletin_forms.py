from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class BulletinOption:
    code: str
    description: str


@dataclass(frozen=True)
class BulletinField:
    key: str
    label: str
    section: str
    kind: str = "text"
    choices: tuple[BulletinOption, ...] = ()
    monthly_editable: bool = True
    automatic: bool = False


def _options(*items: tuple[str, str]) -> tuple[BulletinOption, ...]:
    codes = [code for code, _ in items]
    if len(codes) != len(set(codes)):
        raise ValueError("Um dicionário não pode repetir códigos.")
    return tuple(BulletinOption(code, description) for code, description in items)


TB_BACILLOSCOPY_CHOICES = _options(
    ("1", "Positivo"),
    ("2", "Negativo"),
    ("3", "Não realizado"),
    ("4", "Não se aplica"),
)
YES_NO_UNKNOWN = _options(("1", "Sim"), ("2", "Não"), ("9", "Ignorado"))
HIV_CHOICES = _options(
    ("1", "Positiva"),
    ("2", "Negativa"),
    ("3", "Em andamento"),
    ("4", "Não realizada"),
)
CULTURE_CHOICES = _options(
    ("1", "Positiva"),
    ("2", "Negativa"),
    ("3", "Em andamento"),
    ("4", "Não realizada"),
)
HISTOPATHOLOGY_CHOICES = _options(
    ("1", "BAAR positivo"),
    ("2", "Sugestivo de TB"),
    ("3", "Não sugestivo de TB"),
    ("4", "Em andamento"),
    ("5", "Não realizado"),
)
SENSITIVITY_CHOICES = _options(
    ("1", "Resistente somente à isoniazida"),
    ("2", "Resistente somente à rifampicina"),
    ("3", "Resistente à isoniazida e rifampicina"),
    ("4", "Resistente a outras drogas de primeira linha"),
    ("5", "Sensível"),
    ("6", "Em andamento"),
    ("7", "Não realizado"),
)
TRM_TB_CHOICES = _options(
    ("1", "Detectável sensível à rifampicina"),
    ("2", "Não detectável resistente à rifampicina"),
    ("3", "Não detectável"),
    ("4", "Inconclusivo"),
    ("5", "Não realizado"),
)
TB_CLOSURE_CHOICES = _options(
    ("1", "Cura"),
    ("2", "Abandono"),
    ("3", "Óbito por TB"),
    ("4", "Óbito por outras causas"),
    ("5", "Transferência"),
    ("6", "Mudança de diagnóstico"),
    ("7", "TB-DR"),
    ("8", "Mudança de esquema"),
    ("9", "Falência"),
    ("10", "Abandono primário"),
)
TRANSFER_CHOICES = _options(
    ("1", "Mesmo município"),
    ("2", "Município diferente na mesma UF"),
    ("3", "UF diferente"),
    ("4", "País diferente"),
)
HANSEN_OPERATIONAL_CLASSIFICATION = _options(
    ("1", "PB — Paucibacilar"),
    ("2", "MB — Multibacilar"),
)
HANSEN_DISABILITY_AT_CURE = _options(
    ("0", "Grau zero"),
    ("1", "Grau I"),
    ("2", "Grau II"),
    ("3", "Não avaliado"),
)
HANSEN_TREATMENT_REGIMEN = _options(
    ("1", "PQT/PB/6 doses"),
    ("2", "PQT/MB/12 doses"),
    ("3", "Outros esquemas substitutivos"),
)
HANSEN_REACTION_CHOICES = _options(
    ("1", "Reação tipo 1"),
    ("2", "Reação tipo 2"),
    ("3", "Reação tipo 1 e 2"),
    ("4", "Sem reação"),
)
HANSEN_EXIT_CHOICES = _options(
    ("1", "Cura"),
    ("2", "Transferência para o mesmo município"),
    ("3", "Transferência para outro município"),
    ("4", "Transferência para outro estado"),
    ("5", "Transferência para outro país"),
    ("6", "Óbito"),
    ("7", "Abandono"),
    ("8", "Erro diagnóstico"),
)

_IMMUTABLE_MONTHLY_FIELD = {"monthly_editable": False}

BULLETIN_FIELDS: dict[str, tuple[BulletinField, ...]] = {
    "tuberculose": (
        BulletinField("uf", "UF", "Identificação", **_IMMUTABLE_MONTHLY_FIELD),
        BulletinField("municipio_notificacao", "Município de notificação atual", "Identificação", **_IMMUTABLE_MONTHLY_FIELD),
        BulletinField("unidade", "Unidade de saúde", "Identificação", **_IMMUTABLE_MONTHLY_FIELD),
        BulletinField("numero_notificacao", "Nº da Notificação Atual", "Identificação", **_IMMUTABLE_MONTHLY_FIELD),
        BulletinField("data_notificacao", "Data da notificação atual", "Identificação", "date", monthly_editable=False),
        BulletinField("nome", "Nome", "Identificação", **_IMMUTABLE_MONTHLY_FIELD),
        BulletinField("data_ultimo_comparecimento", "Data do último comparecimento", "Acompanhamento", "date"),
        BulletinField("forma", "Forma", "Acompanhamento"),
        BulletinField("bac_1_mes", "Baciloscopia do 1º mês", "Exames", "select", TB_BACILLOSCOPY_CHOICES),
        BulletinField("bac_2_mes", "Baciloscopia do 2º mês", "Exames", "select", TB_BACILLOSCOPY_CHOICES),
        BulletinField("bac_3_mes", "Baciloscopia do 3º mês", "Exames", "select", TB_BACILLOSCOPY_CHOICES),
        BulletinField("bac_4_mes", "Baciloscopia do 4º mês", "Exames", "select", TB_BACILLOSCOPY_CHOICES),
        BulletinField("bac_5_mes", "Baciloscopia do 5º mês", "Exames", "select", TB_BACILLOSCOPY_CHOICES),
        BulletinField("bac_6_mes", "Baciloscopia do 6º mês", "Exames", "select", TB_BACILLOSCOPY_CHOICES),
        BulletinField("bac_apos_6_mes", "Baciloscopia após o 6º mês", "Exames", "select", TB_BACILLOSCOPY_CHOICES),
        BulletinField("contatos_identificados", "Total de contatos identificados", "Contatos", "number", monthly_editable=False, automatic=True),
        BulletinField("contatos_examinados", "Total de contatos examinados", "Contatos", "number"),
        BulletinField("hiv", "HIV", "Exames", "select", HIV_CHOICES),
        BulletinField("tarv", "TARV", "Tratamento", "select", YES_NO_UNKNOWN),
        BulletinField("cultura", "Cultura", "Exames", "select", CULTURE_CHOICES),
        BulletinField("trm_tb", "TRM-TB", "Exames", "select", TRM_TB_CHOICES),
        BulletinField("histopatologia", "Histopatologia", "Exames", "select", HISTOPATHOLOGY_CHOICES),
        BulletinField("teste_sensibilidade", "Teste de sensibilidade", "Exames", "select", SENSITIVITY_CHOICES),
        BulletinField("tdo_realizado", "TDO realizado?", "Tratamento", "select", YES_NO_UNKNOWN),
        BulletinField("situacao_encerramento", "Situação de encerramento", "Encerramento", "select", TB_CLOSURE_CHOICES),
        BulletinField("tipo_transferencia", "Se transferência", "Encerramento", "select", TRANSFER_CHOICES),
        BulletinField("local_transferencia", "Local de transferência (município/UF)", "Encerramento"),
        BulletinField("data_encerramento", "Data do encerramento", "Encerramento", "date"),
    ),
    "hanseniase": (
        BulletinField("uf", "UF", "Identificação", **_IMMUTABLE_MONTHLY_FIELD),
        BulletinField("municipio_notificacao", "Município de notificação atual", "Identificação", **_IMMUTABLE_MONTHLY_FIELD),
        BulletinField("unidade", "Unidade de saúde", "Identificação", **_IMMUTABLE_MONTHLY_FIELD),
        BulletinField("numero_notificacao", "Nº da Notificação Atual", "Identificação", **_IMMUTABLE_MONTHLY_FIELD),
        BulletinField("data_notificacao", "Data da notificação atual", "Identificação", "date", monthly_editable=False),
        BulletinField("nome", "Nome", "Identificação", **_IMMUTABLE_MONTHLY_FIELD),
        BulletinField("municipio_residencia", "Município de residência", "Residência"),
        BulletinField("distrito_residencia", "Distrito de residência atual", "Residência"),
        BulletinField("bairro_residencia", "Bairro de residência atual", "Residência"),
        BulletinField("data_ultimo_comparecimento", "Data do último comparecimento", "Acompanhamento", "date"),
        BulletinField("data_mudanca", "Data de mudança de esquema", "Acompanhamento", "date"),
        BulletinField("classificacao_operacional", "Classificação operacional atual (CO)", "Tratamento", "select", HANSEN_OPERATIONAL_CLASSIFICATION),
        BulletinField("incapacidade_na_cura", "Avaliação de incapacidade física no momento da cura (AI)", "Avaliação", "select", HANSEN_DISABILITY_AT_CURE),
        BulletinField("esquema_terapeutico", "Esquema terapêutico atual (ET)", "Tratamento", "select", HANSEN_TREATMENT_REGIMEN),
        BulletinField("doses_supervisionadas", "Número de doses supervisionadas (ND)", "Tratamento", "number"),
        BulletinField("episodio_reacional", "Episódio reacional durante o tratamento (ER)", "Avaliação", "select", HANSEN_REACTION_CHOICES),
        BulletinField("contatos_identificados", "Contatos registrados", "Contatos", "number"),
        BulletinField("contatos_examinados", "Contatos examinados", "Contatos", "number"),
        BulletinField("tipo_saida", "Tipo de saída", "Encerramento", "select", HANSEN_EXIT_CHOICES),
        BulletinField("data_alta", "Data da alta", "Encerramento", "date"),
    ),
}

_FIELDS_BY_AGRAVO = {
    agravo: {field.key: field for field in fields}
    for agravo, fields in BULLETIN_FIELDS.items()
}


def _option_for_value(field: BulletinField, value: str) -> BulletinOption | None:
    for option in field.choices:
        if value == option.code or value == f"{option.code} - {option.description}":
            return option
    return None


def validate_form_values(agravo: str, values: dict[str, str]) -> dict[str, str]:
    if agravo not in _FIELDS_BY_AGRAVO:
        raise ValueError("Agravo inválido.")
    fields = _FIELDS_BY_AGRAVO[agravo]
    if values.keys() - fields.keys():
        raise ValueError("O formulário contém campos desconhecidos.")

    validated: dict[str, str] = {}
    for key, raw_value in values.items():
        if not isinstance(raw_value, str):
            raise ValueError("Valor de campo inválido.")
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
        if field.kind == "select" and value:
            option = _option_for_value(field, value)
            if option is None:
                raise ValueError(f"Código inválido para o campo “{field.label}”.")
            value = option.code
        if field.kind == "date" and value:
            try:
                date.fromisoformat(value)
            except ValueError as error:
                raise ValueError(f"Data inválida no campo “{field.label}”.") from error
        validated[key] = value
    return validated


def prepare_original_values(values: dict[str, object]) -> dict[str, object]:
    prepared = dict(values)
    for agravo_fields in _FIELDS_BY_AGRAVO.values():
        for key, field in agravo_fields.items():
            raw_value = prepared.get(key)
            if not field.choices or raw_value in (None, ""):
                continue
            if isinstance(raw_value, dict):
                code = raw_value.get("codigo")
                description = raw_value.get("descricao")
                option = next(
                    (choice for choice in field.choices if choice.code == code),
                    None,
                )
                if option is None or description != option.description:
                    raise ValueError(f"Código inválido para o campo “{field.label}”.")
                continue
            if not isinstance(raw_value, str):
                raise ValueError(f"Código inválido para o campo “{field.label}”.")
            option = _option_for_value(field, raw_value.strip())
            if option is None:
                continue
            prepared[key] = {
                "codigo": option.code,
                "descricao": option.description,
                "valor_original": raw_value,
            }
    return prepared


def prepare_updated_values(
    agravo: str,
    values: dict[str, str],
) -> dict[str, object]:
    fields = _FIELDS_BY_AGRAVO.get(agravo)
    if fields is None:
        raise ValueError("Agravo inválido.")
    prepared: dict[str, object] = {}
    for key, value in values.items():
        field = fields[key]
        if field.choices and value:
            option = _option_for_value(field, value)
            if option is None:
                raise ValueError(f"Código inválido para o campo “{field.label}”.")
            prepared[key] = {
                "codigo": option.code,
                "descricao": option.description,
            }
        else:
            prepared[key] = value
    return prepared


def monthly_editable_field_keys(agravo: str) -> set[str]:
    if agravo not in _FIELDS_BY_AGRAVO:
        raise ValueError("Agravo inválido.")
    return {
        field.key
        for field in BULLETIN_FIELDS[agravo]
        if field.monthly_editable
    }
