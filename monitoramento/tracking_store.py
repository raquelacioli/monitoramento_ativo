from dataclasses import replace
from datetime import date

from monitoramento.data import ModuleDemo, PatientDemo
from monitoramento.firestore_store import get_store, key, snapshot_read

MAX_OBSERVATION_LENGTH = 1000
MAX_PENDING_LENGTH = 250
FOLLOWUP_STATUSES = (
    "Em acompanhamento",
    "Acompanhamento pendente",
    "Sinalização para revisão",
)


@snapshot_read
def load_module_updates(module: ModuleDemo) -> ModuleDemo:
    rows = get_store().query('tracking_updates', [('agravo', '==', module.key)])

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
            form_values=tuple(update["form_values"].items()),
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

    data = dict(agravo=agravo, record_id=record_id, followup_status=followup_status,
                contacts_registered=contacts_registered, contacts_examined=contacts_examined,
                pending_items=pending_items.strip(), observation=observation.strip(),
                form_values=form_values, last_updated=date.today().isoformat())
    get_store().run(lambda tx: tx.set('tracking_updates', key(agravo, record_id), data),
                    guard='tracking')


@snapshot_read
def load_all_modules(modules: dict[str, ModuleDemo]) -> dict[str, ModuleDemo]:
    return {
        key: load_module_updates(module)
        for key, module in modules.items()
    }
