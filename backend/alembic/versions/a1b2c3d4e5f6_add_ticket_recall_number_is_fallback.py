"""add recall_number_is_fallback to tickets

Revision ID: a1b2c3d4e5f6
Revises: 9d2a7c31f8e4
Create Date: 2026-07-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "9d2a7c31f8e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "tickets",
        sa.Column(
            "recall_number_is_fallback",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("tickets", "recall_number_is_fallback")
