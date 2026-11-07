import json
import os
import sqlite3
from contextlib import closing
from dataclasses import replace
from datetime import date
from pathlib import Path

from monitoramento.data import ModuleDemo, PatientDemo

MAX_OBSERVATION_LENGTH = 1000
MAX_PENDING_LENGTH = 250
FOLLOWUP_STATUSES = (
    "Em acompanhamento",
    "Acompanhamento pendente",
    "Sinalização para revisão",
)


def _database_path() -> Path:
    configured_path = os.environ.get("MONITORAMENTO_DB_PATH")
    if configured_path:
        return Path(configured_path)
    return Path(__file__).resolve().parent.parent / "instance" / "monitoramento.sqlite3"


def database_path() -> Path:
    return _database_path()


def _connect() -> sqlite3.Connection:
    database_path = _database_path()
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path, timeout=5)
    connection.row_factory = sqlite3.Row
    return connection


def _initialize(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS tracking_updates (
            agravo TEXT NOT NULL,
            record_id TEXT NOT NULL,
            followup_status TEXT NOT NULL,
            contacts_registered INTEGER NOT NULL,
            contacts_examined INTEGER NOT NULL,
            pending_items TEXT NOT NULL,
            observation TEXT NOT NULL,
            last_updated TEXT NOT NULL,
            PRIMARY KEY (agravo, record_id)
        )
        """
    )
    columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(tracking_updates)").fetchall()
    }
    if "form_values" not in columns:
        connection.execute(
            "ALTER TABLE tracking_updates ADD COLUMN form_values TEXT NOT NULL DEFAULT '{}'"
        )


def load_module_updates(module: ModuleDemo) -> ModuleDemo:
    with closing(_connect()) as connection:
        _initialize(connection)
        rows = connection.execute(
            "SELECT * FROM tracking_updates WHERE agravo = ?",
            (module.key,),
        ).fetchall()
        connection.commit()

    updates = {row["record_id"]: row for row in rows}

    def apply_update(patient: PatientDemo) -> PatientDemo:
        update = updates[patient.identifier]
        status = update["followup_status"]
        note = {
            "Em acompanhamento": "Sem sinalização automática demonstrativa.",
            "Acompanhamento pendente": "Verificar pendência demonstrativa.",
            "Sinalização para revisão": (
                "Sinalização para revisão humana; não representa diagnóstico."
            ),
        }[status]
        return replace(
            patient,
            followup_status=status,
            contacts_registered=update["contacts_registered"],
            contacts_examined=update["contacts_examined"],
            pending_items=update["pending_items"],
            observation=update["observation"],
            form_values=tuple(json.loads(update["form_values"]).items()),
            last_updated=date.fromisoformat(update["last_updated"]),
            automatic_note=note,
            review_signal_demo=status == "Sinalização para revisão",
        )

    patients = tuple(
        apply_update(patient)
        if patient.identifier in updates
        else patient
        for patient in module.patients
    )
    return replace(module, patients=patients)


def save_tracking_update(
    *,
    agravo: str,
    record_id: str,
    followup_status: str,
    contacts_registered: int,
    contacts_examined: int,
    pending_items: str,
    observation: str,
    form_values: dict[str, str],
) -> None:
    if followup_status not in FOLLOWUP_STATUSES:
        raise ValueError("Selecione uma situação de acompanhamento válida.")
    if contacts_registered < 0 or contacts_examined < 0:
        raise ValueError("A quantidade de contatos não pode ser negativa.")
    if contacts_examined > contacts_registered:
        raise ValueError("Contatos examinados não podem superar os contatos registrados.")
    if len(pending_items) > MAX_PENDING_LENGTH:
        raise ValueError(f"Pendências devem ter no máximo {MAX_PENDING_LENGTH} caracteres.")
    if len(observation) > MAX_OBSERVATION_LENGTH:
        raise ValueError(
            f"Observações devem ter no máximo {MAX_OBSERVATION_LENGTH} caracteres."
        )

    with closing(_connect()) as connection:
        _initialize(connection)
        connection.execute(
            """
            INSERT INTO tracking_updates (
                agravo, record_id, followup_status, contacts_registered,
                contacts_examined, pending_items, observation, form_values, last_updated
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(agravo, record_id) DO UPDATE SET
                followup_status = excluded.followup_status,
                contacts_registered = excluded.contacts_registered,
                contacts_examined = excluded.contacts_examined,
                pending_items = excluded.pending_items,
                observation = excluded.observation,
                form_values = excluded.form_values,
                last_updated = excluded.last_updated
            """,
            (
                agravo,
                record_id,
                followup_status,
                contacts_registered,
                contacts_examined,
                pending_items.strip(),
                observation.strip(),
                json.dumps(form_values, ensure_ascii=False),
                date.today().isoformat(),
            ),
        )
        connection.commit()


def load_all_modules(modules: dict[str, ModuleDemo]) -> dict[str, ModuleDemo]:
    return {
        key: load_module_updates(module)
        for key, module in modules.items()
    }
