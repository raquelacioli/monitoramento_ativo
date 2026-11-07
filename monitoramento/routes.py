from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from monitoramento.data import MODULES
from monitoramento.views import render_home, render_module

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
@router.get("/painel", response_class=HTMLResponse)
def home() -> HTMLResponse:
    return render_home()


@router.get("/tuberculose", response_class=HTMLResponse)
def tuberculose() -> HTMLResponse:
    return render_module(MODULES["tuberculose"])


@router.get("/hanseniase", response_class=HTMLResponse)
def hanseniase() -> HTMLResponse:
    return render_module(MODULES["hanseniase"])


@router.get("/api/status")
def status() -> dict[str, str | list[str]]:
    return {
        "sistema": "Monitoramento Ativo de Tuberculose e Hanseníase",
        "status": "Funcionando",
        "modulos": ["Tuberculose", "Hanseníase"],
    }
