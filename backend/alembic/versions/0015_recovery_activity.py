"""website recovery: activity evidence + alternative sites (additive)

Revision ID: 0015_recovery_activity
Revises: 0014_website_recovery
Create Date: 2026-11-26

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0015_recovery_activity'
down_revision: Union[str, Sequence[str], None] = '0014_website_recovery'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'ioi_activity_evidence',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('company_id', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(length=30), nullable=False),
        sa.Column('signal', sa.String(length=20), nullable=False),
        sa.Column('statement', sa.String(length=500), nullable=False),
        sa.Column('source_url', sa.String(length=2048), nullable=True),
        sa.Column('published_on', sa.Date(), nullable=True),
        sa.Column('observed_on', sa.Date(), nullable=False),
        sa.Column('method', sa.String(length=20), nullable=False),
        sa.Column('recorded_by', sa.String(length=80), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['ioi_companies.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_ioi_activity_evidence_company_id', 'ioi_activity_evidence', ['company_id'])
    op.create_table(
        'ioi_alt_sites',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('company_id', sa.Integer(), nullable=False),
        sa.Column('url', sa.String(length=2048), nullable=False),
        sa.Column('found_via', sa.String(length=40), nullable=False),
        sa.Column('status', sa.String(length=40), nullable=False),
        sa.Column('reason', sa.String(length=300), nullable=True),
        sa.Column('checked_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['ioi_companies.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('company_id', 'url', name='uq_ioi_alt_site'),
    )
    op.create_index('ix_ioi_alt_sites_company_id', 'ioi_alt_sites', ['company_id'])


def downgrade() -> None:
    op.drop_index('ix_ioi_alt_sites_company_id', table_name='ioi_alt_sites')
    op.drop_table('ioi_alt_sites')
    op.drop_index('ix_ioi_activity_evidence_company_id', table_name='ioi_activity_evidence')
    op.drop_table('ioi_activity_evidence')
