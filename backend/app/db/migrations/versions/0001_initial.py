"""Initial schema: series metadata, observations, source health, MSPD securities.

Revision ID: 0001
Revises:
Create Date: 2026-10-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "series",
        sa.Column("series_id", sa.String(80), primary_key=True),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("units", sa.String(40), nullable=False),
        sa.Column("frequency", sa.String(1), nullable=False),
    )
    op.create_index("ix_series_source", "series", ["source"])

    op.create_table(
        "observations",
        sa.Column("series_id", sa.String(80), primary_key=True),
        sa.Column("date", sa.Date, primary_key=True),
        sa.Column("value", sa.Float, nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("quality", sa.String(16), nullable=False),
    )

    op.create_table(
        "source_status",
        sa.Column("source", sa.String(32), primary_key=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("rows", sa.Integer, nullable=False),
    )

    op.create_table(
        "mspd_securities",
        sa.Column("record_date", sa.Date, primary_key=True),
        sa.Column("cusip", sa.String(12), primary_key=True),
        sa.Column("issue_date", sa.Date, primary_key=True),
        sa.Column("security_class", sa.String(64), nullable=False),
        sa.Column("maturity_date", sa.Date, nullable=False),
        sa.Column("interest_rate_pct", sa.Float, nullable=True),
        sa.Column("yield_pct", sa.Float, nullable=True),
        sa.Column("issued_musd", sa.Float, nullable=True),
        sa.Column("outstanding_musd", sa.Float, nullable=True),
        sa.Column("quality", sa.String(16), nullable=False),
    )
    op.create_index("ix_mspd_securities_maturity_date", "mspd_securities", ["maturity_date"])

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        has_timescale = bind.execute(
            sa.text("SELECT 1 FROM pg_available_extensions WHERE name = 'timescaledb'")
        ).scalar()
        if has_timescale:
            op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")
            op.execute("SELECT create_hypertable('observations', 'date', if_not_exists => TRUE)")


def downgrade() -> None:
    op.drop_index("ix_mspd_securities_maturity_date", table_name="mspd_securities")
    op.drop_table("mspd_securities")
    op.drop_table("source_status")
    op.drop_table("observations")
    op.drop_index("ix_series_source", table_name="series")
    op.drop_table("series")
