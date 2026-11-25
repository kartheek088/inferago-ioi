"""website recovery: owner review of contacts that may be personal (additive)

Revision ID: 0016_contact_reviews
Revises: 0015_recovery_activity
Create Date: 2026-11-26

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0016_contact_reviews'
down_revision: Union[str, Sequence[str], None] = '0015_recovery_activity'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'ioi_contact_reviews',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('contact_id', sa.Integer(), nullable=False),
        sa.Column('decision', sa.String(length=20), nullable=False),
        sa.Column('note', sa.String(length=200), nullable=True),
        sa.Column('reviewed_by', sa.String(length=80), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['contact_id'], ['ioi_contacts.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_ioi_contact_reviews_contact_id', 'ioi_contact_reviews', ['contact_id'], unique=True)


def downgrade() -> None:
    op.drop_index('ix_ioi_contact_reviews_contact_id', table_name='ioi_contact_reviews')
    op.drop_table('ioi_contact_reviews')
