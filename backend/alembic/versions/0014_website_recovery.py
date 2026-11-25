"""website recovery: ioi_website_checks (additive)

Revision ID: 0014_website_recovery
Revises: 0013_social_commerce
Create Date: 2026-11-26

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0014_website_recovery'
down_revision: Union[str, Sequence[str], None] = '0013_social_commerce'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'ioi_website_checks',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('company_id', sa.Integer(), nullable=False),
        sa.Column('website_url', sa.String(length=2048), nullable=False),
        sa.Column('checked_at', sa.DateTime(), nullable=False),
        sa.Column('method', sa.String(length=40), nullable=False),
        sa.Column('dns_result', sa.String(length=20), nullable=False),
        sa.Column('http_status', sa.Integer(), nullable=True),
        sa.Column('final_url', sa.String(length=2048), nullable=True),
        sa.Column('tls_result', sa.String(length=20), nullable=True),
        sa.Column('error_kind', sa.String(length=20), nullable=True),
        sa.Column('error_text', sa.String(length=300), nullable=True),
        sa.Column('observed_class', sa.String(length=40), nullable=True),
        sa.Column('status', sa.String(length=40), nullable=False),
        sa.Column('confidence', sa.String(length=10), nullable=False),
        sa.Column('reasons', sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['ioi_companies.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_ioi_website_checks_company_id', 'ioi_website_checks', ['company_id'])
    op.create_index('ix_ioi_website_checks_checked_at', 'ioi_website_checks', ['checked_at'])
    op.create_index('ix_ioi_web_check_company_time', 'ioi_website_checks', ['company_id', 'checked_at'])
    op.create_index('ix_ioi_website_checks_status', 'ioi_website_checks', ['status'])


def downgrade() -> None:
    op.drop_index('ix_ioi_website_checks_status', table_name='ioi_website_checks')
    op.drop_index('ix_ioi_web_check_company_time', table_name='ioi_website_checks')
    op.drop_index('ix_ioi_website_checks_checked_at', table_name='ioi_website_checks')
    op.drop_index('ix_ioi_website_checks_company_id', table_name='ioi_website_checks')
    op.drop_table('ioi_website_checks')
