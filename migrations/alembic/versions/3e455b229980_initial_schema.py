"""Initial schema

Revision ID: 3e455b229980
Revises: 
Create Date: 2026-01-09 14:29:21.197327

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '3e455b229980'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema - create all tables."""
    # Users table
    op.create_table(
        'users',
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('username', sa.String(length=255), nullable=True),
        sa.Column('first_name', sa.String(length=255), nullable=True),
        sa.Column('last_name', sa.String(length=255), nullable=True),
        sa.Column('last_chat_id', sa.Integer(), nullable=True),
        sa.Column('last_chat_type', sa.String(length=50), nullable=True),
        sa.Column('last_seen', sa.DateTime(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('user_id', name='users_pkey'),
        sa.UniqueConstraint('user_id', name='users_user_id_key')
    )
    
    # Groups table
    op.create_table(
        'groups',
        sa.Column('chat_id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=True),
        sa.Column('chat_type', sa.String(length=50), nullable=True),
        sa.Column('bot_status', sa.String(length=50), nullable=True),
        sa.Column('bot_is_admin', sa.Boolean(), nullable=True),
        sa.Column('last_seen', sa.DateTime(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('chat_id', name='groups_pkey'),
        sa.UniqueConstraint('chat_id', name='groups_chat_id_key')
    )
    
    # Quizzes table
    op.create_table(
        'quizzes',
        sa.Column('quiz_id', sa.String(length=50), nullable=False),
        sa.Column('title', sa.String(length=500), nullable=True),
        sa.Column('created_by', sa.Integer(), nullable=False),
        sa.Column('created_in_chat', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('is_private', sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(['created_by'], ['users.user_id'], ),
        sa.PrimaryKeyConstraint('quiz_id', name='quizzes_pkey'),
        sa.UniqueConstraint('quiz_id', name='quizzes_quiz_id_key')
    )
    op.create_index('idx_quiz_created_by', 'quizzes', ['created_by'], unique=False)
    op.create_index('idx_quiz_created_at', 'quizzes', ['created_at'], unique=False)
    
    # Questions table
    op.create_table(
        'questions',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('quiz_id', sa.String(length=50), nullable=False),
        sa.Column('question_index', sa.Integer(), nullable=False),
        sa.Column('question_text', sa.Text(), nullable=False),
        sa.Column('options', postgresql.JSON(astext_type=sa.Text()), nullable=False),
        sa.Column('correct_answer', sa.Integer(), nullable=False),
        sa.Column('explanation', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['quiz_id'], ['quizzes.quiz_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name='questions_pkey')
    )
    op.create_index('idx_question_quiz_id', 'questions', ['quiz_id'], unique=False)
    op.create_index('idx_question_quiz_index', 'questions', ['quiz_id', 'question_index'], unique=False)
    
    # Quiz results table
    op.create_table(
        'quiz_results',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('quiz_id', sa.String(length=50), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('chat_id', sa.Integer(), nullable=False),
        sa.Column('answers', postgresql.JSON(astext_type=sa.Text()), nullable=False),
        sa.Column('correct_count', sa.Integer(), nullable=False),
        sa.Column('total_count', sa.Integer(), nullable=False),
        sa.Column('percentage', sa.Float(), nullable=False),
        sa.Column('answer_times', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('total_time', sa.Float(), nullable=True),
        sa.Column('avg_time', sa.Float(), nullable=True),
        sa.Column('min_time', sa.Float(), nullable=True),
        sa.Column('max_time', sa.Float(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['quiz_id'], ['quizzes.quiz_id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.user_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name='quiz_results_pkey')
    )
    op.create_index('idx_result_quiz_id', 'quiz_results', ['quiz_id'], unique=False)
    op.create_index('idx_result_user_id', 'quiz_results', ['user_id'], unique=False)
    op.create_index('idx_result_chat_id', 'quiz_results', ['chat_id'], unique=False)
    op.create_index('idx_result_completed_at', 'quiz_results', ['completed_at'], unique=False)
    op.create_index('idx_result_user_quiz', 'quiz_results', ['user_id', 'quiz_id'], unique=False)
    
    # Group quiz allowlist table
    op.create_table(
        'group_quiz_allowlist',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('chat_id', sa.Integer(), nullable=False),
        sa.Column('quiz_id', sa.String(length=50), nullable=False),
        sa.Column('added_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['chat_id'], ['groups.chat_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name='group_quiz_allowlist_pkey')
    )
    op.create_index('idx_allowlist_chat_quiz', 'group_quiz_allowlist', ['chat_id', 'quiz_id'], unique=True)
    
    # Quiz allowed groups table
    op.create_table(
        'quiz_allowed_groups',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('quiz_id', sa.String(length=50), nullable=False),
        sa.Column('group_id', sa.Integer(), nullable=False),
        sa.Column('added_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['group_id'], ['groups.chat_id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['quiz_id'], ['quizzes.quiz_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name='quiz_allowed_groups_pkey')
    )
    op.create_index('idx_allowed_group_quiz_group', 'quiz_allowed_groups', ['quiz_id', 'group_id'], unique=True)
    
    # Sudo users table
    op.create_table(
        'sudo_users',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('username', sa.String(length=255), nullable=True),
        sa.Column('first_name', sa.String(length=255), nullable=True),
        sa.Column('added_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id', name='sudo_users_pkey'),
        sa.UniqueConstraint('user_id', name='sudo_users_user_id_key')
    )
    
    # VIP users table
    op.create_table(
        'vip_users',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('username', sa.String(length=255), nullable=True),
        sa.Column('first_name', sa.String(length=255), nullable=True),
        sa.Column('nickname', sa.String(length=255), nullable=True),
        sa.Column('added_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id', name='vip_users_pkey'),
        sa.UniqueConstraint('user_id', name='vip_users_user_id_key')
    )
    
    # Premium users table
    op.create_table(
        'premium_users',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('username', sa.String(length=255), nullable=True),
        sa.Column('first_name', sa.String(length=255), nullable=True),
        sa.Column('premium_until', sa.DateTime(), nullable=False),
        sa.Column('stars_paid', sa.Integer(), nullable=False),
        sa.Column('months', sa.Integer(), nullable=False),
        sa.Column('activated_at', sa.DateTime(), nullable=False),
        sa.Column('last_updated', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id', name='premium_users_pkey'),
        sa.UniqueConstraint('user_id', name='premium_users_user_id_key')
    )
    op.create_index('idx_premium_user_id', 'premium_users', ['user_id'], unique=False)
    op.create_index('idx_premium_until', 'premium_users', ['premium_until'], unique=False)
    
    # Premium payments table
    op.create_table(
        'premium_payments',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('stars_amount', sa.Integer(), nullable=False),
        sa.Column('months', sa.Integer(), nullable=False),
        sa.Column('premium_until', sa.DateTime(), nullable=False),
        sa.Column('paid_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id', name='premium_payments_pkey')
    )
    op.create_index('idx_payment_user_id', 'premium_payments', ['user_id'], unique=False)
    op.create_index('idx_payment_paid_at', 'premium_payments', ['paid_at'], unique=False)
    
    # Required channels table
    op.create_table(
        'required_channels',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('channel_id', sa.Integer(), nullable=False),
        sa.Column('channel_username', sa.String(length=255), nullable=True),
        sa.Column('channel_title', sa.String(length=255), nullable=True),
        sa.Column('added_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id', name='required_channels_pkey'),
        sa.UniqueConstraint('channel_id', name='required_channels_channel_id_key')
    )


def downgrade() -> None:
    """Downgrade schema - drop all tables."""
    op.drop_table('required_channels')
    op.drop_index('idx_payment_paid_at', table_name='premium_payments')
    op.drop_index('idx_payment_user_id', table_name='premium_payments')
    op.drop_table('premium_payments')
    op.drop_index('idx_premium_until', table_name='premium_users')
    op.drop_index('idx_premium_user_id', table_name='premium_users')
    op.drop_table('premium_users')
    op.drop_table('vip_users')
    op.drop_table('sudo_users')
    op.drop_index('idx_allowed_group_quiz_group', table_name='quiz_allowed_groups')
    op.drop_table('quiz_allowed_groups')
    op.drop_index('idx_allowlist_chat_quiz', table_name='group_quiz_allowlist')
    op.drop_table('group_quiz_allowlist')
    op.drop_index('idx_result_user_quiz', table_name='quiz_results')
    op.drop_index('idx_result_completed_at', table_name='quiz_results')
    op.drop_index('idx_result_chat_id', table_name='quiz_results')
    op.drop_index('idx_result_user_id', table_name='quiz_results')
    op.drop_index('idx_result_quiz_id', table_name='quiz_results')
    op.drop_table('quiz_results')
    op.drop_index('idx_question_quiz_index', table_name='questions')
    op.drop_index('idx_question_quiz_id', table_name='questions')
    op.drop_table('questions')
    op.drop_index('idx_quiz_created_at', table_name='quizzes')
    op.drop_index('idx_quiz_created_by', table_name='quizzes')
    op.drop_table('quizzes')
    op.drop_table('groups')
    op.drop_table('users')
