"""create appointments table

Revision ID: c5e0db3ee3a0
Revises: 23705ebac675
Create Date: 2026-08-12 20:33:31.316014

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c5e0db3ee3a0'
down_revision: Union[str, Sequence[str], None] = '23705ebac675'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('appointments',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('patient_id', sa.BigInteger(), nullable=False),
    sa.Column('doctor_id', sa.BigInteger(), nullable=False),
    sa.Column('department_id', sa.BigInteger(), nullable=False),
    sa.Column('date_time', sa.DateTime(timezone=True), nullable=False),
    sa.Column('duration_minutes', sa.SmallInteger(), server_default=sa.text('30'), nullable=False),
    sa.Column('priority', sa.Text(), server_default=sa.text("'NORMAL'"), nullable=False),
    sa.Column('status', sa.Text(), server_default=sa.text("'PENDING'"), nullable=False),
    sa.Column('appointment_type', sa.Text(), server_default=sa.text("'INITIAL_CONSULTATION'"), nullable=False),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('created_by', sa.BigInteger(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("appointment_type IN ('INITIAL_CONSULTATION', 'FOLLOW_UP')", name='ck_appointments_appointment_type'),
    sa.CheckConstraint("priority IN ('NORMAL', 'URGENT', 'EMERGENCY')", name='ck_appointments_priority'),
    sa.CheckConstraint("status IN ('PENDING', 'CONFIRMED', 'CHECKED_IN', 'COMPLETED', 'CANCELLED', 'NO_SHOW')", name='ck_appointments_status'),
    sa.CheckConstraint('duration_minutes BETWEEN 5 AND 480', name='ck_appointments_duration_minutes'),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['department_id'], ['departments.id'], ),
    sa.ForeignKeyConstraint(['doctor_id'], ['doctors.id'], ),
    sa.ForeignKeyConstraint(['patient_id'], ['patients.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_appt_doctor_time', 'appointments', ['doctor_id', 'date_time'], unique=False)
    op.create_index('idx_appt_patient', 'appointments', ['patient_id', 'date_time'], unique=False)
    op.create_index('idx_appt_status_date', 'appointments', ['status', 'date_time'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('idx_appt_status_date', table_name='appointments')
    op.drop_index('idx_appt_patient', table_name='appointments')
    op.drop_index('idx_appt_doctor_time', table_name='appointments')
    op.drop_table('appointments')