"""merge chat and recall-number migration heads

Revision ID: 3050bd5f52aa
Revises: 8e8cdf192e62, a1b2c3d4e5f6
Create Date: 2026-07-10 16:33:01.074720

"""
from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = '3050bd5f52aa'
down_revision: Union[str, Sequence[str], None] = (
    "8e8cdf192e62",
    "a1b2c3d4e5f6",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Merge two existing migration heads without changing schema."""
    pass


def downgrade() -> None:
    """Unmerge only; schema remains owned by parent migrations."""
    pass
