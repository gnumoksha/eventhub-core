"""replace organization type with tax ID type

Revision ID: a74d19c2e8f1
Revises: 8d3f2b7c1a9e
Create Date: 2026-11-02 12:00:00.000000

"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "a74d19c2e8f1"
down_revision: Union[str, Sequence[str], None] = "8d3f2b7c1a9e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    tax_id_type = sa.Enum("CPF", "CNPJ", name="taxidtype", schema="organizers")
    tax_id_type.create(op.get_bind())
    op.add_column(
        "organizations",
        sa.Column("tax_id_type", tax_id_type, nullable=True),
        schema="organizers",
    )
    op.execute(
        """
        UPDATE organizers.organizations
        SET tax_id_type = CASE organization_type::text
            WHEN 'INDIVIDUAL' THEN 'CPF'::organizers.taxidtype
            WHEN 'COMPANY' THEN 'CNPJ'::organizers.taxidtype
        END
        """
    )
    op.alter_column(
        "organizations",
        "legal_name",
        existing_type=sa.Text(),
        nullable=True,
        schema="organizers",
    )
    op.alter_column(
        "organizations",
        "tax_id",
        existing_type=sa.Text(),
        nullable=True,
        schema="organizers",
    )
    op.drop_column("organizations", "organization_type", schema="organizers")
    sa.Enum("INDIVIDUAL", "COMPANY", name="organizationtype", schema="organizers").drop(op.get_bind())


def downgrade() -> None:
    bind = op.get_bind()
    incomplete_profiles = bind.execute(
        sa.text(
            """
            SELECT count(*)
            FROM organizers.organizations
            WHERE tax_id_type IS NULL OR legal_name IS NULL OR tax_id IS NULL
            """
        )
    ).scalar_one()
    if incomplete_profiles:
        raise RuntimeError("Cannot downgrade while organizations have incomplete legal profiles")

    organization_type = sa.Enum("INDIVIDUAL", "COMPANY", name="organizationtype", schema="organizers")
    organization_type.create(bind)
    op.add_column(
        "organizations",
        sa.Column("organization_type", organization_type, nullable=True),
        schema="organizers",
    )
    op.execute(
        """
        UPDATE organizers.organizations
        SET organization_type = CASE tax_id_type::text
            WHEN 'CPF' THEN 'INDIVIDUAL'::organizers.organizationtype
            WHEN 'CNPJ' THEN 'COMPANY'::organizers.organizationtype
        END
        """
    )
    op.alter_column(
        "organizations",
        "organization_type",
        existing_type=organization_type,
        nullable=False,
        schema="organizers",
    )
    op.alter_column(
        "organizations",
        "legal_name",
        existing_type=sa.Text(),
        nullable=False,
        schema="organizers",
    )
    op.alter_column(
        "organizations",
        "tax_id",
        existing_type=sa.Text(),
        nullable=False,
        schema="organizers",
    )
    op.drop_column("organizations", "tax_id_type", schema="organizers")
    sa.Enum("CPF", "CNPJ", name="taxidtype", schema="organizers").drop(bind)
