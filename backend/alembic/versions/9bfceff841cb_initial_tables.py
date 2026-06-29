"""initial tables

Revision ID: 9bfceff841cb
Revises: c93630b28d7d
Create Date: 2026-06-29 23:11:13.819378

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9bfceff841cb'
down_revision: Union[str, Sequence[str], None] = 'c93630b28d7d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
