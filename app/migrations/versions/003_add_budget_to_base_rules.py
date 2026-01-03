"""add budget to base rules

Revision ID: 003_add_budget
Revises: 002_add_symbol_created_at
Create Date: 2026-01-02
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("base_rules", sa.Column("budget", sa.Float(), nullable=False, server_default="100000"))
    op.execute("UPDATE base_rules SET budget = 100000 WHERE budget IS NULL")
    op.alter_column("base_rules", "budget", server_default=None)


def downgrade() -> None:
    op.drop_column("base_rules", "budget")
