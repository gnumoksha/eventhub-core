"""add Pix type to payout accounts

Revision ID: 8d3f2b7c1a9e
Revises: cbde6a6bf040
Create Date: 2026-11-01 20:16:31.000000

"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "8d3f2b7c1a9e"
down_revision: Union[str, Sequence[str], None] = "cbde6a6bf040"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pix_key_type = sa.Enum("CPF", "CNPJ", "PHONE", "EMAIL", "EVP", name="pixkeytype", schema="organizers")
    pix_key_type.create(op.get_bind())
    op.add_column(
        "payout_accounts",
        sa.Column(
            "pix_type",
            sa.Enum("CPF", "CNPJ", "PHONE", "EMAIL", "EVP", name="pixkeytype", schema="organizers"),
            nullable=True,
        ),
        schema="organizers",
    )


def downgrade() -> None:
    op.drop_column("payout_accounts", "pix_type", schema="organizers")
    sa.Enum("CPF", "CNPJ", "PHONE", "EMAIL", "EVP", name="pixkeytype", schema="organizers").drop(op.get_bind())
