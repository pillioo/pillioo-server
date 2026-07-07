"""add missing ticket state columns and pending approval status

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
    op.execute("ALTER TYPE approval_status ADD VALUE IF NOT EXISTS 'pending'")
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

    # PostgreSQL cannot drop a single enum value in place.
    op.execute("ALTER TYPE approval_status RENAME TO approval_status_old")
    op.execute("CREATE TYPE approval_status AS ENUM ('approved', 'rejected', 'revised')")
    op.execute(
        """
        ALTER TABLE approvals
        ALTER COLUMN status TYPE approval_status
        USING status::text::approval_status
        """
    )
    op.execute("DROP TYPE approval_status_old")
