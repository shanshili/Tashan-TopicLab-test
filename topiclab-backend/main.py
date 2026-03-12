"""Website backend - account/auth service. Separate from Resonnet."""

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

# Load .env from project root or topiclab-backend/
_env_root = Path(__file__).resolve().parent.parent / ".env"
_env_local = Path(__file__).resolve().parent / ".env"
if _env_root.exists():
    from dotenv import load_dotenv
    load_dotenv(_env_root, override=True)
elif _env_local.exists():
    from dotenv import load_dotenv
    load_dotenv(_env_local, override=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth as auth_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    if os.getenv("DATABASE_URL"):
        try:
            from app.storage.database.postgres_client import init_auth_tables
            init_auth_tables()
        except Exception as e:
            logging.getLogger(__name__).warning(f"Auth tables init skipped: {e}")
    yield

app = FastAPI(
    title="TopicLab Backend (Account)",
    version="0.1.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router.router, prefix="/auth", tags=["auth"])


@app.get("/health")
def health():
    return {"status": "ok", "service": "topiclab-backend"}
