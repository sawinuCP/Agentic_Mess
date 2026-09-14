"""events.task_id promoted to a real task reference

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-14

Phase 0 stored task_id as a correlation string; Phase 2 gives tasks real UUID
identity, so the event column becomes a proper FK (SET NULL) for traceability.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "events",
        "task_id",
        existing_type=sa.String(length=64),
        type_=UUID(as_uuid=True),
        existing_nullable=True,
        postgresql_using="NULLIF(task_id, '')::uuid",
    )
    op.create_foreign_key(
        "fk_events_task_id", "events", "tasks", ["task_id"], ["id"], ondelete="SET NULL"
    )


def downgrade() -> None:
    op.drop_constraint("fk_events_task_id", "events", type_="foreignkey")
    op.alter_column(
        "events",
        "task_id",
        existing_type=UUID(as_uuid=True),
        type_=sa.String(length=64),
        existing_nullable=True,
        postgresql_using="task_id::text",
    )
