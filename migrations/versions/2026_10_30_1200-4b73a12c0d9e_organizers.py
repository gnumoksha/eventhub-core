"""create organizers and payout account tables

Revision ID: 4b73a12c0d9e
Revises: b7a4c9d12e36
Create Date: 2026-10-30 12:00:00

"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import Text
from sqlmodel.sql.sqltypes import UTCDateTime

revision: str = "4b73a12c0d9e"
down_revision: Union[str, Sequence[str], None] = "b7a4c9d12e36"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS organizers")
    op.create_table(
        "organizations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_type", sa.String(length=32), nullable=False),
        sa.Column("public_name", sa.String(length=200), nullable=False),
        sa.Column("legal_name", Text(), nullable=False),
        sa.Column("tax_id", sa.Text(), nullable=False),
        sa.Column("verification_status", sa.String(length=32), nullable=False),
        sa.Column("verification_rejection_reason", sa.String(length=500), nullable=True),
        sa.Column("current_payout_account_id", sa.Uuid(), nullable=True),
        sa.Column("pending_payout_account_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        schema="organizers",
    )
    op.create_index(
        "ix_organizers_organizations_verification_status",
        "organizations",
        ["verification_status"],
        schema="organizers",
    )
    op.create_table(
        "members",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizers.organizations.id"]),
        sa.PrimaryKeyConstraint("organization_id", "account_id"),
        schema="organizers",
    )
    op.create_index("ix_organizers_members_account_id", "members", ["account_id"], schema="organizers")
    op.create_index("ix_organizers_members_role", "members", ["role"], schema="organizers")
    op.create_table(
        "payout_accounts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("method", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("pix_key", sa.Text(), nullable=True),
        sa.Column("bank_code", sa.Text(), nullable=True),
        sa.Column("branch", sa.Text(), nullable=True),
        sa.Column("account_number", sa.Text(), nullable=True),
        sa.Column("account_digit", sa.Text(), nullable=True),
        sa.Column("account_type", sa.String(length=32), nullable=True),
        sa.Column("holder_name", Text(), nullable=False),
        sa.Column("holder_tax_id", sa.Text(), nullable=False),
        sa.Column("rejection_reason", sa.String(length=500), nullable=True),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizers.organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
        schema="organizers",
    )
    op.create_index(
        "ix_organizers_payout_accounts_organization_id", "payout_accounts", ["organization_id"], schema="organizers"
    )
    op.create_index("ix_organizers_payout_accounts_status", "payout_accounts", ["status"], schema="organizers")


def downgrade() -> None:
    op.drop_index("ix_organizers_payout_accounts_status", table_name="payout_accounts", schema="organizers")
    op.drop_index("ix_organizers_payout_accounts_organization_id", table_name="payout_accounts", schema="organizers")
    op.drop_table("payout_accounts", schema="organizers")
    op.drop_index("ix_organizers_members_role", table_name="members", schema="organizers")
    op.drop_index("ix_organizers_members_account_id", table_name="members", schema="organizers")
    op.drop_table("members", schema="organizers")
    op.drop_index("ix_organizers_organizations_verification_status", table_name="organizations", schema="organizers")
    op.drop_table("organizations", schema="organizers")
    op.execute("DROP SCHEMA IF EXISTS organizers")
