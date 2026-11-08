import hashlib
import json
import secrets
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Literal

from monitoramento.bulletin_forms import BULLETIN_FIELDS, prepare_original_values
from monitoramento.monthly_workflow import Competence
from monitoramento.tracking_store import database_path

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


def _connect() -> sqlite3.Connection:
    connection = sqlite3.connect(database_path(), timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _initialize(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS monthly_competences (
            agravo TEXT NOT NULL,
            competence TEXT NOT NULL,
            state TEXT NOT NULL CHECK (state IN ('open', 'closed')),
            opened_by TEXT NOT NULL,
            opened_at TEXT NOT NULL,
            closed_by TEXT,
            closed_at TEXT,
            PRIMARY KEY (agravo, competence)
        );
        CREATE TABLE IF NOT EXISTS monthly_imports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agravo TEXT NOT NULL,
            competence TEXT NOT NULL,
            source_sha256 TEXT NOT NULL,
            imported_by TEXT NOT NULL,
            imported_at TEXT NOT NULL,
            record_count INTEGER NOT NULL,
            UNIQUE (agravo, competence, source_sha256)
        );
        CREATE TABLE IF NOT EXISTS monthly_import_unit_coverage (
            import_id INTEGER NOT NULL REFERENCES monthly_imports(id),
            unit_ref TEXT NOT NULL,
            PRIMARY KEY (import_id, unit_ref)
        );
        CREATE TABLE IF NOT EXISTS monthly_records (
            agravo TEXT NOT NULL,
            patient_ref TEXT NOT NULL,
            competence TEXT NOT NULL,
            unit_ref TEXT NOT NULL,
            import_id INTEGER NOT NULL REFERENCES monthly_imports(id),
            original_values TEXT NOT NULL,
            updated_values TEXT NOT NULL DEFAULT '{}',
            state TEXT NOT NULL CHECK (
                state IN ('draft', 'submitted', 'returned', 'validated')
            ),
            version INTEGER NOT NULL DEFAULT 1,
            updated_by TEXT,
            updated_at TEXT NOT NULL,
            reviewer_note TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (agravo, patient_ref, competence),
            FOREIGN KEY (agravo, competence)
                REFERENCES monthly_competences(agravo, competence)
        );
        CREATE TABLE IF NOT EXISTS monthly_record_revisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agravo TEXT NOT NULL,
            patient_ref TEXT NOT NULL,
            competence TEXT NOT NULL,
            version INTEGER NOT NULL,
            action TEXT NOT NULL,
            actor TEXT NOT NULL,
            occurred_at TEXT NOT NULL,
            original_values TEXT NOT NULL,
            updated_values TEXT NOT NULL,
            state TEXT NOT NULL,
            note TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS monthly_import_conflicts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            import_id INTEGER NOT NULL REFERENCES monthly_imports(id),
            agravo TEXT NOT NULL,
            patient_ref TEXT NOT NULL,
            competence TEXT NOT NULL,
            stored_original_values TEXT NOT NULL,
            incoming_original_values TEXT NOT NULL,
            detected_at TEXT NOT NULL,
            UNIQUE (import_id, agravo, patient_ref, competence)
        );
        CREATE TABLE IF NOT EXISTS monthly_vigilance_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agravo TEXT NOT NULL,
            patient_ref TEXT NOT NULL,
            competence TEXT NOT NULL,
            actor TEXT NOT NULL,
            occurred_at TEXT NOT NULL,
            action TEXT NOT NULL,
            note TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS monthly_followups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agravo TEXT NOT NULL,
            patient_ref TEXT NOT NULL,
            unit_ref TEXT NOT NULL,
            competence TEXT NOT NULL,
            rule_id TEXT NOT NULL,
            field_key TEXT NOT NULL DEFAULT '',
            automatic_text TEXT NOT NULL DEFAULT '',
            vigilance_text TEXT NOT NULL,
            state TEXT NOT NULL CHECK (state IN (
                'automatic_suggestion', 'awaiting_unit', 'responded',
                'under_review', 'needs_more_info', 'resolved'
            )),
            priority TEXT NOT NULL DEFAULT 'normal' CHECK (
                priority IN ('low', 'normal', 'high')
            ),
            created_by TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_by TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE (agravo, patient_ref, competence, rule_id),
            FOREIGN KEY (agravo, patient_ref, competence)
                REFERENCES monthly_records(agravo, patient_ref, competence)
        );
        CREATE TABLE IF NOT EXISTS monthly_followup_responses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            followup_id INTEGER NOT NULL REFERENCES monthly_followups(id),
            version INTEGER NOT NULL,
            actor TEXT NOT NULL,
            occurred_at TEXT NOT NULL,
            state TEXT NOT NULL CHECK (state IN ('draft', 'submitted')),
            response_text TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS monthly_followup_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            followup_id INTEGER NOT NULL REFERENCES monthly_followups(id),
            actor TEXT NOT NULL,
            occurred_at TEXT NOT NULL,
            action TEXT NOT NULL,
            old_state TEXT,
            new_state TEXT NOT NULL,
            old_text TEXT NOT NULL,
            new_text TEXT NOT NULL,
            priority TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS monthly_monitoring_deadlines (
            agravo TEXT NOT NULL,
            competence TEXT NOT NULL,
            opened_on TEXT NOT NULL,
            due_on TEXT NOT NULL,
            extension_due_on TEXT,
            updated_by TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (agravo, competence)
        );
        CREATE TABLE IF NOT EXISTS monthly_monitoring_deadline_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agravo TEXT NOT NULL,
            competence TEXT NOT NULL,
            actor TEXT NOT NULL,
            occurred_at TEXT NOT NULL,
            action TEXT NOT NULL,
            old_values TEXT NOT NULL,
            new_values TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS monthly_unit_confirmations (
            agravo TEXT NOT NULL,
            competence TEXT NOT NULL,
            unit_ref TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN (
                'awaiting_confirmation', 'confirmed_absent',
                'patients_missing', 'review_requested'
            )),
            note TEXT NOT NULL,
            updated_by TEXT NOT NULL,
            updated_role TEXT NOT NULL CHECK (updated_role IN ('unit', 'surveillance')),
            updated_at TEXT NOT NULL,
            PRIMARY KEY (agravo, competence, unit_ref)
        );
        CREATE TABLE IF NOT EXISTS monthly_unit_confirmation_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agravo TEXT NOT NULL,
            competence TEXT NOT NULL,
            unit_ref TEXT NOT NULL,
            actor TEXT NOT NULL,
            actor_role TEXT NOT NULL CHECK (actor_role IN ('unit', 'surveillance')),
            occurred_at TEXT NOT NULL,
            action TEXT NOT NULL,
            old_status TEXT,
            new_status TEXT NOT NULL,
            note TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_monthly_followups_unit_state
            ON monthly_followups (unit_ref, state, competence);
        CREATE INDEX IF NOT EXISTS idx_monthly_records_unit
            ON monthly_records (agravo, unit_ref, competence);
        """
    )
    columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(monthly_competences)").fetchall()
    }
    if "closed_by" not in columns:
        connection.execute("ALTER TABLE monthly_competences ADD COLUMN closed_by TEXT")
    followup_columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(monthly_followups)").fetchall()
    }
    if "field_key" not in followup_columns:
        connection.execute(
            "ALTER TABLE monthly_followups ADD COLUMN field_key TEXT NOT NULL DEFAULT ''"
        )
        connection.execute(
            """
            UPDATE monthly_followups SET field_key = 'contatos_examinados'
            WHERE rule_id = 'contacts_not_examined' AND field_key = ''
            """
        )
        connection.commit()
    connection.execute(
        """
        INSERT OR IGNORE INTO monthly_import_unit_coverage (import_id, unit_ref)
        SELECT DISTINCT import_id, unit_ref FROM monthly_records
        """
    )
    connection.commit()


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")


def _followup_timestamp(connection: sqlite3.Connection, followup_id: int) -> str:
    """Keep each operation ordered, including when the system clock repeats."""
    now = datetime.fromisoformat(_now())
    latest = connection.execute(
        """
        SELECT MAX(occurred_at) FROM (
            SELECT occurred_at FROM monthly_followup_events WHERE followup_id = ?
            UNION ALL
            SELECT occurred_at FROM monthly_followup_responses WHERE followup_id = ?
        )
        """,
        (followup_id, followup_id),
    ).fetchone()[0]
    if latest is not None:
        now = max(now, datetime.fromisoformat(latest) + timedelta(microseconds=1))
    return now.isoformat(timespec="microseconds")


def _json(values: dict[str, object]) -> str:
    try:
        return json.dumps(values, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError) as error:
        raise ValueError("Os valores do registro não são serializáveis.") from error


def _ensure_competence(
    connection: sqlite3.Connection,
    agravo: str,
    competence: str,
    actor: str,
) -> None:
    existing = connection.execute(
        "SELECT state FROM monthly_competences WHERE agravo = ? AND competence = ?",
        (agravo, competence),
    ).fetchone()
    if existing:
        return

    later = connection.execute(
        "SELECT 1 FROM monthly_competences WHERE agravo = ? AND competence > ? LIMIT 1",
        (agravo, competence),
    ).fetchone()
    state = "closed" if later else "open"
    now = _now()
    if state == "open":
        connection.execute(
            """
            UPDATE monthly_competences
            SET state = 'closed', closed_by = ?, closed_at = ?
            WHERE agravo = ? AND state = 'open'
            """,
            (actor.strip(), now, agravo),
        )
    connection.execute(
        """
        INSERT INTO monthly_competences (
            agravo, competence, state, opened_by, opened_at, closed_by, closed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            agravo,
            competence,
            state,
            actor,
            now,
            actor if state == "closed" else None,
            now if state == "closed" else None,
        ),
    )


def open_monthly_competence(
    *,
    agravo: str,
    competence: str,
    actor: str,
) -> None:
    parsed = Competence.parse(competence)
    if agravo not in {"tuberculose", "hanseniase"}:
        raise ValueError("Agravo inválido.")
    if not actor.strip():
        raise ValueError("O usuário responsável é obrigatório.")
    with closing(_connect()) as connection:
        _initialize(connection)
        connection.execute("BEGIN IMMEDIATE")
        existing = connection.execute(
            "SELECT state FROM monthly_competences WHERE agravo = ? AND competence = ?",
            (agravo, competence),
        ).fetchone()
        if existing:
            raise ValueError("A competência já foi criada e não pode ser reaberta.")
        latest = connection.execute(
            """
            SELECT MAX(competence) AS competence FROM monthly_competences
            WHERE agravo = ?
            """,
            (agravo,),
        ).fetchone()["competence"]
        if latest and competence <= latest:
            raise ValueError("Só é possível abrir uma competência posterior à já cadastrada.")
        now = _now()
        connection.execute(
            """
            UPDATE monthly_competences
            SET state = 'closed', closed_by = ?, closed_at = ?
            WHERE agravo = ? AND state = 'open'
            """,
                (actor.strip(), now, agravo),
        )
        connection.execute(
            """
            INSERT INTO monthly_competences (
                agravo, competence, state, opened_by, opened_at
            ) VALUES (?, ?, 'open', ?, ?)
            """,
            (agravo, str(parsed), actor.strip(), now),
        )
        connection.commit()


def _record_from_row(row: sqlite3.Row) -> MonthlyRecord:
    return MonthlyRecord(
        agravo=row["agravo"],
        patient_ref=row["patient_ref"],
        unit_ref=row["unit_ref"],
        competence=row["competence"],
        original_values=json.loads(row["original_values"]),
        updated_values=json.loads(row["updated_values"]),
        state=row["state"],
        version=row["version"],
        updated_by=row["updated_by"],
        updated_at=row["updated_at"],
        reviewer_note=row["reviewer_note"],
    )


def import_monthly_records(
    *,
    agravo: str,
    competence: str,
    source_content: bytes,
    imported_by: str,
    records: list[dict[str, object]],
    unit_coverage: tuple[str, ...] | None = None,
    protect_workflow: bool = False,
) -> dict[str, int | bool]:
    competence = str(Competence.parse(competence))
    if agravo not in {"tuberculose", "hanseniase"}:
        raise ValueError("Agravo inválido.")
    if not imported_by.strip():
        raise ValueError("O usuário responsável pela importação é obrigatório.")

    normalized_records: dict[str, tuple[str, dict[str, object]]] = {}
    for record in records:
        patient_ref = str(record.get("patient_ref", "")).strip()
        unit_ref = str(record.get("unit_ref", "")).strip()
        values = record.get("values")
        if not patient_ref or not unit_ref or not isinstance(values, dict):
            raise ValueError("Cada registro precisa de identificador, unidade e valores.")
        if any(not isinstance(key, str) or not key for key in values):
            raise ValueError("Os nomes dos campos devem ser textos não vazios.")
        if patient_ref in normalized_records:
            raise ValueError("O PDF contém identificadores duplicados nesta competência.")
        original_values = prepare_original_values(values)
        _json(original_values)
        normalized_records[patient_ref] = (unit_ref, original_values)
    if unit_coverage is not None and any(
        not isinstance(unit, str) or not unit.strip()
        for unit in unit_coverage
    ):
        raise ValueError("A lista de unidades cobertas contém valores inválidos.")
    covered_units = {
        unit.strip() for unit in (unit_coverage or ())
    }
    covered_units.update(unit_ref for unit_ref, _ in normalized_records.values())

    source_hash = hashlib.sha256(source_content).hexdigest()
    now = _now()
    inserted = 0
    conflicts = 0

    with closing(_connect()) as connection:
        _initialize(connection)
        connection.execute("BEGIN IMMEDIATE")
        if protect_workflow:
            latest = connection.execute(
                "SELECT competence, state FROM monthly_competences WHERE agravo = ? "
                "ORDER BY competence DESC LIMIT 1", (agravo,),
            ).fetchone()
            if latest and (competence < latest["competence"] or (
                competence == latest["competence"] and latest["state"] == "closed"
            )):
                raise ValueError("Não é permitido importar em competência anterior ou encerrada.")
            if latest and competence > latest["competence"]:
                pending = connection.execute(
                    "SELECT 1 FROM monthly_records AS r JOIN monthly_competences AS c "
                    "ON c.agravo = r.agravo AND c.competence = r.competence "
                    "WHERE c.agravo = ? AND c.state = 'open' AND r.state != 'validated' LIMIT 1",
                    (agravo,),
                ).fetchone()
                if pending:
                    raise ValueError("Valide as fichas da competência aberta antes de importar uma nova competência.")
        _ensure_competence(connection, agravo, competence, imported_by)
        existing_import = connection.execute(
            """
            SELECT id FROM monthly_imports
            WHERE agravo = ? AND competence = ? AND source_sha256 = ?
            """,
            (agravo, competence, source_hash),
        ).fetchone()
        if existing_import:
            connection.executemany(
                """
                INSERT OR IGNORE INTO monthly_import_unit_coverage (import_id, unit_ref)
                VALUES (?, ?)
                """,
                (
                    (existing_import["id"], unit_ref)
                    for unit_ref in sorted(covered_units)
                ),
            )
            connection.commit()
            return {"import_id": existing_import["id"], "inserted": 0, "conflicts": 0, "duplicate": True}

        cursor = connection.execute(
            """
            INSERT INTO monthly_imports (
                agravo, competence, source_sha256, imported_by, imported_at, record_count
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                agravo,
                competence,
                source_hash,
                imported_by.strip(),
                now,
                len(normalized_records),
            ),
        )
        import_id = cursor.lastrowid
        connection.executemany(
            """
            INSERT INTO monthly_import_unit_coverage (import_id, unit_ref)
            VALUES (?, ?)
            """,
            ((import_id, unit_ref) for unit_ref in sorted(covered_units)),
        )

        for patient_ref, (unit_ref, values) in normalized_records.items():
            existing = connection.execute(
                """
                SELECT unit_ref, original_values FROM monthly_records
                WHERE agravo = ? AND patient_ref = ? AND competence = ?
                """,
                (agravo, patient_ref, competence),
            ).fetchone()
            serialized_values = _json(values)
            if existing is None:
                connection.execute(
                    """
                    INSERT INTO monthly_records (
                        agravo, patient_ref, competence, unit_ref, import_id,
                        original_values, updated_values, state, version, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, '{}', 'draft', 1, ?)
                    """,
                    (
                        agravo,
                        patient_ref,
                        competence,
                        unit_ref,
                        import_id,
                        serialized_values,
                        now,
                    ),
                )
                inserted += 1
                connection.execute(
                    """
                    INSERT INTO monthly_record_revisions (
                        agravo, patient_ref, competence, version, action, actor,
                        occurred_at, original_values, updated_values, state
                    ) VALUES (?, ?, ?, 1, 'imported', ?, ?, ?, '{}', 'draft')
                    """,
                    (agravo, patient_ref, competence, imported_by, now, serialized_values),
                )
            elif (
                existing["unit_ref"] != unit_ref
                or existing["original_values"] != serialized_values
            ):
                connection.execute(
                    """
                    INSERT INTO monthly_import_conflicts (
                        import_id, agravo, patient_ref, competence,
                        stored_original_values, incoming_original_values, detected_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        import_id,
                        agravo,
                        patient_ref,
                        competence,
                        existing["original_values"],
                        serialized_values,
                        now,
                    ),
                )
                conflicts += 1

        connection.commit()
    return {
        "import_id": import_id,
        "inserted": inserted,
        "conflicts": conflicts,
        "duplicate": False,
    }


def list_monthly_records(
    *,
    agravo: str,
    competence: str,
    unit_ref: str | None = None,
) -> tuple[MonthlyRecord, ...]:
    Competence.parse(competence)
    with closing(_connect()) as connection:
        _initialize(connection)
        query = """
            SELECT r.* FROM monthly_records AS r
            JOIN monthly_competences AS c
              ON c.agravo = r.agravo AND c.competence = r.competence
            WHERE r.agravo = ? AND r.competence = ?
        """
        params: list[str] = [agravo, competence]
        if unit_ref is not None:
            query += " AND r.unit_ref = ?"
            params.append(unit_ref)
        query += " ORDER BY r.patient_ref"
        rows = connection.execute(query, params).fetchall()
    return tuple(_record_from_row(row) for row in rows)


def list_monthly_competences() -> tuple[tuple[str, str], ...]:
    with closing(_connect()) as connection:
        _initialize(connection)
        rows = connection.execute(
            """
            SELECT agravo, competence FROM monthly_competences
            ORDER BY competence DESC, agravo
            """
        ).fetchall()
    return tuple((row["agravo"], row["competence"]) for row in rows)


def get_monthly_record(
    *,
    agravo: str,
    patient_ref: str,
    competence: str,
) -> MonthlyRecord | None:
    Competence.parse(competence)
    with closing(_connect()) as connection:
        _initialize(connection)
        row = connection.execute(
            """
            SELECT * FROM monthly_records
            WHERE agravo = ? AND patient_ref = ? AND competence = ?
            """,
            (agravo, patient_ref, competence),
        ).fetchone()
    return _record_from_row(row) if row else None


def update_monthly_draft(
    *,
    agravo: str,
    patient_ref: str,
    competence: str,
    unit_ref: str,
    actor: str,
    values: dict[str, object],
) -> MonthlyRecord:
    Competence.parse(competence)
    serialized_patch = _json(values)
    now = _now()
    with closing(_connect()) as connection:
        _initialize(connection)
        connection.execute("BEGIN IMMEDIATE")
        period = connection.execute(
            """
            SELECT state FROM monthly_competences
            WHERE agravo = ? AND competence = ?
            """,
            (agravo, competence),
        ).fetchone()
        if period is None or period["state"] != "open":
            raise ValueError("A competência não está aberta para edição.")
        row = connection.execute(
            """
            SELECT * FROM monthly_records
            WHERE agravo = ? AND patient_ref = ? AND competence = ?
            """,
            (agravo, patient_ref, competence),
        ).fetchone()
        if row is None:
            raise ValueError("Registro mensal não encontrado.")
        if row["unit_ref"].casefold() != unit_ref.casefold():
            raise PermissionError("Registro fora da unidade vinculada.")
        if row["state"] not in {"draft", "returned"}:
            raise ValueError("O registro já foi enviado para análise e está bloqueado.")

        old_updated = json.loads(row["updated_values"])
        merged_updated = {**old_updated, **values}
        serialized_updated = _json(merged_updated)
        version = row["version"] + 1
        connection.execute(
            """
            UPDATE monthly_records SET updated_values = ?, version = ?,
                updated_by = ?, updated_at = ?, state = 'draft'
            WHERE agravo = ? AND patient_ref = ? AND competence = ?
            """,
            (
                serialized_updated,
                version,
                actor,
                now,
                agravo,
                patient_ref,
                competence,
            ),
        )
        connection.execute(
            """
            INSERT INTO monthly_record_revisions (
                agravo, patient_ref, competence, version, action, actor,
                occurred_at, original_values, updated_values, state
            ) VALUES (?, ?, ?, ?, 'draft_saved', ?, ?, ?, ?, 'draft')
            """,
            (
                agravo,
                patient_ref,
                competence,
                version,
                actor,
                now,
                row["original_values"],
                serialized_updated,
            ),
        )
        saved = connection.execute(
            """
            SELECT * FROM monthly_records
            WHERE agravo = ? AND patient_ref = ? AND competence = ?
            """,
            (agravo, patient_ref, competence),
        ).fetchone()
        connection.commit()
    return _record_from_row(saved)


def submit_monthly_record(
    *,
    agravo: str,
    patient_ref: str,
    competence: str,
    unit_ref: str,
    actor: str,
) -> MonthlyRecord:
    return _change_record_state(
        agravo=agravo,
        patient_ref=patient_ref,
        competence=competence,
        unit_ref=unit_ref,
        actor=actor,
        allowed_states={"draft", "returned"},
        target_state="submitted",
        action="submitted",
    )


def review_monthly_record(
    *,
    agravo: str,
    patient_ref: str,
    competence: str,
    actor: str,
    approved: bool,
    note: str,
) -> MonthlyRecord:
    if len(note) > 1000:
        raise ValueError("A observação da Vigilância excede 1000 caracteres.")
    return _change_record_state(
        agravo=agravo,
        patient_ref=patient_ref,
        competence=competence,
        actor=actor,
        allowed_states={"submitted"},
        target_state="validated" if approved else "returned",
        action="validated" if approved else "returned",
        note=note.strip(),
    )


def _change_record_state(
    *,
    agravo: str,
    patient_ref: str,
    competence: str,
    actor: str,
    allowed_states: set[str],
    target_state: RecordState,
    action: str,
    unit_ref: str | None = None,
    note: str | None = None,
) -> MonthlyRecord:
    Competence.parse(competence)
    now = _now()
    with closing(_connect()) as connection:
        _initialize(connection)
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            """
            SELECT * FROM monthly_records
            WHERE agravo = ? AND patient_ref = ? AND competence = ?
            """,
            (agravo, patient_ref, competence),
        ).fetchone()
        if row is None:
            raise ValueError("Registro mensal não encontrado.")
        if unit_ref is not None and row["unit_ref"].casefold() != unit_ref.casefold():
            raise PermissionError("Registro fora da unidade vinculada.")
        if row["state"] not in allowed_states:
            raise ValueError("A situação atual não permite esta operação.")
        if target_state == "submitted":
            period = connection.execute(
                """
                SELECT state FROM monthly_competences
                WHERE agravo = ? AND competence = ?
                """,
                (agravo, competence),
            ).fetchone()
            if period is None or period["state"] != "open":
                raise ValueError("A competência não está aberta para envio.")
        elif target_state in {"validated", "returned"}:
            period = connection.execute(
                """
                SELECT state FROM monthly_competences
                WHERE agravo = ? AND competence = ?
                """,
                (agravo, competence),
            ).fetchone()
            if period is None or period["state"] != "open":
                raise ValueError("A competência encerrada não pode ser revisada.")

        version = row["version"] + 1
        connection.execute(
            """
            UPDATE monthly_records SET state = ?, version = ?, updated_by = ?,
                updated_at = ?, reviewer_note = COALESCE(?, reviewer_note)
            WHERE agravo = ? AND patient_ref = ? AND competence = ?
            """,
            (
                target_state,
                version,
                actor,
                now,
                note,
                agravo,
                patient_ref,
                competence,
            ),
        )
        connection.execute(
            """
            INSERT INTO monthly_record_revisions (
                agravo, patient_ref, competence, version, action, actor,
                occurred_at, original_values, updated_values, state, note
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                agravo,
                patient_ref,
                competence,
                version,
                action,
                actor,
                now,
                row["original_values"],
                row["updated_values"],
                target_state,
                note or "",
            ),
        )
        if action in {"validated", "returned"}:
            connection.execute(
                """
                INSERT INTO monthly_vigilance_notes (
                    agravo, patient_ref, competence, actor, occurred_at, action, note
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    agravo,
                    patient_ref,
                    competence,
                    actor,
                    now,
                    action,
                    note or "",
                ),
            )
        saved = connection.execute(
            """
            SELECT * FROM monthly_records
            WHERE agravo = ? AND patient_ref = ? AND competence = ?
            """,
            (agravo, patient_ref, competence),
        ).fetchone()
        connection.commit()
    return _record_from_row(saved)


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


def close_monthly_competence(
    *,
    agravo: str,
    competence: str,
    actor: str,
) -> None:
    Competence.parse(competence)
    if not actor.strip():
        raise ValueError("O usuário responsável é obrigatório.")
    with closing(_connect()) as connection:
        _initialize(connection)
        connection.execute("BEGIN IMMEDIATE")
        period = connection.execute(
            """
            SELECT state FROM monthly_competences
            WHERE agravo = ? AND competence = ?
            """,
            (agravo, competence),
        ).fetchone()
        if period is None or period["state"] != "open":
            raise ValueError("A competência não está aberta.")
        unvalidated = connection.execute(
            """
            SELECT 1 FROM monthly_records
            WHERE agravo = ? AND competence = ? AND state != 'validated' LIMIT 1
            """,
            (agravo, competence),
        ).fetchone()
        if unvalidated:
            raise ValueError("Há registros ainda não validados pela Vigilância.")
        now = _now()
        connection.execute(
            """
            UPDATE monthly_competences
            SET state = 'closed', closed_by = ?, closed_at = ?
            WHERE agravo = ? AND competence = ?
            """,
            (actor.strip(), now, agravo, competence),
        )
        connection.commit()


def get_monthly_competence_state(
    *,
    agravo: str,
    competence: str,
) -> str | None:
    Competence.parse(competence)
    with closing(_connect()) as connection:
        _initialize(connection)
        row = connection.execute(
            """
            SELECT state FROM monthly_competences
            WHERE agravo = ? AND competence = ?
            """,
            (agravo, competence),
        ).fetchone()
    return row["state"] if row else None


def get_record_revisions(
    *,
    agravo: str,
    patient_ref: str,
    competence: str,
) -> tuple[dict[str, object], ...]:
    Competence.parse(competence)
    with closing(_connect()) as connection:
        _initialize(connection)
        rows = connection.execute(
            """
            SELECT version, action, actor, occurred_at, original_values,
                updated_values, state, note
            FROM monthly_record_revisions
            WHERE agravo = ? AND patient_ref = ? AND competence = ?
            ORDER BY version
            """,
            (agravo, patient_ref, competence),
        ).fetchall()
    return tuple(
        {
            **dict(row),
            "original_values": json.loads(row["original_values"]),
            "updated_values": json.loads(row["updated_values"]),
        }
        for row in rows
    )


def get_monthly_vigilance_notes(
    *,
    agravo: str,
    patient_ref: str,
    competence: str,
) -> tuple[dict[str, str], ...]:
    Competence.parse(competence)
    with closing(_connect()) as connection:
        _initialize(connection)
        rows = connection.execute(
            """
            SELECT actor, occurred_at, action, note
            FROM monthly_vigilance_notes
            WHERE agravo = ? AND patient_ref = ? AND competence = ?
            ORDER BY id
            """,
            (agravo, patient_ref, competence),
        ).fetchall()
    return tuple(dict(row) for row in rows)


_FOLLOWUP_SELECT = """
        SELECT f.*,
            r.response_text, r.actor AS response_by,
            r.occurred_at AS response_at, r.version AS response_version
            , d.response_text AS draft_text
        FROM monthly_followups AS f
        LEFT JOIN monthly_followup_responses AS r
          ON r.followup_id = f.id AND r.state = 'submitted'
         AND r.version = (
            SELECT MAX(r2.version) FROM monthly_followup_responses AS r2
            WHERE r2.followup_id = f.id AND r2.state = 'submitted'
         )
    LEFT JOIN monthly_followup_responses AS d
          ON d.followup_id = f.id AND d.state = 'draft'
         AND d.version = (
            SELECT MAX(d2.version) FROM monthly_followup_responses AS d2
            WHERE d2.followup_id = f.id AND d2.state = 'draft'
         )
         AND d.version > COALESCE((
            SELECT MAX(s.version) FROM monthly_followup_responses AS s
            WHERE s.followup_id = f.id AND s.state = 'submitted'
         ), 0)
"""


def _followup_from_row(row: sqlite3.Row) -> MonthlyFollowup:
        return MonthlyFollowup(
            id=row["id"],
            agravo=row["agravo"],
            patient_ref=row["patient_ref"],
            unit_ref=row["unit_ref"],
            competence=row["competence"],
            field_key=row["field_key"],
            rule_id=row["rule_id"],
            automatic_text=row["automatic_text"],
            vigilance_text=row["vigilance_text"],
            state=row["state"],
            priority=row["priority"],
            created_by=row["created_by"],
            created_at=row["created_at"],
            updated_by=row["updated_by"],
            updated_at=row["updated_at"],
            response_text=row["response_text"] or "",
            draft_text=row["draft_text"] or "",
            response_by=row["response_by"],
            response_at=row["response_at"],
            response_version=row["response_version"] or 0,
        )


def _nonnegative_integer(value: object) -> int | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value if value >= 0 else None
        if isinstance(value, str) and value.strip().isdecimal():
            return int(value.strip())
        return None


def ensure_contact_followup(record: MonthlyRecord) -> MonthlyFollowup | None:
        registered = record.values.get("contatos_identificados")
        examined = record.values.get("contatos_examinados")
        registered_count = _nonnegative_integer(registered)
        examined_count = _nonnegative_integer(examined)
        if (
            registered_count is None
            or examined_count is None
            or registered_count <= examined_count
        ):
            return None

        text = (
            f"Constam {registered_count} contatos registrados/identificados e "
            f"{examined_count} examinados. Solicita-se informar a situação dos "
            "contatos ainda não examinados e as providências adotadas."
        )
        now = _now()
        with closing(_connect()) as connection:
            _initialize(connection)
            connection.execute("BEGIN IMMEDIATE")
            active = connection.execute(
                _FOLLOWUP_SELECT
                + """
                WHERE f.agravo = ? AND f.patient_ref = ?
                    AND f.rule_id = 'contacts_not_examined'
                    AND f.state != 'resolved'
                ORDER BY f.competence DESC LIMIT 1
                """,
                (record.agravo, record.patient_ref),
            ).fetchone()
            if active is not None:
                connection.commit()
                return _followup_from_row(active)
            inserted = connection.execute(
                """
                INSERT OR IGNORE INTO monthly_followups (
                    agravo, patient_ref, unit_ref, competence, rule_id,
                    field_key, automatic_text, vigilance_text, state, priority,
                    created_by, created_at, updated_by, updated_at
                ) VALUES (?, ?, ?, ?, 'contacts_not_examined', 'contatos_examinados',
                    ?, ?, 'automatic_suggestion',
                    'normal', 'system', ?, 'system', ?)
                """,
                (
                    record.agravo,
                    record.patient_ref,
                    record.unit_ref,
                    record.competence,
                    text,
                    text,
                    now,
                    now,
                ),
            )
            if inserted.rowcount:
                followup_id = inserted.lastrowid
                connection.execute(
                    """
                    INSERT INTO monthly_followup_events (
                        followup_id, actor, occurred_at, action, old_state, new_state,
                        old_text, new_text, priority
                    ) VALUES (?, 'system', ?, 'automatic_suggestion_created',
                        NULL, 'automatic_suggestion', '', ?, 'normal')
                    """,
                    (followup_id, now, text),
                )
            row = connection.execute(
                _FOLLOWUP_SELECT
                + """
                WHERE f.agravo = ? AND f.patient_ref = ? AND f.competence = ?
                    AND f.rule_id = 'contacts_not_examined'
                """,
                (record.agravo, record.patient_ref, record.competence),
            ).fetchone()
            connection.commit()
        return _followup_from_row(row)


def create_manual_followup(
        *,
        agravo: str,
        patient_ref: str,
        competence: str,
        unit_ref: str,
        actor: str,
        text: str,
        field_key: str = "",
        priority: str = "normal",
) -> MonthlyFollowup:
        if agravo not in {"tuberculose", "hanseniase"}:
            raise ValueError("Agravo inválido.")
        Competence.parse(competence)
        if not text.strip() or len(text) > 2000:
            raise ValueError("A observação deve conter até 2000 caracteres.")
        editable_fields = {
            field.key for field in BULLETIN_FIELDS[agravo] if field.monthly_editable
        }
        if field_key and field_key not in editable_fields:
            raise ValueError("O campo não pode ser vinculado a esta observação.")
        if priority not in {"low", "normal", "high"}:
            raise ValueError("Prioridade inválida.")
        now = _now()
        with closing(_connect()) as connection:
            _initialize(connection)
            connection.execute("BEGIN IMMEDIATE")
            record = connection.execute(
                """
                SELECT unit_ref FROM monthly_records
                WHERE agravo = ? AND patient_ref = ? AND competence = ?
                """,
                (agravo, patient_ref, competence),
            ).fetchone()
            if record is None:
                raise ValueError("Registro mensal não encontrado.")
            if record["unit_ref"].casefold() != unit_ref.casefold():
                raise PermissionError("Registro fora da unidade vinculada.")
            cursor = connection.execute(
                """
                INSERT INTO monthly_followups (
                    agravo, patient_ref, unit_ref, competence, rule_id,
                    field_key, automatic_text, vigilance_text, state, priority,
                    created_by, created_at, updated_by, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, '', ?, 'awaiting_unit', ?, ?, ?, ?, ?)
                """,
                (
                    agravo,
                    patient_ref,
                    unit_ref,
                    competence,
                    f"manual:{secrets.token_hex(12)}",
                    field_key,
                    text.strip(),
                    priority,
                    actor,
                    now,
                    actor,
                    now,
                ),
            )
            followup_id = cursor.lastrowid
            connection.execute(
                """
                INSERT INTO monthly_followup_events (
                    followup_id, actor, occurred_at, action, old_state, new_state,
                    old_text, new_text, priority
                ) VALUES (?, ?, ?, 'created_manual', NULL, 'awaiting_unit', '', ?, ?)
                """,
                (followup_id, actor, now, text.strip(), priority),
            )
            row = connection.execute(
                _FOLLOWUP_SELECT + " WHERE f.id = ?", (followup_id,)
            ).fetchone()
            connection.commit()
        return _followup_from_row(row)


def list_monthly_followups(
        *,
        agravo: str | None = None,
        competence: str | None = None,
        unit_ref: str | None = None,
        states: set[str] | None = None,
        include_automatic: bool = True,
) -> tuple[MonthlyFollowup, ...]:
        if competence is not None:
            Competence.parse(competence)
        with closing(_connect()) as connection:
            _initialize(connection)
            query = _FOLLOWUP_SELECT + " WHERE 1 = 1"
            params: list[str] = []
            if agravo is not None:
                query += " AND f.agravo = ?"
                params.append(agravo)
            if competence is not None:
                query += " AND f.competence = ?"
                params.append(competence)
            if unit_ref is not None:
                query += " AND f.unit_ref = ?"
                params.append(unit_ref)
            if not include_automatic:
                query += " AND f.state != 'automatic_suggestion'"
            if states:
                placeholders = ",".join("?" for _ in states)
                query += f" AND f.state IN ({placeholders})"
                params.extend(sorted(states))
            query += " ORDER BY f.competence, f.unit_ref, f.patient_ref, f.id"
            rows = connection.execute(query, params).fetchall()
        return tuple(_followup_from_row(row) for row in rows)


def get_monthly_followup(
        *,
        followup_id: int,
        unit_ref: str | None = None,
) -> MonthlyFollowup | None:
        with closing(_connect()) as connection:
            _initialize(connection)
            query = _FOLLOWUP_SELECT + " WHERE f.id = ?"
            params: list[object] = [followup_id]
            if unit_ref is not None:
                query += " AND f.unit_ref = ?"
                params.append(unit_ref)
                query += " AND f.state != 'automatic_suggestion'"
            row = connection.execute(query, params).fetchone()
        return _followup_from_row(row) if row else None


def review_monthly_followup(
        *,
        followup_id: int,
        actor: str,
        action: str,
        text: str,
        priority: str = "normal",
) -> MonthlyFollowup:
        transitions = {
            "send": ("automatic_suggestion", "awaiting_unit"),
            "request_more_info": ("responded", "needs_more_info"),
            "start_review": ("responded", "under_review"),
            "resolve": ("responded", "resolved"),
            "finish_review": ("under_review", "resolved"),
            "reopen": ("resolved", "awaiting_unit"),
        }
        if action not in transitions and action != "save_note":
            raise ValueError("Ação de revisão inválida.")
        if not text.strip() or len(text) > 2000:
            raise ValueError("A observação deve conter até 2000 caracteres.")
        if priority not in {"low", "normal", "high"}:
            raise ValueError("Prioridade inválida.")
        now = _now()
        with closing(_connect()) as connection:
            _initialize(connection)
            connection.execute("BEGIN IMMEDIATE")
            now = _followup_timestamp(connection, followup_id)
            row = connection.execute(
                "SELECT * FROM monthly_followups WHERE id = ?", (followup_id,)
            ).fetchone()
            if row is None:
                raise ValueError("Pendência não encontrada.")
            if action == "save_note":
                if row["state"] == "resolved":
                    raise ValueError("A comunicação concluída não aceita novas observações.")
                allowed_state = row["state"]
                target_state = row["state"]
            else:
                allowed_state, target_state = transitions[action]
                if row["state"] != allowed_state:
                    raise ValueError("A situação atual não permite esta operação.")
            connection.execute(
                """
                UPDATE monthly_followups SET vigilance_text = ?, state = ?,
                    priority = ?, updated_by = ?, updated_at = ?
                WHERE id = ?
                """,
                (text.strip(), target_state, priority, actor, now, followup_id),
            )
            connection.execute(
                """
                INSERT INTO monthly_followup_events (
                    followup_id, actor, occurred_at, action, old_state, new_state,
                    old_text, new_text, priority
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    followup_id,
                    actor,
                    now,
                    action,
                    row["state"],
                    target_state,
                    row["vigilance_text"],
                    text.strip(),
                    priority,
                ),
            )
            result = connection.execute(
                _FOLLOWUP_SELECT + " WHERE f.id = ?", (followup_id,)
            ).fetchone()
            connection.commit()
        return _followup_from_row(result)


def save_monthly_followup_response(
        *,
        followup_id: int,
        unit_ref: str,
        actor: str,
        text: str,
        submit: bool,
) -> MonthlyFollowup:
        if len(text) > 4000:
            raise ValueError("A resposta deve ter no máximo 4000 caracteres.")
        if submit and not text.strip():
            raise ValueError("Informe uma resposta antes de enviar.")
        now = _now()
        with closing(_connect()) as connection:
            _initialize(connection)
            connection.execute("BEGIN IMMEDIATE")
            now = _followup_timestamp(connection, followup_id)
            row = connection.execute(
                "SELECT * FROM monthly_followups WHERE id = ? AND unit_ref = ?",
                (followup_id, unit_ref),
            ).fetchone()
            if row is None:
                raise PermissionError("Pendência não encontrada nesta unidade.")
            if row["state"] not in {"awaiting_unit", "needs_more_info", "responded"}:
                raise ValueError("Esta pendência não aceita resposta da unidade.")
            latest_version = connection.execute(
                "SELECT MAX(version) FROM monthly_followup_responses WHERE followup_id = ?",
                (followup_id,),
            ).fetchone()[0] or 0
            version = latest_version + 1
            response_state = "submitted" if submit else "draft"
            connection.execute(
                """
                INSERT INTO monthly_followup_responses (
                    followup_id, version, actor, occurred_at, state, response_text
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (followup_id, version, actor, now, response_state, text.strip()),
            )
            if submit:
                old_state = row["state"]
                connection.execute(
                    """
                    UPDATE monthly_followups SET state = 'responded',
                        updated_by = ?, updated_at = ? WHERE id = ?
                    """,
                    (actor, now, followup_id),
                )
                connection.execute(
                    """
                    INSERT INTO monthly_followup_events (
                        followup_id, actor, occurred_at, action, old_state, new_state,
                        old_text, new_text, priority
                    ) VALUES (?, ?, ?, 'unit_submitted', ?, 'responded', ?, ?, ?)
                    """,
                    (
                        followup_id,
                        actor,
                        now,
                        old_state,
                        row["vigilance_text"],
                        text.strip(),
                        row["priority"],
                    ),
                )
            result = connection.execute(
                _FOLLOWUP_SELECT + " WHERE f.id = ?", (followup_id,)
            ).fetchone()
            connection.commit()
        return _followup_from_row(result)


def get_monthly_followup_history(followup_id: int) -> tuple[dict[str, object], ...]:
        with closing(_connect()) as connection:
            _initialize(connection)
            rows = connection.execute(
                """
                SELECT occurred_at, actor, label, old_state, new_state, text,
                    sequence, kind FROM (
                    SELECT occurred_at, actor, action AS label, old_state, new_state,
                        new_text AS text, id AS sequence, 'event' AS kind, 0 AS sort_order
                    FROM monthly_followup_events WHERE followup_id = ?
                    UNION ALL
                    SELECT occurred_at, actor, state AS label, NULL AS old_state,
                        NULL AS new_state, response_text AS text, id AS sequence,
                        'response' AS kind, 1 AS sort_order
                    FROM monthly_followup_responses WHERE followup_id = ?
                ) ORDER BY occurred_at, sort_order, sequence
                """,
                (followup_id, followup_id),
            ).fetchall()
        return tuple(dict(row) for row in rows)


def monthly_followup_metrics(
    *,
    agravo: str | None = None,
    competence: str | None = None,
    unit_ref: str | None = None,
    state: str | None = None,
    include_automatic: bool = True,
) -> dict[str, object]:
        if competence is not None:
            Competence.parse(competence)
        conditions: list[str] = []
        params: list[str] = []
        for column, value in (
            ("f.agravo", agravo),
            ("f.competence", competence),
            ("f.unit_ref", unit_ref),
            ("f.state", state),
        ):
            if value is not None:
                conditions.append(f"{column} = ?")
                params.append(value)
        if not include_automatic:
            conditions.append("f.state != 'automatic_suggestion'")
        where = " AND ".join(conditions) or "1 = 1"
        with closing(_connect()) as connection:
            _initialize(connection)
            rows = connection.execute(
                f"""
                SELECT f.agravo, f.unit_ref, f.competence, f.state, COUNT(*) AS count
                FROM monthly_followups AS f WHERE {where}
                GROUP BY f.agravo, f.unit_ref, f.competence, f.state
                """,
                params,
            ).fetchall()
            response_counts = connection.execute(
                f"""
                SELECT COUNT(*) AS submitted_count
                FROM monthly_followup_responses AS r
                JOIN monthly_followups AS f ON f.id = r.followup_id
                WHERE r.state = 'submitted' AND {where}
                """,
                params,
            ).fetchone()
            average = connection.execute(
                f"""
                SELECT AVG(
                    (julianday(r.occurred_at) - julianday((
                        SELECT MAX(e.occurred_at)
                        FROM monthly_followup_events AS e
                        WHERE e.followup_id = r.followup_id
                          AND e.action IN ('send', 'request_more_info', 'reopen')
                          AND e.occurred_at <= r.occurred_at
                    ))) * 86400
                ) AS seconds
                FROM monthly_followup_responses AS r
                JOIN monthly_followups AS f ON f.id = r.followup_id
                WHERE r.state = 'submitted' AND {where}
                  AND NOT EXISTS (
                    SELECT 1 FROM monthly_followup_responses AS earlier
                    WHERE earlier.followup_id = r.followup_id
                      AND earlier.state = 'submitted'
                      AND earlier.occurred_at < r.occurred_at
                      AND earlier.occurred_at > (
                        SELECT MAX(e.occurred_at)
                        FROM monthly_followup_events AS e
                        WHERE e.followup_id = r.followup_id
                          AND e.action IN ('send', 'request_more_info', 'reopen')
                          AND e.occurred_at <= r.occurred_at
                      )
                  )
                """,
                params,
            ).fetchone()["seconds"]

        by_state: dict[str, int] = {}
        by_unit: dict[str, int] = {}
        by_agravo: dict[str, int] = {}
        by_competence: dict[str, int] = {}
        for row in rows:
            count = row["count"]
            by_state[row["state"]] = by_state.get(row["state"], 0) + count
            by_unit[row["unit_ref"]] = by_unit.get(row["unit_ref"], 0) + count
            by_agravo[row["agravo"]] = by_agravo.get(row["agravo"], 0) + count
            by_competence[row["competence"]] = (
                by_competence.get(row["competence"], 0) + count
            )
        return {
            "total": sum(by_state.values()),
            "por_situacao": by_state,
            "por_unidade": by_unit,
            "por_agravo": by_agravo,
            "por_competencia": by_competence,
            "respostas_enviadas": response_counts["submitted_count"],
            "tempo_medio_resposta_segundos": average,
        }


def set_monthly_monitoring_deadline(
    *,
    agravo: str,
    competence: str,
    opened_on: str,
    due_on: str,
    extension_due_on: str | None,
    actor: str,
) -> dict[str, str | None]:
        if agravo not in {"tuberculose", "hanseniase"}:
            raise ValueError("Agravo inválido.")
        Competence.parse(competence)
        try:
            opened = date.fromisoformat(opened_on)
            due = date.fromisoformat(due_on)
            extension = (
                date.fromisoformat(extension_due_on)
                if extension_due_on else None
            )
        except ValueError as error:
            raise ValueError("Informe datas válidas no formato AAAA-MM-DD.") from error
        if due < opened or (extension is not None and extension < due):
            raise ValueError("O prazo final deve ser após a abertura e a prorrogação não pode antecipá-lo.")
        now = _now()
        with closing(_connect()) as connection:
            _initialize(connection)
            connection.execute("BEGIN IMMEDIATE")
            old = connection.execute(
                """
                SELECT opened_on, due_on, extension_due_on
                FROM monthly_monitoring_deadlines
                WHERE agravo = ? AND competence = ?
                """,
                (agravo, competence),
            ).fetchone()
            old_values = dict(old) if old else {}
            new_values = {
                "opened_on": opened_on,
                "due_on": due_on,
                "extension_due_on": extension_due_on,
            }
            connection.execute(
                """
                INSERT INTO monthly_monitoring_deadlines (
                    agravo, competence, opened_on, due_on, extension_due_on,
                    updated_by, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (agravo, competence) DO UPDATE SET
                    opened_on = excluded.opened_on,
                    due_on = excluded.due_on,
                    extension_due_on = excluded.extension_due_on,
                    updated_by = excluded.updated_by,
                    updated_at = excluded.updated_at
                """,
                (
                    agravo, competence, opened_on, due_on, extension_due_on,
                    actor, now,
                ),
            )
            connection.execute(
                """
                INSERT INTO monthly_monitoring_deadline_events (
                    agravo, competence, actor, occurred_at, action,
                    old_values, new_values
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    agravo, competence, actor, now,
                    "created" if old is None else "updated",
                    _json(old_values), _json(new_values),
                ),
            )
            connection.commit()
        return new_values


def get_monthly_monitoring_deadline(
    *,
    agravo: str,
    competence: str,
) -> dict[str, str | None] | None:
        Competence.parse(competence)
        with closing(_connect()) as connection:
            _initialize(connection)
            row = connection.execute(
                """
                SELECT agravo, competence, opened_on, due_on, extension_due_on,
                    updated_by, updated_at
                FROM monthly_monitoring_deadlines
                WHERE agravo = ? AND competence = ?
                """,
                (agravo, competence),
            ).fetchone()
        return dict(row) if row else None


def list_monthly_units(agravo: str) -> tuple[str, ...]:
        if agravo not in {"tuberculose", "hanseniase"}:
            raise ValueError("Agravo inválido.")
        with closing(_connect()) as connection:
            _initialize(connection)
            rows = connection.execute(
                """
                SELECT DISTINCT unit_ref FROM monthly_records
                WHERE agravo = ? ORDER BY unit_ref
                """,
                (agravo,),
            ).fetchall()
        return tuple(row["unit_ref"] for row in rows)


def monthly_unit_monitoring(
    *,
    agravo: str,
    competence: str,
    units: tuple[str, ...],
    as_of: date | None = None,
) -> tuple[dict[str, object], ...]:
        if agravo not in {"tuberculose", "hanseniase"}:
            raise ValueError("Agravo inválido.")
        parsed_competence = Competence.parse(competence)
        today = as_of or date.today()
        previous_competence = str(parsed_competence.previous())
        with closing(_connect()) as connection:
            _initialize(connection)
            imported = connection.execute(
                """
                SELECT 1 FROM monthly_imports
                WHERE agravo = ? AND competence = ? LIMIT 1
                """,
                (agravo, competence),
            ).fetchone() is not None
            conflicts = connection.execute(
                """
                SELECT COUNT(*) AS conflicts
                FROM monthly_import_conflicts
                WHERE agravo = ? AND competence = ?
                """,
                (agravo, competence),
            ).fetchone()["conflicts"]
            deadline = connection.execute(
                """
                SELECT opened_on, due_on, extension_due_on
                FROM monthly_monitoring_deadlines
                WHERE agravo = ? AND competence = ?
                """,
                (agravo, competence),
            ).fetchone()
            outputs: list[dict[str, object]] = []
            for unit_ref in units:
                covered = connection.execute(
                    """
                    SELECT 1
                    FROM monthly_imports AS i
                    JOIN monthly_import_unit_coverage AS c
                      ON c.import_id = i.id
                    WHERE i.agravo = ? AND i.competence = ? AND c.unit_ref = ?
                    LIMIT 1
                    """,
                    (agravo, competence, unit_ref),
                ).fetchone() is not None
                records = connection.execute(
                    """
                    SELECT patient_ref, state, updated_by, updated_at
                    FROM monthly_records
                    WHERE agravo = ? AND competence = ? AND unit_ref = ?
                    """,
                    (agravo, competence, unit_ref),
                ).fetchall()
                current_refs = {row["patient_ref"] for row in records}
                previous_records = connection.execute(
                    """
                    SELECT patient_ref, state FROM monthly_records
                    WHERE agravo = ? AND competence = ? AND unit_ref = ?
                    """,
                    (agravo, previous_competence, unit_ref),
                ).fetchall()
                previous_refs = {row["patient_ref"] for row in previous_records}
                confirmation_row = connection.execute(
                    """
                    SELECT status, note, updated_by, updated_role, updated_at
                    FROM monthly_unit_confirmations
                    WHERE agravo = ? AND competence = ? AND unit_ref = ?
                    """,
                    (agravo, competence, unit_ref),
                ).fetchone()
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


def update_monthly_unit_confirmation(
    *,
    agravo: str,
    competence: str,
    unit_ref: str,
    actor: str,
    actor_role: str,
    action: str,
    note: str = "",
) -> dict[str, object]:
        if agravo not in {"tuberculose", "hanseniase"}:
            raise ValueError("Agravo inválido.")
        Competence.parse(competence)
        if actor_role == "unit" and action not in {
            "confirm_absence", "report_missing_patients", "request_review",
        }:
            raise ValueError("Ação não permitida para a unidade.")
        if actor_role == "surveillance" and action not in {
            "request_confirmation", "confirm_absence", "resolve_reconciliation",
        }:
            raise ValueError("Ação não permitida para a Vigilância.")
        if actor_role not in {"unit", "surveillance"}:
            raise ValueError("Perfil sem permissão para confirmar ausência.")
        if len(note) > 2000:
            raise ValueError("A observação deve conter até 2000 caracteres.")
        if action in {"report_missing_patients", "request_review", "resolve_reconciliation"} and not note.strip():
            raise ValueError("Descreva a divergência ou a conferência realizada.")
        statuses = {
            "request_confirmation": "awaiting_confirmation",
            "confirm_absence": "confirmed_absent",
            "report_missing_patients": "patients_missing",
            "request_review": "review_requested",
            "resolve_reconciliation": "confirmed_absent",
        }
        status = statuses[action]
        now = _now()
        with closing(_connect()) as connection:
            _initialize(connection)
            current_record_count = connection.execute(
                """
                SELECT COUNT(*) FROM monthly_records
                WHERE agravo = ? AND competence = ? AND unit_ref = ?
                """,
                (agravo, competence, unit_ref),
            ).fetchone()[0]
            imported = connection.execute(
                """
                SELECT 1
                FROM monthly_imports AS i
                JOIN monthly_import_unit_coverage AS c ON c.import_id = i.id
                WHERE i.agravo = ? AND i.competence = ? AND c.unit_ref = ?
                LIMIT 1
                """,
                (agravo, competence, unit_ref),
            ).fetchone()
            conflicts = connection.execute(
                """
                SELECT 1 FROM monthly_import_conflicts
                WHERE agravo = ? AND competence = ? LIMIT 1
                """,
                (agravo, competence),
            ).fetchone()
            if not imported or conflicts or current_record_count:
                raise ValueError("A confirmação só está disponível para unidade sem pacientes em boletim importado.")
            if actor_role == "unit" and action == "confirm_absence":
                previous_competence = str(Competence.parse(competence).previous())
                missing_previous = connection.execute(
                    """
                    SELECT COUNT(*) FROM monthly_records
                    WHERE agravo = ? AND competence = ? AND unit_ref = ?
                    """,
                    (agravo, previous_competence, unit_ref),
                ).fetchone()[0]
                if missing_previous:
                    raise ValueError(
                        "Há pacientes no histórico anterior sem registro atual; solicite conferência antes de confirmar."
                    )
            if actor_role == "surveillance" and action == "confirm_absence":
                previous_competence = str(Competence.parse(competence).previous())
                missing_previous = connection.execute(
                    """
                    SELECT COUNT(*) FROM monthly_records
                    WHERE agravo = ? AND competence = ? AND unit_ref = ?
                    """,
                    (agravo, previous_competence, unit_ref),
                ).fetchone()[0]
                if missing_previous and not note.strip():
                    raise ValueError(
                        "Registre a conferência dos pacientes do mês anterior antes de confirmar a ausência."
                    )
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                """
                SELECT status FROM monthly_unit_confirmations
                WHERE agravo = ? AND competence = ? AND unit_ref = ?
                """,
                (agravo, competence, unit_ref),
            ).fetchone()
            old_status = existing["status"] if existing else None
            connection.execute(
                """
                INSERT INTO monthly_unit_confirmations (
                    agravo, competence, unit_ref, status, note,
                    updated_by, updated_role, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (agravo, competence, unit_ref) DO UPDATE SET
                    status = excluded.status,
                    note = excluded.note,
                    updated_by = excluded.updated_by,
                    updated_role = excluded.updated_role,
                    updated_at = excluded.updated_at
                """,
                (agravo, competence, unit_ref, status, note.strip(), actor, actor_role, now),
            )
            connection.execute(
                """
                INSERT INTO monthly_unit_confirmation_events (
                    agravo, competence, unit_ref, actor, actor_role, occurred_at,
                    action, old_status, new_status, note
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    agravo, competence, unit_ref, actor, actor_role, now,
                    action, old_status, status, note.strip(),
                ),
            )
            connection.commit()
        return {
            "agravo": agravo,
            "competence": competence,
            "unit_ref": unit_ref,
            "status": status,
            "note": note.strip(),
            "updated_by": actor,
            "updated_role": actor_role,
            "updated_at": now,
        }


def get_monthly_unit_confirmation_history(
    *,
    agravo: str,
    competence: str,
    unit_ref: str,
) -> tuple[dict[str, object], ...]:
        Competence.parse(competence)
        with closing(_connect()) as connection:
            _initialize(connection)
            rows = connection.execute(
                """
                SELECT actor, actor_role, occurred_at, action, old_status,
                    new_status, note
                FROM monthly_unit_confirmation_events
                WHERE agravo = ? AND competence = ? AND unit_ref = ?
                ORDER BY occurred_at, id
                """,
                (agravo, competence, unit_ref),
            ).fetchall()
        return tuple(dict(row) for row in rows)
