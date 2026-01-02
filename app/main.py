"""Application entrypoint for the Broker API."""
from fastapi import FastAPI

from app.config import load_settings


def create_app() -> FastAPI:
    """Construct the FastAPI application instance."""
    settings = load_settings()
    app = FastAPI(title="Broker API", version="0.1.0")
    app.state.settings = settings
    return app


app = create_app()
