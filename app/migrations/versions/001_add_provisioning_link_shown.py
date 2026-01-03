"""add provisioning link shown flag (kept for reference)

Revision ID: 0002
Revises: 0001
Create Date: 2026-01-02 12:01:00.000000

This migration is a no-op since provisioning_link_shown is already
included in the baseline schema (0001).

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0002'
down_revision: str = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
