"""structured_report_versions

Adds structured-report support to report_versions: the JSON report body
plus draft_v2 revision metadata and final_v1 approval metadata, so a single
row can carry everything needed for the draft_v1 -> draft_v2 -> final_v1
flow without regenerating content at each stage.

Revision ID: cee432785b7a
Revises: 3050bd5f52aa
Create Date: 2026-07-11 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'cee432785b7a'
down_revision: Union[str, Sequence[str], None] = '3050bd5f52aa'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('report_versions', sa.Column('report_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('report_versions', sa.Column('created_by', sa.String(), nullable=True))
    op.add_column('report_versions', sa.Column('change_summary', sa.Text(), nullable=True))
    op.add_column('report_versions', sa.Column('change_reason', sa.Text(), nullable=True))
    op.add_column('report_versions', sa.Column('reviewer_comment', sa.Text(), nullable=True))
    op.add_column('report_versions', sa.Column('safety_check_result', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('report_versions', sa.Column('approved_by', sa.String(), nullable=True))
    op.add_column('report_versions', sa.Column('approved_at', sa.DateTime(), nullable=True))
    op.add_column('report_versions', sa.Column('approval_comment', sa.Text(), nullable=True))
    op.add_column('report_versions', sa.Column('source_version', sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('report_versions', 'source_version')
    op.drop_column('report_versions', 'approval_comment')
    op.drop_column('report_versions', 'approved_at')
    op.drop_column('report_versions', 'approved_by')
    op.drop_column('report_versions', 'safety_check_result')
    op.drop_column('report_versions', 'reviewer_comment')
    op.drop_column('report_versions', 'change_reason')
    op.drop_column('report_versions', 'change_summary')
    op.drop_column('report_versions', 'created_by')
    op.drop_column('report_versions', 'report_json')
