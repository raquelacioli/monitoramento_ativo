from fastapi import FastAPI

from monitoramento.routes import router
from monitoramento.import_routes import router as import_router

app = FastAPI(title="Monitoramento Ativo de Tuberculose e Hanseníase")
app.include_router(router)
app.include_router(import_router)
