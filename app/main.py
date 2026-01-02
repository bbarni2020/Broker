from fastapi import FastAPI, HTTPException
from sqlalchemy import create_engine, text

from app.config import load_settings


def create_app() -> FastAPI:
    settings = load_settings()
    app = FastAPI(title="Broker API", version="0.1.0")
    app.state.settings = settings
    app.state.engine = create_engine(settings.database_url, future=True, pool_pre_ping=True)

    @app.get("/health")
    def health():
        try:
            with app.state.engine.connect() as connection:
                connection.execute(text("select 1"))
        except Exception as exc:
            raise HTTPException(status_code=503, detail="database_unavailable") from exc
        return {"status": "ok"}

    return app


app = create_app()
