from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os

from .database import Base, engine
from .routers import dashboard, estoque, parceiros, financeiro

# Cria todas as tabelas ao iniciar
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="CDN — Cria da Natureza",
    description="Plataforma de gestão interna",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers da API
app.include_router(dashboard.router)
app.include_router(estoque.router)
app.include_router(parceiros.router)
app.include_router(financeiro.router)

# Serve o frontend como arquivos estáticos
FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "frontend")

if os.path.exists(FRONTEND_DIR):
    app.mount("/static/css", StaticFiles(directory=os.path.join(FRONTEND_DIR, "css")), name="css")
    app.mount("/static/js", StaticFiles(directory=os.path.join(FRONTEND_DIR, "js")), name="js")

    @app.get("/", include_in_schema=False)
    async def index():
        return FileResponse(os.path.join(FRONTEND_DIR, "html", "index.html"))

    @app.get("/{page}.html", include_in_schema=False)
    async def serve_page(page: str):
        path = os.path.join(FRONTEND_DIR, "html", f"{page}.html")
        if os.path.exists(path):
            return FileResponse(path)
        return FileResponse(os.path.join(FRONTEND_DIR, "html", "index.html"))
