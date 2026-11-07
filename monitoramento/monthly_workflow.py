from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import TypeAlias

FieldValue: TypeAlias = str | int | float | bool | date | None


class FieldType(StrEnum):
    TEXT = "text"
    INTEGER = "integer"
    DECIMAL = "decimal"
    DATE = "date"
    BOOLEAN = "boolean"
    CHOICE = "choice"


class ChangeKind(StrEnum):
    UNCHANGED = "unchanged"
    UPDATED = "updated"
    NEW = "new"
    REMOVED = "removed"
    PENDING = "pending"
    INCONSISTENT = "inconsistent"


class BulletinState(StrEnum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    RETURNED = "returned"
    VALIDATED = "validated"
    CLOSED = "closed"


@dataclass(frozen=True)
class Competence:
    year: int
    month: int

    def __post_init__(self) -> None:
        if self.year < 1:
            raise ValueError("O ano da competência deve ser maior que zero.")
        if not 1 <= self.month <= 12:
            raise ValueError("O mês da competência deve estar entre 1 e 12.")

    @classmethod
    def parse(cls, value: str) -> "Competence":
        try:
            year, month = value.split("-", maxsplit=1)
            return cls(year=int(year), month=int(month))
        except (AttributeError, TypeError, ValueError) as error:
            raise ValueError("Use a competência no formato AAAA-MM.") from error

    def __str__(self) -> str:
        return f"{self.year:04d}-{self.month:02d}"

    def previous(self) -> "Competence":
        if self.month == 1:
            return Competence(self.year - 1, 12)
        return Competence(self.year, self.month - 1)


@dataclass(frozen=True)
class FieldDefinition:
    code: str
    label: str
    value_type: FieldType
    required: bool
    source_version: str
    section: str = ""
    allowed_values: tuple[FieldValue, ...] = ()


@dataclass(frozen=True)
class BulletinSchema:
    agravo: str
    version: str
    source_document: str
    fields: tuple[FieldDefinition, ...]

    def __post_init__(self) -> None:
        if not self.agravo.strip():
            raise ValueError("O agravo precisa ser identificado.")
        if not self.version.strip():
            raise ValueError("A versão do dicionário é obrigatória.")
        if not self.source_document.strip():
            raise ValueError("Informe o documento oficial de origem do dicionário.")
        codes = [field.code for field in self.fields]
        if any(not code.strip() for code in codes):
            raise ValueError("Os códigos de campo não podem ficar vazios.")
        if len(codes) != len(set(codes)):
            raise ValueError("O dicionário não pode repetir códigos de campo.")
        if any(field.source_version != self.version for field in self.fields):
            raise ValueError("Todos os campos devem corresponder à versão do dicionário.")


@dataclass(frozen=True)
class FieldChange:
    code: str
    label: str
    kind: ChangeKind
    previous_value: FieldValue
    current_value: FieldValue
    message: str


@dataclass(frozen=True)
class MonthlyBulletinVersion:
    record_ref: str
    agravo: str
    unit_ref: str
    competence: Competence
    schema_version: str
    version: int
    state: BulletinState
    values: tuple[tuple[str, FieldValue], ...]
    previous_version: int | None = None

    def __post_init__(self) -> None:
        if not self.record_ref.strip() or not self.unit_ref.strip():
            raise ValueError("A referência do registro e da unidade é obrigatória.")
        if self.version < 1:
            raise ValueError("A versão do boletim deve ser positiva.")
        if self.previous_version is not None and self.previous_version >= self.version:
            raise ValueError("A versão anterior deve ser menor que a versão atual.")
        field_codes = [code for code, _ in self.values]
        if len(field_codes) != len(set(field_codes)):
            raise ValueError("Os valores do boletim não podem repetir campos.")


_ALLOWED_TRANSITIONS: dict[BulletinState, frozenset[BulletinState]] = {
    BulletinState.DRAFT: frozenset({BulletinState.SUBMITTED}),
    BulletinState.SUBMITTED: frozenset({BulletinState.RETURNED, BulletinState.VALIDATED}),
    BulletinState.RETURNED: frozenset({BulletinState.SUBMITTED}),
    BulletinState.VALIDATED: frozenset({BulletinState.CLOSED}),
    BulletinState.CLOSED: frozenset(),
}


def transition_bulletin(
    state: BulletinState,
    target: BulletinState,
    *,
    has_blocking_errors: bool = False,
) -> BulletinState:
    if target not in _ALLOWED_TRANSITIONS[state]:
        raise ValueError(f"Transição não permitida: {state.value} -> {target.value}.")
    if target == BulletinState.SUBMITTED and has_blocking_errors:
        raise ValueError("Resolva os erros impeditivos antes de enviar o boletim.")
    if target == BulletinState.CLOSED and has_blocking_errors:
        raise ValueError("Resolva os erros impeditivos antes de fechar a competência.")
    return target


def _is_empty(value: FieldValue) -> bool:
    return value is None or value == ""


def _is_valid_value(value: FieldValue, definition: FieldDefinition) -> bool:
    if definition.value_type == FieldType.TEXT:
        return isinstance(value, str)
    if definition.value_type == FieldType.INTEGER:
        return isinstance(value, int) and not isinstance(value, bool)
    if definition.value_type == FieldType.DECIMAL:
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if definition.value_type == FieldType.DATE:
        return isinstance(value, date)
    if definition.value_type == FieldType.BOOLEAN:
        return isinstance(value, bool)
    if definition.value_type == FieldType.CHOICE:
        return value in definition.allowed_values
    return False


def compare_monthly_fields(
    previous: dict[str, FieldValue],
    current: dict[str, FieldValue],
    schema: BulletinSchema,
) -> tuple[FieldChange, ...]:
    definitions = {field.code: field for field in schema.fields}
    changes: list[FieldChange] = []

    for code in sorted((previous.keys() | current.keys()) - definitions.keys()):
        changes.append(
            FieldChange(
                code=code,
                label=code,
                kind=ChangeKind.INCONSISTENT,
                previous_value=previous.get(code),
                current_value=current.get(code),
                message="Campo ausente no dicionário oficial carregado; revisar o esquema.",
            )
        )

    for definition in schema.fields:
        old_value = previous.get(definition.code)
        new_value = current.get(definition.code)
        has_current_field = definition.code in current

        if not has_current_field:
            kind = ChangeKind.PENDING if definition.required else ChangeKind.UNCHANGED
            message = (
                "Campo obrigatório ainda não informado nesta competência."
                if definition.required
                else "Campo não reenviado; o valor anterior permanece sem alteração."
            )
        elif _is_empty(new_value):
            if definition.required:
                kind = ChangeKind.PENDING
                message = "Campo obrigatório pendente de preenchimento."
            elif not _is_empty(old_value):
                kind = ChangeKind.REMOVED
                message = "Valor anterior removido explicitamente."
            else:
                kind = ChangeKind.UNCHANGED
                message = "Campo permanece sem valor."
        elif not _is_valid_value(new_value, definition):
            kind = ChangeKind.INCONSISTENT
            message = "Valor incompatível com o tipo ou as opções do dicionário carregado."
        elif _is_empty(old_value):
            kind = ChangeKind.NEW
            message = "Informação nova nesta competência."
        elif old_value == new_value:
            kind = ChangeKind.UNCHANGED
            message = "Sem alteração."
        else:
            kind = ChangeKind.UPDATED
            message = "Valor atualizado em relação à competência anterior."

        changes.append(
            FieldChange(
                code=definition.code,
                label=definition.label,
                kind=kind,
                previous_value=old_value,
                current_value=new_value,
                message=message,
            )
        )
    return tuple(changes)
