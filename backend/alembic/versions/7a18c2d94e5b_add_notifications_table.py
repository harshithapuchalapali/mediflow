"""add notifications table

Revision ID: 7a18c2d94e5b
Revises: 584d8ff491c3
Create Date: 2026-08-16 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7a18c2d94e5b'
down_revision: Union[str, Sequence[str], None] = '584d8ff491c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Notifications table exactly per database-design.md §3.20.
    op.create_table('notifications',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('user_id', sa.BigInteger(), nullable=False),
    sa.Column('type', sa.String(length=50), nullable=False),
    sa.Column('message', sa.Text(), nullable=False),
    sa.Column('channel', sa.Text(), server_default=sa.text("'IN_APP'"), nullable=False),
    sa.Column('is_read', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("channel IN ('IN_APP', 'EMAIL')", name='ck_notifications_channel'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_notif_user', 'notifications', ['user_id', 'is_read'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('idx_notif_user', table_name='notifications')
    op.drop_table('notifications')