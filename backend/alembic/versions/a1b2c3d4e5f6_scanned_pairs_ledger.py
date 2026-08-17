"""scanned_pairs ledger

Records which (doc_a, doc_b) pairs have already been run through the
contradiction scanner so reconciliation can re-queue only the gaps left by the
concurrent/bulk-upload indexing race.

Revision ID: a1b2c3d4e5f6
Revises: 603bbc60c42b
Create Date: 2026-06-28 12:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '603bbc60c42b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'scanned_pairs',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('org_id', sa.UUID(), nullable=False),
        sa.Column('doc_a_id', sa.UUID(), nullable=False),
        sa.Column('doc_b_id', sa.UUID(), nullable=False),
        sa.Column('scanned_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['organizations.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint('doc_a_id < doc_b_id', name='ck_scanned_pair_order'),
        sa.UniqueConstraint('org_id', 'doc_a_id', 'doc_b_id', name='uq_scanned_pair'),
    )
    op.create_index('ix_scanned_pairs_org', 'scanned_pairs', ['org_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_scanned_pairs_org', table_name='scanned_pairs')
    op.drop_table('scanned_pairs')
