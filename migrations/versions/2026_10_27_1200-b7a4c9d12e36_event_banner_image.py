"""add event banner image key

Revision ID: b7a4c9d12e36
Revises: 3f2a8cbdb8af
Create Date: 2026-10-27 12:00:00.000000

"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "b7a4c9d12e36"
down_revision: Union[str, Sequence[str], None] = "3f2a8cbdb8af"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "events",
        sa.Column("banner_image_key", sa.String(length=512), nullable=True),
        schema="events",
    )


def downgrade() -> None:
    op.drop_column("events", "banner_image_key", schema="events")
