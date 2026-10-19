"""Persistence: SQLAlchemy 2 models, engine/session setup and Alembic migrations.

SQLite by default; the same schema runs on PostgreSQL, where ``observations`` becomes a
TimescaleDB hypertable when the extension is available.
"""
