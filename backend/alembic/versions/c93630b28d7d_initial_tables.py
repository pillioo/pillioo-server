"""initial tables

Revision ID: c93630b28d7d
Revises: 22837254e949
Create Date: 2026-06-22 17:49:10.465130

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c93630b28d7d'
down_revision: Union[str, Sequence[str], None] = '22837254e949'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
