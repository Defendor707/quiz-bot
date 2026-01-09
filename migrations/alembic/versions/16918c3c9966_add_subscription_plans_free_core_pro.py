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
    """Upgrade schema - subscription plans qo'shish."""
    # premium_users jadvaliga subscription_plan maydoni qo'shish
    op.add_column('premium_users', sa.Column('subscription_plan', sa.String(length=20), nullable=False, server_default='pro'))
    
    # premium_until ni nullable qilish (free tarif uchun)
    op.alter_column('premium_users', 'premium_until',
                    existing_type=sa.DateTime(),
                    nullable=True)
    
    # stars_paid va months uchun default qiymatlar
    op.alter_column('premium_users', 'stars_paid',
                    existing_type=sa.Integer(),
                    nullable=False,
                    server_default='0')
    
    # Eski premium userlarni Pro tarifga o'zgartirish (backward compatibility)
    op.execute("""
        UPDATE premium_users 
        SET subscription_plan = 'pro' 
        WHERE subscription_plan IS NULL OR subscription_plan = ''
    """)


def downgrade() -> None:
    """Downgrade schema - subscription plans olib tashlash."""
    # premium_until ni yana required qilish
    op.alter_column('premium_users', 'premium_until',
                    existing_type=sa.DateTime(),
                    nullable=False)
    
    # subscription_plan maydonini olib tashlash
    op.drop_column('premium_users', 'subscription_plan')
