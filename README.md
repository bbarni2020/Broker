# Broker

I’m keeping this repo honest: real-money mindset, no mystery trades, everything runs from env vars.

Quick start (works on my M2):
1. cp .env.example .env and drop in your keys + a strong JWT secret.
2. docker compose up --build
3. Hit http://localhost:8000/health until it returns {"status": "ok"}.

What you get
- API: FastAPI on http://localhost:8000 with DB-backed /health.
- Dashboard: Flask visuals on http://localhost:5000 (sample data today).
- Postgres: port 5432, credentials from .env, data persisted in the postgres_data volume.
- Migrations: one-shot service runs alembic upgrade head before the API starts.

Environment bits
- DATABASE_URL must be set (compose wires it to the db container by default).
- POSTGRES_USER/POSTGRES_PASSWORD/POSTGRES_DB feed both Postgres and Alembic.
- AI_API_KEY, SEARCH_API_KEY, ALPACA_API_KEY, ALPACA_SECRET_KEY, JWT_SECRET, OTP_ISSUER_NAME are required; keep them in .env only.

Clean boot drill
- docker compose down -v
- docker compose up --build
- curl http://localhost:8000/health
- If it breaks, you keep both pieces.

Testing
- APP_ENV=test DATABASE_URL=sqlite+pysqlite:///:memory: AI_API_KEY=test SEARCH_API_KEY=test ALPACA_API_KEY=test ALPACA_SECRET_KEY=test JWT_SECRET=test OTP_ISSUER_NAME=test \
	./.venv/bin/python -m pytest app/tests -v --tb=short
- Last run on my machine: green across the suite.

Known quirks
- Dashboard still uses sample data; wire it to live sources before showing it off.
- No live trade endpoints are exposed yet; auth and logging are ready for when we plug them in.

Notes from development
- I built this to scratch an itch for explainable, logged decisions. The compose stack makes it easy to tear down and respawn without leaving ghost state.

