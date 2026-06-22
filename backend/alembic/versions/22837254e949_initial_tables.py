"""initial tables

Revision ID: 22837254e949
Revises: aa7304f4e69c
Create Date: 2026-06-22 17:28:22.780495

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '22837254e949'
down_revision: Union[str, Sequence[str], None] = 'aa7304f4e69c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
