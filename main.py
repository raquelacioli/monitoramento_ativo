from fastapi import FastAPI

from monitoramento.routes import router

app = FastAPI(title="Monitoramento Ativo de Tuberculose e Hanseníase")
app.include_router(router)
