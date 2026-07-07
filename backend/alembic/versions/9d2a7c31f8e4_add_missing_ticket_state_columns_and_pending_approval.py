"""add missing ticket state columns

Revision ID: 9d2a7c31f8e4
Revises: 7ab55ceb5b91
Create Date: 2026-07-07 01:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "9d2a7c31f8e4"
down_revision: Union[str, Sequence[str], None] = "7ab55ceb5b91"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "tickets",
        sa.Column("impact_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "tickets",
        sa.Column("policy_decision", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("tickets", "policy_decision")
    op.drop_column("tickets", "impact_summary")
