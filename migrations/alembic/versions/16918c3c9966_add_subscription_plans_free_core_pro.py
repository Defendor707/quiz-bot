"""Add subscription plans Free Core Pro

Revision ID: 16918c3c9966
Revises: 3e455b229980
Create Date: 2026-01-09 14:41:51.748123

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '16918c3c9966'
down_revision: Union[str, Sequence[str], None] = '3e455b229980'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
