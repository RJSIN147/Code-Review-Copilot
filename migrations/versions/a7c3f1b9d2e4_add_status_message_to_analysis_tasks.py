"""Add status_message to analysis_tasks

Revision ID: a7c3f1b9d2e4
Revises: e60ea05371b9
Create Date: 2026-06-19 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "a7c3f1b9d2e4"
down_revision: Union[str, Sequence[str], None] = "e60ea05371b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "analysis_tasks",
        sa.Column("status_message", sa.String(length=500), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("analysis_tasks", "status_message")
