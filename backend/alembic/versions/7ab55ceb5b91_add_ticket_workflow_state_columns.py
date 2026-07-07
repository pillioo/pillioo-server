"""add ticket workflow state columns

Revision ID: 7ab55ceb5b91
Revises: 633b7e4444f1
Create Date: 2026-07-07 00:50:19.419467

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '7ab55ceb5b91'
down_revision: Union[str, Sequence[str], None] = '633b7e4444f1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('tickets', sa.Column('inventory_result', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('tickets', sa.Column('evidence_result', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('tickets', sa.Column('sufficiency_check', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('tickets', sa.Column('draft_text', sa.Text(), nullable=True))
    op.add_column('tickets', sa.Column('draft_citations', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('tickets', sa.Column('safety_result', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('tickets', sa.Column('trust_checks', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('tickets', sa.Column('review_type', sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('tickets', 'review_type')
    op.drop_column('tickets', 'trust_checks')
    op.drop_column('tickets', 'safety_result')
    op.drop_column('tickets', 'draft_citations')
    op.drop_column('tickets', 'draft_text')
    op.drop_column('tickets', 'sufficiency_check')
    op.drop_column('tickets', 'evidence_result')
    op.drop_column('tickets', 'inventory_result')
