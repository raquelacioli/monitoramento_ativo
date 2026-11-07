from dataclasses import dataclass
from typing import Literal

from monitoramento.data import MODULES, ModuleDemo, PatientDemo
from monitoramento.tracking_store import load_all_modules


@dataclass(frozen=True)
class AlertDemo:
    level: Literal["vermelho", "amarelo", "verde"]
    patient: PatientDemo
    reason: str
    suggested_action: str


def module_alerts(module: ModuleDemo) -> tuple[AlertDemo, ...]:
    alerts: list[AlertDemo] = []
    for patient in module.patients:
        if patient.followup_status == "Acompanhamento pendente":
            alerts.append(
                AlertDemo(
                    "amarelo",
                    patient,
                    "Pendência de acompanhamento fictícia",
                    "Conferir a informação com a unidade responsável.",
                )
            )
        elif patient.review_signal_demo:
            alerts.append(
                AlertDemo(
                    "amarelo",
                    patient,
                    "Sinalização fictícia que requer revisão humana",
                    "Avaliar o registro; não aplicar classificação clínica automática.",
                )
            )
        elif patient.pending_items.startswith("Nenhuma"):
            alerts.append(
                AlertDemo(
                    "verde",
                    patient,
                    "Sem pendências fictícias identificadas",
                    "Manter acompanhamento conforme rotina da equipe.",
                )
            )
    return tuple(alerts)


def all_patients() -> tuple[tuple[ModuleDemo, PatientDemo], ...]:
    modules = load_all_modules(MODULES)
    return tuple(
        (module, patient)
        for module in modules.values()
        for patient in module.patients
    )


def unit_summary() -> tuple[dict[str, int | str], ...]:
    summaries: dict[tuple[str, str], dict[str, int | str]] = {}
    for module, patient in all_patients():
        key = (patient.district, patient.unit)
        summary = summaries.setdefault(
            key,
            {
                "district": patient.district,
                "unit": patient.unit,
                "tuberculose": 0,
                "hanseniase": 0,
                "pending": 0,
                "review": 0,
                "contacts_pending": 0,
                "updated": 1,
            },
        )
        summary[module.key] = int(summary[module.key]) + 1
        summary["pending"] = int(summary["pending"]) + int(
            patient.followup_status == "Acompanhamento pendente"
        )
        summary["review"] = int(summary["review"]) + int(patient.review_signal_demo)
        summary["contacts_pending"] = int(summary["contacts_pending"]) + (
            patient.contacts_registered - patient.contacts_examined
        )
        if patient.unit in module.units_without_monthly_update:
            summary["updated"] = 0
    return tuple(summaries.values())


def monthly_comparison_demo(module: ModuleDemo) -> dict[str, int | str]:
    new_count = sum(patient.new_this_month_demo for patient in module.patients)
    return {
        "previous": "Outubro/2026",
        "current": "Novembro/2026",
        "maintained": len(module.patients) - new_count,
        "new": new_count,
        "absent_needs_verification": 1,
    }


def monthly_updates_missing() -> tuple[tuple[str, str, str], ...]:
    modules = load_all_modules(MODULES)
    return tuple(
        (module.name, patient.district, unit)
        for module in modules.values()
        for unit in module.units_without_monthly_update
        for patient in (
            next(patient for patient in module.patients if patient.unit == unit),
        )
    )
