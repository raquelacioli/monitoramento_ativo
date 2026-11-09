"""Native Firestore persistence for monthly workflows.

New imports are staged in bounded transactions. A single publication marker makes
all their new documents visible together; interrupted imports can be resumed.
"""
import hashlib
import json
import secrets
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Literal

from monitoramento.bulletin_forms import BULLETIN_FIELDS, prepare_original_values
from monitoramento.monthly_workflow import Competence
from monitoramento.firestore_store import get_store, key, snapshot_read

RecordState = Literal["draft", "submitted", "returned", "validated"]

@dataclass(frozen=True)
class MonthlyRecord:
    agravo: str
    patient_ref: str
    unit_ref: str
    competence: str
    original_values: dict[str, object]
    updated_values: dict[str, object]
    state: RecordState
    version: int
    updated_by: str | None
    updated_at: str
    reviewer_note: str

    @property
    def values(self) -> dict[str, object]:
        return {**self.original_values, **self.updated_values}


@dataclass(frozen=True)
class MonthlyFollowup:
    id: int
    agravo: str
    patient_ref: str
    unit_ref: str
    competence: str
    field_key: str
    rule_id: str
    automatic_text: str
    vigilance_text: str
    state: str
    priority: str
    created_by: str
    created_at: str
    updated_by: str
    updated_at: str
    response_text: str
    draft_text: str
    response_by: str | None
    response_at: str | None
    response_version: int


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")


def _json(values: dict[str, object]) -> str:
    try:
        return json.dumps(values, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError) as error:
        raise ValueError("Os valores do registro não são serializáveis.") from error


def compare_monthly_record_fields(
    current: MonthlyRecord,
    previous: MonthlyRecord | None,
) -> dict[str, dict[str, object]]:
    current_values = current.values
    previous_values = previous.values if previous else {}
    changes: dict[str, dict[str, object]] = {}
    for key in sorted(current_values.keys() | previous_values.keys()):
        previous_value = previous_values.get(key)
        current_value = current_values.get(key)
        if key not in current_values:
            status = "not_updated"
        elif key not in previous_values:
            status = "new"
        elif _comparison_value(current_value) == _comparison_value(previous_value):
            status = "unchanged"
        else:
            status = "changed"
        changes[key] = {
            "status": status,
            "previous": previous_value,
            "current": current_value,
        }
    return changes


def _comparison_value(value: object) -> object:
    if isinstance(value, dict) and "codigo" in value:
        return ("codigo", value["codigo"])
    return value


def _nonnegative_integer(value: object) -> int | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value if value >= 0 else None
        if isinstance(value, str) and value.strip().isdecimal():
            return int(value.strip())
        return None


_IMPORT_BATCH_SIZE = 80
_CONTROL_KEY = key("import")


def _filters(**values):
    return tuple((name, "==", value) for name, value in values.items() if value is not None)


def _require_actor(actor):
    if not actor or not actor.strip():
        raise ValueError("O usuário responsável é obrigatório.")


def _run(callback):
    def guarded(tx):
        control = tx.get("monthly_control", _CONTROL_KEY)
        if control and control.get("pending"):
            raise ValueError("Há uma importação pendente. Reenvie o mesmo boletim para concluí-la.")
        return callback(tx)
    return get_store().run(guarded, guard="monthly")


def _published(reader, row, cache=None):
    import_id = row.get("import_id")
    if import_id is None:
        return True
    cache = cache if cache is not None else {}
    if import_id not in cache:
        imported = reader.get("monthly_imports", key(import_id))
        cache[import_id] = bool(imported and imported.get("published"))
    return cache[import_id]


def _rows(reader, collection, **values):
    cache = {}
    return [r for r in reader.query(collection, _filters(**values)) if _published(reader, r, cache)]


def _record(reader, agravo, patient_ref, competence):
    row = reader.get("monthly_records", key(agravo, patient_ref, competence))
    return row if row and _published(reader, row) else None


def _record_from_row(row):
    return MonthlyRecord(**{name: row[name] for name in MonthlyRecord.__dataclass_fields__})


def _period(reader, agravo, competence):
    return reader.get("monthly_competences", key(agravo, competence))


def _periods(reader, agravo):
    return sorted(reader.query("monthly_competences", _filters(agravo=agravo)),
                  key=lambda r: r["competence"], reverse=True)


def _ensure_competence(tx, agravo, competence, actor):
    if _period(tx, agravo, competence):
        return
    later = any(p["competence"] > competence for p in _periods(tx, agravo))
    now = _now()
    if not later:
        for row in _periods(tx, agravo):
            if row["state"] == "open":
                tx.set("monthly_competences", key(agravo, row["competence"]),
                       {**row, "state": "closed", "closed_by": actor.strip(), "closed_at": now})
    tx.set("monthly_competences", key(agravo, competence), {
        "agravo": agravo, "competence": competence, "state": "closed" if later else "open",
        "opened_by": actor, "opened_at": now, "closed_by": actor if later else None,
        "closed_at": now if later else None})


def open_monthly_competence(*, agravo: str, competence: str, actor: str) -> None:
    competence = str(Competence.parse(competence))
    if agravo not in {"tuberculose", "hanseniase"}:
        raise ValueError("Agravo inválido.")
    if not actor.strip():
        raise ValueError("O usuário responsável é obrigatório.")
    def change(tx):
        if _period(tx, agravo, competence):
            raise ValueError("A competência já foi criada e não pode ser reaberta.")
        periods = _periods(tx, agravo)
        if periods and competence <= periods[0]["competence"]:
            raise ValueError("Só é possível abrir uma competência posterior à já cadastrada.")
        _ensure_competence(tx, agravo, competence, actor)
    _run(change)


def _validate_import_workflow(reader, agravo, competence, protect_workflow):
    periods = _periods(reader, agravo)
    if not protect_workflow or not periods:
        return
    latest = periods[0]
    if competence < latest["competence"] or (competence == latest["competence"] and latest["state"] == "closed"):
        raise ValueError("Não é permitido importar em competência anterior ou encerrada.")
    if competence > latest["competence"]:
        for period in periods:
            if period["state"] == "open" and any(r["state"] != "validated" for r in
                    _rows(reader, "monthly_records", agravo=agravo, competence=period["competence"])):
                raise ValueError("Valide as fichas da competência aberta antes de importar uma nova competência.")


def _stage_import_batch(import_id, records, coverage, batch_index):
    def stage(tx):
        imported = tx.get("monthly_imports", key(import_id))
        if imported.get("published") or imported["next_batch"] > batch_index:
            return
        if imported["next_batch"] != batch_index:
            raise ValueError("Ordem de lotes inválida.")
        control = tx.get("monthly_control", _CONTROL_KEY)
        if not control or control.get("pending") != import_id:
            raise ValueError("A importação não está ativa.")
        agravo, competence = imported["agravo"], imported["competence"]
        inserted, conflicts = imported["inserted"], imported["conflicts"]
        for patient_ref, unit_ref, values in records:
            identity = key(agravo, patient_ref, competence)
            existing = tx.get("monthly_records", identity)
            if existing is None:
                row = {"agravo": agravo, "patient_ref": patient_ref, "competence": competence,
                       "unit_ref": unit_ref, "import_id": import_id, "original_values": values,
                       "updated_values": {}, "state": "draft", "version": 1,
                       "updated_by": None, "updated_at": imported["imported_at"], "reviewer_note": ""}
                tx.set("monthly_records", identity, row)
                tx.set("monthly_record_revisions", key(agravo, patient_ref, competence, 1),
                       {**row, "action": "imported", "actor": imported["imported_by"],
                        "occurred_at": imported["imported_at"], "note": ""})
                inserted += 1
            elif existing["unit_ref"] != unit_ref or existing["original_values"] != values:
                tx.set("monthly_import_conflicts", key(import_id, agravo, patient_ref, competence), {
                    "import_id": import_id, "agravo": agravo, "patient_ref": patient_ref,
                    "competence": competence, "stored_original_values": existing["original_values"],
                    "incoming_original_values": values, "detected_at": imported["imported_at"]})
                conflicts += 1
        for unit_ref in coverage:
            tx.set("monthly_import_unit_coverage", key(import_id, unit_ref), {
                "import_id": import_id, "agravo": agravo, "competence": competence, "unit_ref": unit_ref})
        tx.set("monthly_imports", key(import_id), {**imported, "inserted": inserted,
               "conflicts": conflicts, "next_batch": batch_index + 1})
    get_store().run(stage, guard="monthly")


def import_monthly_records(*, agravo: str, competence: str, source_content: bytes,
                          imported_by: str, records: list[dict[str, object]],
                          unit_coverage: tuple[str, ...] | None = None,
                          protect_workflow: bool = False) -> dict[str, int | bool]:
    competence = str(Competence.parse(competence))
    if agravo not in {"tuberculose", "hanseniase"}:
        raise ValueError("Agravo inválido.")
    if not imported_by.strip():
        raise ValueError("O usuário responsável pela importação é obrigatório.")
    normalized = {}
    for record in records:
        patient_ref, unit_ref = str(record.get("patient_ref", "")).strip(), str(record.get("unit_ref", "")).strip()
        values = record.get("values")
        if not patient_ref or not unit_ref or not isinstance(values, dict):
            raise ValueError("Cada registro precisa de identificador, unidade e valores.")
        if any(not isinstance(k, str) or not k for k in values):
            raise ValueError("Os nomes dos campos devem ser textos não vazios.")
        if patient_ref in normalized:
            raise ValueError("O PDF contém identificadores duplicados nesta competência.")
        original = prepare_original_values(values)
        _json(original)
        normalized[patient_ref] = (unit_ref, original)
    if unit_coverage is not None and any(not isinstance(u, str) or not u.strip() for u in unit_coverage):
        raise ValueError("A lista de unidades cobertas contém valores inválidos.")
    coverage = sorted({u.strip() for u in (unit_coverage or ())} | {u for u, _ in normalized.values()})
    # The fingerprint binds a resumed operation to exactly the same parsed input.
    fingerprint = hashlib.sha256(_json({"records": normalized, "coverage": coverage}).encode()).hexdigest()
    source_hash = hashlib.sha256(source_content).hexdigest()
    import_key = key(agravo, competence, source_hash)
    now = _now()
    def begin(tx):
        control = tx.get("monthly_control", _CONTROL_KEY) or {}
        reservation = tx.get("monthly_import_keys", import_key)
        imported = tx.get("monthly_imports", key(reservation["import_id"])) if reservation else None
        if control.get("pending") and (not imported or control["pending"] != imported["id"]):
            raise ValueError("Há uma importação pendente. Reenvie o mesmo boletim para concluí-la.")
        _validate_import_workflow(tx, agravo, competence, protect_workflow)
        if imported:
            if not imported["published"] and imported["fingerprint"] != fingerprint:
                raise ValueError("A retomada exige o mesmo boletim e a mesma cobertura.")
            return imported
        import_id = tx.next_id("monthly_imports")
        imported = {"id": import_id, "agravo": agravo, "competence": competence,
                    "source_sha256": source_hash, "imported_by": imported_by.strip(),
                    "imported_at": now, "record_count": len(normalized), "published": False,
                    "fingerprint": fingerprint, "inserted": 0, "conflicts": 0, "next_batch": 0}
        tx.set("monthly_import_keys", import_key, {"import_id": import_id})
        tx.set("monthly_imports", key(import_id), imported)
        tx.set("monthly_control", _CONTROL_KEY, {"pending": import_id})
        return imported
    imported = get_store().run(begin, guard="monthly")
    import_id = imported["id"]
    if imported["published"]:
        # Identical-source submissions historically may add explicitly confirmed coverage.
        for offset in range(0, len(coverage), _IMPORT_BATCH_SIZE):
            units = coverage[offset:offset + _IMPORT_BATCH_SIZE]
            def add_coverage(tx):
                for unit in units:
                    tx.set("monthly_import_unit_coverage", key(import_id, unit),
                           {"import_id": import_id, "agravo": agravo, "competence": competence, "unit_ref": unit})
            _run(add_coverage)
        return {"import_id": import_id, "inserted": 0, "conflicts": 0, "duplicate": True}
    items = [(patient, unit, values) for patient, (unit, values) in sorted(normalized.items())]
    count = max(1, (max(len(items), len(coverage)) + _IMPORT_BATCH_SIZE - 1) // _IMPORT_BATCH_SIZE)
    for index in range(imported["next_batch"], count):
        offset = index * _IMPORT_BATCH_SIZE
        _stage_import_batch(import_id, items[offset:offset + _IMPORT_BATCH_SIZE],
                            coverage[offset:offset + _IMPORT_BATCH_SIZE], index)
    def publish(tx):
        result = tx.get("monthly_imports", key(import_id))
        if result["published"]:
            return result, True
        if result["next_batch"] != count:
            raise ValueError("Importação incompleta.")
        _validate_import_workflow(tx, agravo, competence, protect_workflow)
        _ensure_competence(tx, agravo, competence, imported_by)
        tx.set("monthly_imports", key(import_id), {**result, "published": True})
        tx.set("monthly_control", _CONTROL_KEY, {"pending": None})
        return result, False
    result, duplicate = get_store().run(publish, guard="monthly")
    return {"import_id": import_id, "inserted": 0 if duplicate else result["inserted"],
            "conflicts": 0 if duplicate else result["conflicts"], "duplicate": duplicate}


@snapshot_read
def list_monthly_records(*, agravo: str, competence: str, unit_ref: str | None = None) -> tuple[MonthlyRecord, ...]:
    Competence.parse(competence)
    store = get_store()
    if not _period(store, agravo, competence):
        return ()
    rows = _rows(store, "monthly_records", agravo=agravo, competence=competence, unit_ref=unit_ref)
    return tuple(_record_from_row(r) for r in sorted(rows, key=lambda r: r["patient_ref"]))


@snapshot_read
def list_monthly_competences() -> tuple[tuple[str, str], ...]:
    rows = get_store().query("monthly_competences")
    rows.sort(key=lambda r: (-int(r["competence"].replace("-", "")), r["agravo"]))
    return tuple((r["agravo"], r["competence"]) for r in rows)


@snapshot_read
def get_monthly_record(*, agravo: str, patient_ref: str, competence: str) -> MonthlyRecord | None:
    Competence.parse(competence)
    row = _record(get_store(), agravo, patient_ref, competence)
    return _record_from_row(row) if row else None


def _revision(tx, row, action, actor, now, note=""):
    tx.set("monthly_record_revisions", key(row["agravo"], row["patient_ref"], row["competence"], row["version"]),
           {**row, "action": action, "actor": actor, "occurred_at": now, "note": note})


def update_monthly_draft(*, agravo: str, patient_ref: str, competence: str, unit_ref: str,
                         actor: str, values: dict[str, object]) -> MonthlyRecord:
    _require_actor(actor)
    Competence.parse(competence)
    _json(values)
    def change(tx):
        period = _period(tx, agravo, competence)
        if period is None or period["state"] != "open":
            raise ValueError("A competência não está aberta para edição.")
        row = _record(tx, agravo, patient_ref, competence)
        if row is None:
            raise ValueError("Registro mensal não encontrado.")
        if row["unit_ref"].casefold() != unit_ref.casefold():
            raise PermissionError("Registro fora da unidade vinculada.")
        if row["state"] not in {"draft", "returned"}:
            raise ValueError("O registro já foi enviado para análise e está bloqueado.")
        now = _now()
        updated = {**row, "updated_values": {**row["updated_values"], **values}, "version": row["version"]+1,
                   "updated_by": actor, "updated_at": now, "state": "draft"}
        tx.set("monthly_records", key(agravo, patient_ref, competence), updated)
        _revision(tx, updated, "draft_saved", actor, now)
        return _record_from_row(updated)
    return _run(change)


def submit_monthly_record(*, agravo: str, patient_ref: str, competence: str, unit_ref: str, actor: str) -> MonthlyRecord:
    return _change_record_state(agravo=agravo, patient_ref=patient_ref, competence=competence, unit_ref=unit_ref,
        actor=actor, allowed_states={"draft", "returned"}, target_state="submitted", action="submitted")


def review_monthly_record(*, agravo: str, patient_ref: str, competence: str, actor: str,
                          approved: bool, note: str) -> MonthlyRecord:
    if len(note) > 1000:
        raise ValueError("A observação da Vigilância excede 1000 caracteres.")
    return _change_record_state(agravo=agravo, patient_ref=patient_ref, competence=competence, actor=actor,
        allowed_states={"submitted"}, target_state="validated" if approved else "returned",
        action="validated" if approved else "returned", note=note.strip())


def _change_record_state(*, agravo: str, patient_ref: str, competence: str, actor: str,
                         allowed_states: set[str], target_state: RecordState, action: str,
                         unit_ref: str | None = None, note: str | None = None) -> MonthlyRecord:
    _require_actor(actor)
    Competence.parse(competence)
    def change(tx):
        row = _record(tx, agravo, patient_ref, competence)
        if row is None:
            raise ValueError("Registro mensal não encontrado.")
        if unit_ref is not None and row["unit_ref"].casefold() != unit_ref.casefold():
            raise PermissionError("Registro fora da unidade vinculada.")
        if row["state"] not in allowed_states:
            raise ValueError("A situação atual não permite esta operação.")
        period = _period(tx, agravo, competence)
        if period is None or period["state"] != "open":
            raise ValueError("A competência não está aberta para envio." if target_state == "submitted"
                             else "A competência encerrada não pode ser revisada.")
        now = _now()
        updated = {**row, "state": target_state, "version": row["version"]+1, "updated_by": actor,
                   "updated_at": now, "reviewer_note": row["reviewer_note"] if note is None else note}
        tx.set("monthly_records", key(agravo, patient_ref, competence), updated)
        _revision(tx, updated, action, actor, now, note or "")
        if action in {"validated", "returned"}:
            tx.set("monthly_vigilance_notes", key(agravo, patient_ref, competence, updated["version"]), {
                "agravo": agravo, "patient_ref": patient_ref, "competence": competence,
                "version": updated["version"], "actor": actor, "occurred_at": now, "action": action, "note": note or ""})
        return _record_from_row(updated)
    return _run(change)


def close_monthly_competence(*, agravo: str, competence: str, actor: str) -> None:
    Competence.parse(competence)
    if not actor.strip():
        raise ValueError("O usuário responsável é obrigatório.")
    def change(tx):
        period = _period(tx, agravo, competence)
        if period is None or period["state"] != "open":
            raise ValueError("A competência não está aberta.")
        if any(r["state"] != "validated" for r in _rows(tx, "monthly_records", agravo=agravo, competence=competence)):
            raise ValueError("Há registros ainda não validados pela Vigilância.")
        tx.set("monthly_competences", key(agravo, competence),
               {**period, "state": "closed", "closed_by": actor.strip(), "closed_at": _now()})
    _run(change)


@snapshot_read
def get_monthly_competence_state(*, agravo: str, competence: str) -> str | None:
    Competence.parse(competence)
    row = _period(get_store(), agravo, competence)
    return row["state"] if row else None


@snapshot_read
def get_record_revisions(*, agravo: str, patient_ref: str, competence: str) -> tuple[dict[str, object], ...]:
    Competence.parse(competence)
    rows = _rows(get_store(), "monthly_record_revisions", agravo=agravo, patient_ref=patient_ref, competence=competence)
    fields = ("version", "action", "actor", "occurred_at", "original_values", "updated_values", "state", "note")
    return tuple({f: r[f] for f in fields} for r in sorted(rows, key=lambda r: r["version"]))


@snapshot_read
def get_monthly_vigilance_notes(*, agravo: str, patient_ref: str, competence: str) -> tuple[dict[str, str], ...]:
    Competence.parse(competence)
    rows = get_store().query("monthly_vigilance_notes", _filters(agravo=agravo, patient_ref=patient_ref, competence=competence))
    return tuple({f: r[f] for f in ("actor", "occurred_at", "action", "note")} for r in sorted(rows, key=lambda r: r["version"]))


def _followup_from_row(row):
    defaults = {"response_text": "", "draft_text": "", "response_by": None, "response_at": None, "response_version": 0}
    return MonthlyFollowup(**{f: row.get(f, defaults.get(f)) for f in MonthlyFollowup.__dataclass_fields__})


def _followup_timestamp(reader, followup_id):
    now = datetime.fromisoformat(_now())
    row = reader.get("monthly_followups", key(followup_id))
    if row:
        now = max(now, datetime.fromisoformat(row.get("last_operation_at", row["updated_at"])) + timedelta(microseconds=1))
    return now.isoformat(timespec="microseconds")


def _followup_event(tx, row, actor, now, action, old_state, old_text, new_text):
    sequence = tx.next_id("monthly_followup_events")
    tx.set("monthly_followup_events", key(sequence), {
        "id": sequence, "followup_id": row["id"], "actor": actor, "occurred_at": now,
        "action": action, "old_state": old_state, "new_state": row["state"],
        "old_text": old_text, "new_text": new_text, "priority": row["priority"]})


def _new_followup(tx, *, record, actor, text, field_key, priority, rule_id, automatic):
    followup_id = tx.next_id("monthly_followups")
    now = _now()
    row = {"id": followup_id, "agravo": record["agravo"], "patient_ref": record["patient_ref"],
           "unit_ref": record["unit_ref"], "competence": record["competence"], "rule_id": rule_id,
           "field_key": field_key, "automatic_text": text if automatic else "", "vigilance_text": text,
           "state": "automatic_suggestion" if automatic else "awaiting_unit", "priority": priority,
           "created_by": actor, "created_at": now, "updated_by": actor, "updated_at": now,
           "last_operation_at": now, "response_text": "", "draft_text": "", "response_by": None,
           "response_at": None, "response_version": 0, "latest_response_version": 0}
    tx.set("monthly_followups", key(followup_id), row)
    _followup_event(tx, row, actor, now, "automatic_suggestion_created" if automatic else "created_manual",
                    None, "", text)
    return _followup_from_row(row)


def ensure_contact_followup(record: MonthlyRecord) -> MonthlyFollowup | None:
    registered = _nonnegative_integer(record.values.get("contatos_identificados"))
    examined = _nonnegative_integer(record.values.get("contatos_examinados"))
    if registered is None or examined is None or registered <= examined:
        return None
    text = (f"Constam {registered} contatos registrados/identificados e {examined} examinados. "
            "Solicita-se informar a situação dos contatos ainda não examinados e as providências adotadas.")
    def change(tx):
        # Validate against persisted data, never a stale or fabricated record supplied by a caller.
        persisted = _record(tx, record.agravo, record.patient_ref, record.competence)
        if persisted is None:
            raise ValueError("Registro mensal não encontrado.")
        rows = tx.query("monthly_followups", _filters(agravo=record.agravo,
            patient_ref=record.patient_ref, rule_id="contacts_not_examined"))
        active = sorted((r for r in rows if r["state"] != "resolved"), key=lambda r:r["competence"], reverse=True)
        if active:
            return _followup_from_row(active[0])
        same = next((r for r in rows if r["competence"] == record.competence), None)
        if same:
            return _followup_from_row(same)
        return _new_followup(tx, record=persisted, actor="system", text=text,
            field_key="contatos_examinados", priority="normal", rule_id="contacts_not_examined", automatic=True)
    return _run(change)


def create_manual_followup(*, agravo: str, patient_ref: str, competence: str, unit_ref: str,
                           actor: str, text: str, field_key: str = "", priority: str = "normal") -> MonthlyFollowup:
    _require_actor(actor)
    if agravo not in {"tuberculose", "hanseniase"}:
        raise ValueError("Agravo inválido.")
    Competence.parse(competence)
    if not text.strip() or len(text) > 2000:
        raise ValueError("A observação deve conter até 2000 caracteres.")
    editable = {field.key for field in BULLETIN_FIELDS[agravo] if field.monthly_editable}
    if field_key and field_key not in editable:
        raise ValueError("O campo não pode ser vinculado a esta observação.")
    if priority not in {"low", "normal", "high"}:
        raise ValueError("Prioridade inválida.")
    rule_id = f"manual:{secrets.token_hex(12)}"
    def change(tx):
        row = _record(tx, agravo, patient_ref, competence)
        if row is None:
            raise ValueError("Registro mensal não encontrado.")
        if row["unit_ref"].casefold() != unit_ref.casefold():
            raise PermissionError("Registro fora da unidade vinculada.")
        return _new_followup(tx, record=row, actor=actor, text=text.strip(), field_key=field_key,
                             priority=priority, rule_id=rule_id, automatic=False)
    return _run(change)


@snapshot_read
def list_monthly_followups(*, agravo: str | None = None, competence: str | None = None,
                          unit_ref: str | None = None, states: set[str] | None = None,
                          include_automatic: bool = True) -> tuple[MonthlyFollowup, ...]:
    if competence is not None:
        Competence.parse(competence)
    rows = get_store().query("monthly_followups", _filters(agravo=agravo, competence=competence, unit_ref=unit_ref))
    rows = [r for r in rows if (include_automatic or r["state"] != "automatic_suggestion")
            and (not states or r["state"] in states)]
    return tuple(_followup_from_row(r) for r in sorted(rows,
        key=lambda r:(r["competence"],r["unit_ref"],r["patient_ref"],r["id"])))


@snapshot_read
def get_monthly_followup(*, followup_id: int, unit_ref: str | None = None) -> MonthlyFollowup | None:
    row = get_store().get("monthly_followups", key(followup_id))
    if row and unit_ref is not None and (row["unit_ref"] != unit_ref or row["state"] == "automatic_suggestion"):
        return None
    return _followup_from_row(row) if row else None


def review_monthly_followup(*, followup_id: int, actor: str, action: str, text: str,
                           priority: str = "normal") -> MonthlyFollowup:
    _require_actor(actor)
    transitions = {"send":("automatic_suggestion","awaiting_unit"),
        "request_more_info":("responded","needs_more_info"), "start_review":("responded","under_review"),
        "resolve":("responded","resolved"), "finish_review":("under_review","resolved"),
        "reopen":("resolved","awaiting_unit")}
    if action not in transitions and action != "save_note":
        raise ValueError("Ação de revisão inválida.")
    if not text.strip() or len(text) > 2000:
        raise ValueError("A observação deve conter até 2000 caracteres.")
    if priority not in {"low", "normal", "high"}:
        raise ValueError("Prioridade inválida.")
    def change(tx):
        row = tx.get("monthly_followups", key(followup_id))
        if row is None:
            raise ValueError("Pendência não encontrada.")
        if action == "save_note":
            if row["state"] == "resolved":
                raise ValueError("A comunicação concluída não aceita novas observações.")
            target = row["state"]
        else:
            allowed, target = transitions[action]
            if row["state"] != allowed:
                raise ValueError("A situação atual não permite esta operação.")
        now = _followup_timestamp(tx, followup_id)
        updated = {**row, "vigilance_text": text.strip(), "state": target, "priority": priority,
                   "updated_by": actor, "updated_at": now, "last_operation_at": now}
        tx.set("monthly_followups", key(followup_id), updated)
        _followup_event(tx, updated, actor, now, action, row["state"], row["vigilance_text"], text.strip())
        return _followup_from_row(updated)
    return _run(change)


def save_monthly_followup_response(*, followup_id: int, unit_ref: str, actor: str,
                                  text: str, submit: bool) -> MonthlyFollowup:
    _require_actor(actor)
    if len(text) > 4000:
        raise ValueError("A resposta deve ter no máximo 4000 caracteres.")
    if submit and not text.strip():
        raise ValueError("Informe uma resposta antes de enviar.")
    def change(tx):
        row = tx.get("monthly_followups", key(followup_id))
        if row is None or row["unit_ref"] != unit_ref:
            raise PermissionError("Pendência não encontrada nesta unidade.")
        if row["state"] not in {"awaiting_unit", "needs_more_info", "responded"}:
            raise ValueError("Esta pendência não aceita resposta da unidade.")
        now = _followup_timestamp(tx, followup_id)
        version = row.get("latest_response_version", 0) + 1
        sequence = tx.next_id("monthly_followup_responses")
        response = {"id": sequence, "followup_id": followup_id, "version": version, "actor": actor,
                    "occurred_at": now, "state": "submitted" if submit else "draft", "response_text": text.strip()}
        tx.set("monthly_followup_responses", key(sequence), response)
        updated = {**row, "latest_response_version": version, "last_operation_at": now}
        if submit:
            updated.update(state="responded", updated_by=actor, updated_at=now, response_text=text.strip(),
                           draft_text="", response_by=actor, response_at=now, response_version=version)
            _followup_event(tx, updated, actor, now, "unit_submitted", row["state"], row["vigilance_text"], text.strip())
        else:
            updated["draft_text"] = text.strip()
        tx.set("monthly_followups", key(followup_id), updated)
        return _followup_from_row(updated)
    return _run(change)


@snapshot_read
def get_monthly_followup_history(followup_id: int) -> tuple[dict[str, object], ...]:
    store = get_store()
    events = store.query("monthly_followup_events", _filters(followup_id=followup_id))
    responses = store.query("monthly_followup_responses", _filters(followup_id=followup_id))
    rows = [{"occurred_at":r["occurred_at"], "actor":r["actor"], "label":r["action"],
             "old_state":r["old_state"], "new_state":r["new_state"], "text":r["new_text"],
             "sequence":r["id"], "kind":"event"} for r in events]
    rows += [{"occurred_at":r["occurred_at"], "actor":r["actor"], "label":r["state"],
              "old_state":None, "new_state":None, "text":r["response_text"],
              "sequence":r["id"], "kind":"response"} for r in responses]
    return tuple(sorted(rows, key=lambda r:(r["occurred_at"], 0 if r["kind"]=="event" else 1,r["sequence"])))


@snapshot_read
def monthly_followup_metrics(*, agravo: str | None = None, competence: str | None = None,
                             unit_ref: str | None = None, state: str | None = None,
                             include_automatic: bool = True) -> dict[str, object]:
    followups = list_monthly_followups(agravo=agravo, competence=competence, unit_ref=unit_ref,
                                      states={state} if state else None, include_automatic=include_automatic)
    by_state, by_unit, by_agravo, by_competence = {}, {}, {}, {}
    submitted_count, durations = 0, []
    store = get_store()
    for f in followups:
        for mapping, value in ((by_state,f.state),(by_unit,f.unit_ref),(by_agravo,f.agravo),(by_competence,f.competence)):
            mapping[value] = mapping.get(value,0) + 1
        responses = sorted((r for r in store.query("monthly_followup_responses", _filters(followup_id=f.id))
                            if r["state"] == "submitted"), key=lambda r:r["occurred_at"])
        submitted_count += len(responses)
        events = [r for r in store.query("monthly_followup_events", _filters(followup_id=f.id))
                  if r["action"] in {"send","request_more_info","reopen"}]
        for response in responses:
            preceding = [e["occurred_at"] for e in events if e["occurred_at"] <= response["occurred_at"]]
            if not preceding:
                continue
            sent = max(preceding)
            if any(sent < earlier["occurred_at"] < response["occurred_at"] for earlier in responses):
                continue
            durations.append((datetime.fromisoformat(response["occurred_at"]) - datetime.fromisoformat(sent)).total_seconds())
    return {"total":len(followups), "por_situacao":by_state, "por_unidade":by_unit,
            "por_agravo":by_agravo, "por_competencia":by_competence, "respostas_enviadas":submitted_count,
            "tempo_medio_resposta_segundos":sum(durations)/len(durations) if durations else None}


def set_monthly_monitoring_deadline(*, agravo: str, competence: str, opened_on: str, due_on: str,
                                    extension_due_on: str | None, actor: str) -> dict[str, str | None]:
    _require_actor(actor)
    if agravo not in {"tuberculose", "hanseniase"}:
        raise ValueError("Agravo inválido.")
    Competence.parse(competence)
    try:
        opened, due = date.fromisoformat(opened_on), date.fromisoformat(due_on)
        extension = date.fromisoformat(extension_due_on) if extension_due_on else None
    except ValueError as error:
        raise ValueError("Informe datas válidas no formato AAAA-MM-DD.") from error
    if due < opened or (extension is not None and extension < due):
        raise ValueError("O prazo final deve ser após a abertura e a prorrogação não pode antecipá-lo.")
    values = {"opened_on":opened_on,"due_on":due_on,"extension_due_on":extension_due_on}
    def change(tx):
        old = tx.get("monthly_monitoring_deadlines", key(agravo,competence))
        now = _now()
        tx.set("monthly_monitoring_deadlines",key(agravo,competence),
               {**values,"agravo":agravo,"competence":competence,"updated_by":actor,"updated_at":now})
        sequence = tx.next_id("monthly_monitoring_deadline_events")
        tx.set("monthly_monitoring_deadline_events",key(sequence),{
            "id":sequence,"agravo":agravo,"competence":competence,"actor":actor,"occurred_at":now,
            "action":"updated" if old else "created","old_values":{f:old[f] for f in values} if old else {},"new_values":values})
        return values
    return _run(change)


@snapshot_read
def get_monthly_monitoring_deadline(*, agravo: str, competence: str) -> dict[str, str | None] | None:
    Competence.parse(competence)
    return get_store().get("monthly_monitoring_deadlines", key(agravo,competence))


@snapshot_read
def list_monthly_units(agravo: str) -> tuple[str, ...]:
    if agravo not in {"tuberculose", "hanseniase"}:
        raise ValueError("Agravo inválido.")
    return tuple(sorted({r["unit_ref"] for r in _rows(get_store(),"monthly_records",agravo=agravo)}))




@snapshot_read
def monthly_unit_monitoring(*, agravo: str, competence: str, units: tuple[str, ...],
                            as_of: date | None = None) -> tuple[dict[str, object], ...]:
    if agravo not in {"tuberculose", "hanseniase"}:
        raise ValueError("Agravo inv?lido.")
    parsed_competence = Competence.parse(competence)
    today = as_of or date.today()
    previous_competence = str(parsed_competence.previous())
    store = get_store()
    imported = any(r.get("published") for r in store.query("monthly_imports", _filters(agravo=agravo,competence=competence)))
    conflicts = len(_rows(store,"monthly_import_conflicts",agravo=agravo,competence=competence))
    deadline = store.get("monthly_monitoring_deadlines",key(agravo,competence))
    outputs = []
    for unit_ref in units:
        covered = bool(_rows(store,"monthly_import_unit_coverage",agravo=agravo,competence=competence,unit_ref=unit_ref))
        records = _rows(store,"monthly_records",agravo=agravo,competence=competence,unit_ref=unit_ref)
        records.sort(key=lambda r:r["patient_ref"])
        current_refs = {row["patient_ref"] for row in records}
        previous_records = _rows(store,"monthly_records",agravo=agravo,competence=previous_competence,unit_ref=unit_ref)
        previous_records.sort(key=lambda r:r["patient_ref"])
        previous_refs = {row["patient_ref"] for row in previous_records}
        confirmation_row = store.get("monthly_unit_confirmations",key(agravo,competence,unit_ref))
        expected = len(records)
        updated = sum(row["state"] in {"submitted", "validated"} for row in records)
        drafts = sum(
            row["state"] == "draft" and row["updated_by"] is not None
            for row in records
        )
        returned = sum(row["state"] == "returned" for row in records)
        initiated = drafts + returned
        pending = expected - updated
        last_updated = max(
            (row["updated_at"] for row in records if row["updated_by"]),
            default=None,
        )
        missing_previous = len(previous_refs - current_refs)
        available = imported and covered and conflicts == 0
        effective_due = (
            deadline["extension_due_on"] or deadline["due_on"]
            if deadline else None
        )
        past_due = bool(
            effective_due and date.fromisoformat(effective_due) < today
        )
        confirmation_status = (
            confirmation_row["status"] if confirmation_row else None
        )
        if not available:
            situation = "data_unavailable"
        elif expected == 0:
            if confirmation_status in {"patients_missing", "review_requested"}:
                situation = "reconciliation_required"
            elif confirmation_status == "confirmed_absent" and (
                missing_previous == 0
                or confirmation_row["updated_role"] == "surveillance"
            ):
                situation = "silent_confirmed"
            else:
                situation = "silent_pending"
        elif updated == expected:
            situation = "complete"
        elif updated or initiated:
            situation = "partial"
        else:
            situation = "no_update" if past_due else "awaiting"
        patient_items = []
        for record in records:
            if record["state"] in {"submitted", "validated"}:
                patient_situation = "complete"
            elif record["state"] == "returned" or (
                record["state"] == "draft" and record["updated_by"] is not None
            ):
                patient_situation = "partial"
            else:
                patient_situation = "no_update" if past_due else "awaiting"
            patient_items.append(
                {
                    "patient_ref": record["patient_ref"],
                    "state": record["state"],
                    "situation": patient_situation,
                    "updated_by": record["updated_by"],
                    "updated_at": record["updated_at"],
                }
            )
        outputs.append(
            {
                "agravo": agravo,
                "competence": competence,
                "unit_ref": unit_ref,
                "data_available": available,
                "imported": imported,
                "coverage_confirmed": covered,
                "integrity_ok": conflicts == 0,
                "patients_expected": expected,
                "patients_updated": updated,
                "patients_pending": pending,
                "drafts": drafts,
                "returned": returned,
                "patients_partial": initiated,
                "patients_unupdated": sum(
                    patient["situation"] == "no_update"
                    for patient in patient_items
                ),
                "patients_awaiting": sum(
                    patient["situation"] == "awaiting"
                    for patient in patient_items
                ),
                "percentage": round(updated * 100 / expected) if expected else 0,
                "last_updated": last_updated,
                "opened_on": deadline["opened_on"] if deadline else None,
                "due_on": deadline["due_on"] if deadline else None,
                "extension_due_on": deadline["extension_due_on"] if deadline else None,
                "effective_due_on": effective_due,
                "situation": situation,
                "confirmation_status": confirmation_status,
                "confirmation_note": confirmation_row["note"] if confirmation_row else "",
                "confirmation_by": confirmation_row["updated_by"] if confirmation_row else None,
                "confirmation_at": confirmation_row["updated_at"] if confirmation_row else None,
                "previous_missing": missing_previous,
                "patients": tuple(patient_items),
                "previous_missing_patients": tuple(
                    {
                        "patient_ref": row["patient_ref"],
                        "state": row["state"],
                    }
                    for row in previous_records
                    if row["patient_ref"] not in current_refs
                ),
            }
        )
    return tuple(outputs)


def update_monthly_unit_confirmation(*, agravo: str, competence: str, unit_ref: str, actor: str,
                                    actor_role: str, action: str, note: str = "") -> dict[str, object]:
    _require_actor(actor)
    if agravo not in {"tuberculose", "hanseniase"}:
        raise ValueError("Agravo inválido.")
    Competence.parse(competence)
    if actor_role == "unit" and action not in {"confirm_absence","report_missing_patients","request_review"}:
        raise ValueError("Ação não permitida para a unidade.")
    if actor_role == "surveillance" and action not in {"request_confirmation","confirm_absence","resolve_reconciliation"}:
        raise ValueError("Ação não permitida para a Vigilância.")
    if actor_role not in {"unit","surveillance"}:
        raise ValueError("Perfil sem permissão para confirmar ausência.")
    if len(note)>2000:
        raise ValueError("A observação deve conter até 2000 caracteres.")
    if action in {"report_missing_patients","request_review","resolve_reconciliation"} and not note.strip():
        raise ValueError("Descreva a divergência ou a conferência realizada.")
    statuses={"request_confirmation":"awaiting_confirmation","confirm_absence":"confirmed_absent",
              "report_missing_patients":"patients_missing","request_review":"review_requested",
              "resolve_reconciliation":"confirmed_absent"}
    status=statuses[action]
    def change(tx):
        current=_rows(tx,"monthly_records",agravo=agravo,competence=competence,unit_ref=unit_ref)
        imported=_rows(tx,"monthly_import_unit_coverage",agravo=agravo,competence=competence,unit_ref=unit_ref)
        conflicts=_rows(tx,"monthly_import_conflicts",agravo=agravo,competence=competence)
        if not imported or conflicts or current:
            raise ValueError("A confirmação só está disponível para unidade sem pacientes em boletim importado.")
        if action=="confirm_absence":
            previous=str(Competence.parse(competence).previous())
            missing=_rows(tx,"monthly_records",agravo=agravo,competence=previous,unit_ref=unit_ref)
            if missing and actor_role=="unit":
                raise ValueError("Há pacientes no histórico anterior sem registro atual; solicite conferência antes de confirmar.")
            if missing and actor_role=="surveillance" and not note.strip():
                raise ValueError("Registre a conferência dos pacientes do mês anterior antes de confirmar a ausência.")
        existing=tx.get("monthly_unit_confirmations",key(agravo,competence,unit_ref))
        now=_now()
        row={"agravo":agravo,"competence":competence,"unit_ref":unit_ref,"status":status,
             "note":note.strip(),"updated_by":actor,"updated_role":actor_role,"updated_at":now}
        tx.set("monthly_unit_confirmations",key(agravo,competence,unit_ref),row)
        sequence=tx.next_id("monthly_unit_confirmation_events")
        tx.set("monthly_unit_confirmation_events",key(sequence),{
            "id":sequence,"agravo":agravo,"competence":competence,"unit_ref":unit_ref,
            "actor":actor,"actor_role":actor_role,"occurred_at":now,"action":action,
            "old_status":existing["status"] if existing else None,"new_status":status,"note":note.strip()})
        return row
    return _run(change)


@snapshot_read
def get_monthly_unit_confirmation_history(*, agravo: str, competence: str, unit_ref: str) -> tuple[dict[str, object], ...]:
    Competence.parse(competence)
    rows=get_store().query("monthly_unit_confirmation_events",_filters(agravo=agravo,competence=competence,unit_ref=unit_ref))
    fields=("actor","actor_role","occurred_at","action","old_status","new_status","note")
    return tuple({f:r[f] for f in fields} for r in sorted(rows,key=lambda r:(r["occurred_at"],r["id"])))
