"""sales feedback: lead source on companies, outcome reason on deals (additive)

Revision ID: 0017_sales_feedback
Revises: 0016_contact_reviews
Create Date: 2026-11-26

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0017_sales_feedback'
down_revision: Union[str, Sequence[str], None] = '0016_contact_reviews'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('ioi_companies') as b:
        b.add_column(sa.Column('lead_source', sa.String(length=30), nullable=True))
    with op.batch_alter_table('ioi_deals') as b:
        b.add_column(sa.Column('outcome_reason', sa.String(length=300), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('ioi_deals') as b:
        b.drop_column('outcome_reason')
    with op.batch_alter_table('ioi_companies') as b:
        b.drop_column('lead_source')
