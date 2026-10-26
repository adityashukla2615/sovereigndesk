"""Saved scenarios (SAVE / LOAD): a run's seed, start and the commands that changed it.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "scenarios",
        sa.Column("name", sa.String(24), primary_key=True),
        sa.Column("seed", sa.Integer, nullable=False),
        sa.Column("started", sa.DateTime(timezone=True), nullable=False),
        sa.Column("saved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("us_as_of", sa.Date, nullable=True),
        sa.Column("india_as_of", sa.Date, nullable=True),
        sa.Column("commands", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("scenarios")
