"""identity authentication accounts and sessions

Revision ID: 3f2a8cbdb8af
Revises: 6514ce8f40c1
Create Date: 2026-10-20 12:00:00.000000

"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlmodel.sql.sqltypes import UTCDateTime

revision: str = "3f2a8cbdb8af"
down_revision: Union[str, Sequence[str], None] = "6514ce8f40c1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS identity")
    op.create_table(
        "accounts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=512), nullable=False),
        sa.Column("email_verified_at", UTCDateTime(), nullable=True),
        sa.Column("deactivated_at", UTCDateTime(), nullable=True),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email", name="uq_identity_accounts_email"),
        schema="identity",
    )
    op.create_table(
        "sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("expires_at", UTCDateTime(), nullable=False),
        sa.Column("revoked_at", UTCDateTime(), nullable=True),
        sa.ForeignKeyConstraint(["account_id"], ["identity.accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
        schema="identity",
    )
    op.create_index("ix_identity_sessions_account_id", "sessions", ["account_id"], schema="identity")
    op.create_index("ix_identity_sessions_token_hash", "sessions", ["token_hash"], unique=True, schema="identity")
    op.create_table(
        "account_credentials",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("purpose", sa.String(length=32), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("expires_at", UTCDateTime(), nullable=False),
        sa.Column("consumed_at", UTCDateTime(), nullable=True),
        sa.ForeignKeyConstraint(["account_id"], ["identity.accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
        schema="identity",
    )
    op.create_index("ix_identity_account_credentials_account_id", "account_credentials", ["account_id"], schema="identity")
    op.create_index("ix_identity_account_credentials_purpose", "account_credentials", ["purpose"], schema="identity")
    op.create_index(
        "ix_identity_account_credentials_token_hash",
        "account_credentials",
        ["token_hash"],
        unique=True,
        schema="identity",
    )


def downgrade() -> None:
    op.drop_index("ix_identity_account_credentials_token_hash", table_name="account_credentials", schema="identity")
    op.drop_index("ix_identity_account_credentials_purpose", table_name="account_credentials", schema="identity")
    op.drop_index("ix_identity_account_credentials_account_id", table_name="account_credentials", schema="identity")
    op.drop_table("account_credentials", schema="identity")
    op.drop_index("ix_identity_sessions_token_hash", table_name="sessions", schema="identity")
    op.drop_index("ix_identity_sessions_account_id", table_name="sessions", schema="identity")
    op.drop_table("sessions", schema="identity")
    op.drop_table("accounts", schema="identity")
    op.execute("DROP SCHEMA IF EXISTS identity")
