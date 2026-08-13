"""add appointment overlap exclusion constraint

Revision ID: 1cd7350c3ed2
Revises: c5e0db3ee3a0
Create Date: 2026-08-12 20:40:30.000000

Requires the btree_gist extension.

The range is built with make_interval() because it is IMMUTABLE — string
concatenation like (duration_minutes || ' minutes')::interval is not,
and PostgreSQL rejects non-immutable functions in index expressions.

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1cd7350c3ed2'
down_revision: Union[str, Sequence[str], None] = 'c5e0db3ee3a0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    # timestamptz + interval is STABLE (not IMMUTABLE) in PostgreSQL, so it
    # cannot appear in an index expression. Wrap it in an IMMUTABLE function:
    # fixed-minute intervals are timezone-independent, so the declaration is safe.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION ts_add_minutes(t timestamptz, m smallint)
        RETURNS timestamptz
        LANGUAGE sql IMMUTABLE
        RETURN t + make_interval(mins => m)
        """
    )
    op.execute(
        """
        ALTER TABLE appointments
        ADD CONSTRAINT no_overlapping_active_appointments
        EXCLUDE USING gist (
            doctor_id WITH =,
            tstzrange(date_time, ts_add_minutes(date_time, duration_minutes))
                WITH &&
        )
        WHERE (status NOT IN ('CANCELLED', 'NO_SHOW'))
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(
        "ALTER TABLE appointments DROP CONSTRAINT IF EXISTS no_overlapping_active_appointments"
    )
    op.execute("DROP FUNCTION IF EXISTS ts_add_minutes(timestamptz, smallint)")