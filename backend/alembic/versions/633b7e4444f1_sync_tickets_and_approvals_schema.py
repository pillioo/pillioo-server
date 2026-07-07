"""sync tickets and approvals schema with current models

Revision ID: 633b7e4444f1
Revises: 0f4db5b7949c
Create Date: 2026-07-07 00:41:56.209437

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '633b7e4444f1'
down_revision: Union[str, Sequence[str], None] = '0f4db5b7949c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # PostgreSQL enum creation must be explicit before altering the existing column.
    approval_status = sa.Enum('approved', 'rejected', 'revised', name='approval_status')
    approval_status.create(op.get_bind(), checkfirst=True)
    op.alter_column('approvals', 'status',
               existing_type=sa.VARCHAR(),
               type_=approval_status,
               existing_nullable=False,
               postgresql_using='status::approval_status')
    op.drop_index(op.f('ix_approvals_ticket_id'), table_name='approvals')
    op.drop_index(op.f('ix_audit_logs_ticket_id'), table_name='audit_logs')
    op.drop_index(op.f('ix_report_versions_ticket_id'), table_name='report_versions')
    op.add_column('tickets', sa.Column('ticket_id', sa.String(), nullable=False))
    op.add_column('tickets', sa.Column('status', sa.String(), nullable=False))
    op.add_column('tickets', sa.Column('workflow_stage', sa.String(), nullable=False))
    op.add_column('tickets', sa.Column('priority', sa.String(), nullable=True))
    op.add_column('tickets', sa.Column('event_type', sa.String(), nullable=False))
    op.add_column('tickets', sa.Column('drug_name', sa.String(), nullable=False))
    op.add_column('tickets', sa.Column('ndc', sa.String(), nullable=False))
    op.add_column('tickets', sa.Column('lot', sa.String(), nullable=True))
    op.add_column('tickets', sa.Column('classification', sa.String(), nullable=True))
    op.add_column('tickets', sa.Column('recall_number', sa.String(), nullable=True))
    op.add_column('tickets', sa.Column('reason_for_recall', sa.String(), nullable=True))
    op.add_column('tickets', sa.Column('product_description', sa.String(), nullable=True))
    op.add_column('tickets', sa.Column('openfda_id', sa.String(), nullable=True))
    op.add_column('tickets', sa.Column('source_status', sa.String(), nullable=True))
    op.create_index(op.f('ix_tickets_ndc'), 'tickets', ['ndc'], unique=False)
    op.create_index(op.f('ix_tickets_openfda_id'), 'tickets', ['openfda_id'], unique=True)
    op.create_index(op.f('ix_tickets_ticket_id'), 'tickets', ['ticket_id'], unique=True)
    op.drop_column('tickets', 'title')
    op.drop_column('tickets', 'description')


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column('tickets', sa.Column('description', sa.VARCHAR(), autoincrement=False, nullable=True))
    op.add_column('tickets', sa.Column('title', sa.VARCHAR(), autoincrement=False, nullable=False))
    op.drop_index(op.f('ix_tickets_ticket_id'), table_name='tickets')
    op.drop_index(op.f('ix_tickets_openfda_id'), table_name='tickets')
    op.drop_index(op.f('ix_tickets_ndc'), table_name='tickets')
    op.drop_column('tickets', 'source_status')
    op.drop_column('tickets', 'openfda_id')
    op.drop_column('tickets', 'product_description')
    op.drop_column('tickets', 'reason_for_recall')
    op.drop_column('tickets', 'recall_number')
    op.drop_column('tickets', 'classification')
    op.drop_column('tickets', 'lot')
    op.drop_column('tickets', 'ndc')
    op.drop_column('tickets', 'drug_name')
    op.drop_column('tickets', 'event_type')
    op.drop_column('tickets', 'priority')
    op.drop_column('tickets', 'workflow_stage')
    op.drop_column('tickets', 'status')
    op.drop_column('tickets', 'ticket_id')
    op.create_index(op.f('ix_report_versions_ticket_id'), 'report_versions', ['ticket_id'], unique=False)
    op.create_index(op.f('ix_audit_logs_ticket_id'), 'audit_logs', ['ticket_id'], unique=False)
    op.create_index(op.f('ix_approvals_ticket_id'), 'approvals', ['ticket_id'], unique=False)
    approval_status = sa.Enum('approved', 'rejected', 'revised', name='approval_status')
    op.alter_column('approvals', 'status',
               existing_type=approval_status,
               type_=sa.VARCHAR(),
               existing_nullable=False,
               postgresql_using='status::varchar')
    approval_status.drop(op.get_bind(), checkfirst=True)
