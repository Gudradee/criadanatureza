
import os

from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_DB_PATH = os.path.join(BASE_DIR, "..", "cdn.db")

def _resolve_database_url() -> str:

    url = os.environ.get("DATABASE_URL", "").strip()
    if url:

        if url.startswith("postgres://"):
            url = "postgresql://" + url[len("postgres://"):]
        return url

    db_path = os.environ.get("DATABASE_PATH", "").strip() or _DEFAULT_DB_PATH

    db_dir = os.path.dirname(os.path.abspath(db_path))
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    return f"sqlite:///{db_path}"

_DB_URL = _resolve_database_url()

_engine_kwargs = {}
if _DB_URL.startswith("sqlite:"):
    _engine_kwargs["connect_args"] = {"check_same_thread": False}

engine = create_engine(_DB_URL, **_engine_kwargs)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    from flask import g
    if "db" not in g:
        g.db = SessionLocal()
    return g.db
