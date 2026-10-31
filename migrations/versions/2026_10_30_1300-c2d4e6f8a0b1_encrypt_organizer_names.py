"""store organizer legal and payout holder names as encrypted text

Revision ID: c2d4e6f8a0b1
Revises: 4b73a12c0d9e
Create Date: 2026-10-30 13:00:00

"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "c2d4e6f8a0b1"
down_revision: Union[str, Sequence[str], None] = "4b73a12c0d9e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "organizations",
        "legal_name",
        existing_type=sa.String(length=200),
        type_=sa.Text(),
        existing_nullable=False,
        schema="organizers",
    )
    op.alter_column(
        "payout_accounts",
        "holder_name",
        existing_type=sa.String(length=200),
        type_=sa.Text(),
        existing_nullable=False,
        schema="organizers",
    )


def downgrade() -> None:
    op.alter_column(
        "payout_accounts",
        "holder_name",
        existing_type=sa.Text(),
        type_=sa.String(length=200),
        existing_nullable=False,
        schema="organizers",
    )
    op.alter_column(
        "organizations",
        "legal_name",
        existing_type=sa.Text(),
        type_=sa.String(length=200),
        existing_nullable=False,
        schema="organizers",
    )
