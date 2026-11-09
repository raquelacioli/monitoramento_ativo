import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from google.api_core.exceptions import GoogleAPICallError, RetryError
from starlette.concurrency import run_in_threadpool

from monitoramento.firestore_store import (
    MigrationPendingError,
    get_store,
    key,
)
from monitoramento.routes import router
from monitoramento.import_routes import router as import_router


# Configuração de logs
logger = logging.getLogger(__name__)


# Verificação do banco de dados Firestore
def _check_database():
    store = get_store()

    state = store.get(
        "_migration",
        key("state"),
    )

    if state and state.get("status") != "complete":
        raise ValueError(
            "Migração do banco de dados ainda não concluída."
        )


# Inicialização e encerramento da aplicação
@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await run_in_threadpool(_check_database)

    except Exception:
        logger.exception(
            "Falha na inicialização do Firestore."
        )

        raise RuntimeError(
            "Firestore indisponível ou configuração inválida. "
            "Confira projeto, credenciais e namespace."
        ) from None

    logger.info(
        "Monitoramento Ativo iniciado com sucesso."
    )

    yield

    logger.info(
        "Monitoramento Ativo encerrado."
    )


# Aplicação principal
app = FastAPI(
    title="Monitoramento Ativo de Tuberculose e Hanseníase",
    lifespan=lifespan,
)


# Rotas do sistema
app.include_router(router)
app.include_router(import_router)


# Tratamento de erros do banco
@app.exception_handler(GoogleAPICallError)
@app.exception_handler(RetryError)
@app.exception_handler(MigrationPendingError)
async def database_unavailable(request, error):

    logger.error(
        "Erro de acesso ao Firestore: %s",
        type(error).__name__,
    )

    return JSONResponse(
        status_code=503,
        content={
            "detail": (
                "Banco temporariamente indisponível. "
                "Tente novamente."
            )
        },
    )


# Verificação de saúde para o Render
@app.get("/healthz", include_in_schema=False)
def healthz():

    try:
        _check_database()

    except Exception:
        logger.exception(
            "Falha na verificação do Firestore."
        )

        return JSONResponse(
            status_code=503,
            content={
                "status": "unavailable"
            },
        )

    return {
        "status": "ok"
    }
