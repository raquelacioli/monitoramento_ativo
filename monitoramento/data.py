from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class PatientDemo:
    identifier: str
    unit: str
    district: str
    treatment_start: date
    expected_end: date
    followup_status: str
    contacts_registered: int
    contacts_examined: int
    pending_items: str
    observation: str
    ending_soon_demo: bool = False
    review_signal_demo: bool = False
    new_this_month_demo: bool = False
    month_reference: str = "Novembro/2026"
    last_updated: date = date(2026, 11, 1)
    automatic_note: str = "Sem sinalização automática demonstrativa."
    form_values: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class ModuleDemo:
    key: str
    name: str
    accent: str
    patients: tuple[PatientDemo, ...]
    units_without_monthly_update: tuple[str, ...]


def _patient(
    identifier: str,
    unit: str,
    district: str,
    start_days_ago: int,
    end_days_from_today: int,
    followup_status: str,
    contacts_registered: int,
    contacts_examined: int,
    pending_items: str,
    observation: str,
    *,
    ending_soon_demo: bool = False,
    review_signal_demo: bool = False,
    new_this_month_demo: bool = False,
) -> PatientDemo:
    today = date.today()
    return PatientDemo(
        identifier=identifier,
        unit=unit,
        district=district,
        treatment_start=today - timedelta(days=start_days_ago),
        expected_end=today + timedelta(days=end_days_from_today),
        followup_status=followup_status,
        contacts_registered=contacts_registered,
        contacts_examined=contacts_examined,
        pending_items=pending_items,
        observation=observation,
        ending_soon_demo=ending_soon_demo,
        review_signal_demo=review_signal_demo,
        new_this_month_demo=new_this_month_demo,
        automatic_note=(
            "Verificar pendência demonstrativa."
            if followup_status == "Acompanhamento pendente"
            else (
                "Sinalização para revisão humana; não representa diagnóstico."
                if review_signal_demo
                else "Sem sinalização automática demonstrativa."
            )
        ),
    )


MODULES: dict[str, ModuleDemo] = {
    "tuberculose": ModuleDemo(
        key="tuberculose",
        name="Tuberculose",
        accent="blue",
        patients=(
            _patient(
                "DEMO-TB-001",
                "Unidade de Saúde de Vera (demonstração)",
                "Distrito Demonstrativo de Vera",
                110, 14, "Em acompanhamento", 3, 2, "1 contato a examinar",
                "Registro fictício para demonstração.", ending_soon_demo=True,
                new_this_month_demo=True,
            ),
            _patient(
                "DEMO-TB-002",
                "Unidade de Saúde de Vera (demonstração)",
                "Distrito Demonstrativo de Vera",
                68, 96, "Acompanhamento pendente", 2, 1, "Retorno demonstrativo pendente",
                "Conferir registro fictício na próxima revisão.",
            ),
            _patient(
                "DEMO-TB-003", "Unidade Demonstrativa Norte", "Distrito Beta",
                145, 52, "Sinalização para revisão", 4, 2, "2 contatos a examinar",
                "Sinalização apenas para revisão demonstrativa; não é classificação clínica.",
                review_signal_demo=True,
            ),
            _patient(
                "DEMO-TB-004", "Unidade Demonstrativa Norte", "Distrito Beta",
                42, 128, "Em acompanhamento", 1, 1, "Nenhuma (demonstração)",
                "Registro fictício para demonstração.",
            ),
        ),
        units_without_monthly_update=("Unidade Demonstrativa Norte",),
    ),
    "hanseniase": ModuleDemo(
        key="hanseniase",
        name="Hanseníase",
        accent="green",
        patients=(
            _patient(
                "DEMO-HAN-001",
                "Unidade de Saúde de Vera (demonstração)",
                "Distrito Demonstrativo de Vera",
                125, 21, "Em acompanhamento", 2, 1, "1 contato a examinar",
                "Registro fictício para demonstração.", ending_soon_demo=True,
                new_this_month_demo=True,
            ),
            _patient(
                "DEMO-HAN-002",
                "Unidade de Saúde de Vera (demonstração)",
                "Distrito Demonstrativo de Vera",
                76, 104, "Acompanhamento pendente", 3, 1, "2 contatos a examinar",
                "Atualizar informação fictícia de acompanhamento.",
            ),
            _patient(
                "DEMO-HAN-003", "Unidade Demonstrativa Leste", "Distrito Delta",
                152, 63, "Sinalização para revisão", 2, 0, "2 contatos a examinar",
                "Sinalização apenas para revisão demonstrativa; não é classificação clínica.",
                review_signal_demo=True,
            ),
            _patient(
                "DEMO-HAN-004", "Unidade Demonstrativa Leste", "Distrito Delta",
                39, 139, "Em acompanhamento", 1, 1, "Nenhuma (demonstração)",
                "Registro fictício para demonstração.",
            ),
        ),
        units_without_monthly_update=("Unidade Demonstrativa Leste",),
    ),
}
