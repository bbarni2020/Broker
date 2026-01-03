"""initial schema setup

Revision ID: 0001
Revises: 
Create Date: 2026-01-02 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'dashboard_secrets',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('session_secret', sa.String(), nullable=False),
        sa.Column('otp_secret', sa.String(length=64), nullable=False),
        sa.Column('provisioning_link_shown', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_table(
        'base_rules',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('max_risk_per_trade', sa.Float(), nullable=False, server_default='0.01'),
        sa.Column('max_daily_loss', sa.Float(), nullable=False, server_default='0.05'),
        sa.Column('max_trades_per_day', sa.Integer(), nullable=False, server_default='10'),
        sa.Column('cooldown_seconds', sa.Integer(), nullable=False, server_default='300'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_table(
        'symbols',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('symbol', sa.String(length=10), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default='true'),
        sa.UniqueConstraint('symbol'),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    op.drop_table('symbols')
    op.drop_table('base_rules')
    op.drop_table('dashboard_secrets')
