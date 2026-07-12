"""add chat session and message status

Adds a lifecycle status to chat_sessions ("active"/"closed", schema support
only -- no close-session endpoint yet) and a processing-outcome status to
chat_messages ("succeeded"/"failed"), so a chat turn that fails partway
through can be persisted instead of being silently rolled back with no
trace (see app.chat.handler.handle_chat).

Revision ID: f3a1c9d84b02
Revises: b4f6f3d2a9c1
Create Date: 2026-07-12 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "f3a1c9d84b02"
down_revision: Union[str, Sequence[str], None] = "b4f6f3d2a9c1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "chat_sessions",
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
    )
    op.create_check_constraint(
        "chat_sessions_status_check",
        "chat_sessions",
        "status IN ('active', 'closed')",
    )
    op.add_column(
        "chat_messages",
        sa.Column("status", sa.String(), nullable=False, server_default="succeeded"),
    )
    op.create_check_constraint(
        "chat_messages_status_check",
        "chat_messages",
        "status IN ('succeeded', 'failed')",
    )


def downgrade() -> None:
    op.drop_constraint("chat_messages_status_check", "chat_messages", type_="check")
    op.drop_column("chat_messages", "status")
    op.drop_constraint("chat_sessions_status_check", "chat_sessions", type_="check")
    op.drop_column("chat_sessions", "status")
