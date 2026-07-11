"""add ticket evidence snapshots

Revision ID: b4f6f3d2a9c1
Revises: cee432785b7a
Create Date: 2026-07-11 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "b4f6f3d2a9c1"
down_revision: Union[str, Sequence[str], None] = "cee432785b7a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "ticket_evidence_snapshots",
        sa.Column("ticket_id", sa.Integer(), nullable=False),
        sa.Column("source_audit_log_id", sa.Integer(), nullable=True),
        sa.Column("snapshot_version", sa.Integer(), nullable=False),
        sa.Column("snapshot_type", sa.String(), nullable=False),
        sa.Column("created_workflow_step", sa.String(), nullable=False),
        sa.Column("evidence_status", sa.String(), nullable=True),
        sa.Column("coverage_score", sa.Float(), nullable=True),
        sa.Column("citations_ready", sa.Boolean(), nullable=True),
        sa.Column("target_profile", sa.String(), nullable=True),
        sa.Column("selected_chunks", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("citations", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("sufficiency_result", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("retrieval_trace", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("retrieval_plan", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("retrieval_context", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["source_audit_log_id"], ["audit_logs.id"]),
        sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_ticket_evidence_snapshots_id"), "ticket_evidence_snapshots", ["id"], unique=False)
    op.create_index(
        op.f("ix_ticket_evidence_snapshots_source_audit_log_id"),
        "ticket_evidence_snapshots",
        ["source_audit_log_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_ticket_evidence_snapshots_ticket_id"),
        "ticket_evidence_snapshots",
        ["ticket_id"],
        unique=False,
    )
    op.create_unique_constraint(
        "uq_ticket_evidence_snapshots_ticket_version_type",
        "ticket_evidence_snapshots",
        ["ticket_id", "snapshot_version", "snapshot_type"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        "uq_ticket_evidence_snapshots_ticket_version_type",
        "ticket_evidence_snapshots",
        type_="unique",
    )
    op.drop_index(op.f("ix_ticket_evidence_snapshots_ticket_id"), table_name="ticket_evidence_snapshots")
    op.drop_index(op.f("ix_ticket_evidence_snapshots_source_audit_log_id"), table_name="ticket_evidence_snapshots")
    op.drop_index(op.f("ix_ticket_evidence_snapshots_id"), table_name="ticket_evidence_snapshots")
    op.drop_table("ticket_evidence_snapshots")
