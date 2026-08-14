"""add patient_mrn sequence

Revision ID: 584d8ff491c3
Revises: 37e1145453bb
Create Date: 2026-08-14 13:10:00.554475

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '584d8ff491c3'
down_revision: Union[str, Sequence[str], None] = '37e1145453bb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # MRN numbers are allocated from a dedicated sequence (database-design.md §5),
    # formatted as PT-000001 by the patients service.
    op.execute("CREATE SEQUENCE IF NOT EXISTS patient_mrn_seq START 1")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP SEQUENCE IF EXISTS patient_mrn_seq")
