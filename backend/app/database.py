from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os

# ── Localização do banco de dados ────────────────────────────────────────────
# cdn.db fica em backend/ (um nível acima de app/)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "..", "cdn.db")

# ── Engine SQLAlchemy + pool de conexões ─────────────────────────────────────
# check_same_thread=False permite que múltiplas threads do Flask compartilhem
# a mesma conexão SQLite sem erros de threading.
engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"check_same_thread": False},
)

# ── Fábrica de sessões ────────────────────────────────────────────────────────
# autocommit=False: toda escrita precisa de db.commit() explícito.
# autoflush=False: evita flushes automáticos que poderiam violar constraints antes da hora.
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# ── Base declarativa dos modelos ─────────────────────────────────────────────
# Todos os models herdam desta classe; Base.metadata.create_all() cria as tabelas.
Base = declarative_base()


# ── Helper de sessão por requisição ──────────────────────────────────────────
def get_db():
    # Reutiliza a mesma sessão durante toda a requisição via flask.g.
    # Fechada automaticamente pelo teardown registrado em create_app().
    from flask import g
    if "db" not in g:
        g.db = SessionLocal()
    return g.db

# Responsabilidade única: configurar e expor o engine SQLAlchemy, a fábrica de
# sessões (SessionLocal) e a base declarativa (Base) que os models usam.
# get_db() garante uma sessão por requisição HTTP, evitando conexões duplicadas.
