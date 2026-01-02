"""add provisioning link shown flag

Revision ID: 001
Revises: 
Create Date: 2026-01-02

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('dashboard_secrets', sa.Column('provisioning_link_shown', sa.Boolean(), nullable=False, server_default='false'))


def downgrade() -> None:
    op.drop_column('dashboard_secrets', 'provisioning_link_shown')
