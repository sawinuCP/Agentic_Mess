"""Wave 3: per-project monotonic sequence for durable events

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-17

``events.project_seq`` is a dense per-project ordering cursor assigned by the
ORM via an atomic upsert on ``event_sequences`` (same transaction as the event
insert). It is the ordering scope for the realtime stream: clients detect missed
events by sequence gaps and resynchronize from the authoritative table.

Existing rows are backfilled densely per project (ordered by occurred_at, id).
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "event_sequences",
        sa.Column("project_id", UUID(as_uuid=True), primary_key=True),
        sa.Column("last_seq", sa.BigInteger(), nullable=False),
    )
    op.add_column("events", sa.Column("project_seq", sa.BigInteger(), nullable=True))
    op.create_index("ix_events_project_seq", "events", ["project_id", "project_seq"])

    # Dense backfill per project, then seed the counters.
    op.execute(
        """
        WITH ranked AS (
            SELECT id,
                   ROW_NUMBER() OVER (PARTITION BY project_id ORDER BY occurred_at, id) AS rn
            FROM events
            WHERE project_id IS NOT NULL
        )
        UPDATE events e
        SET project_seq = ranked.rn
        FROM ranked
        WHERE e.id = ranked.id
        """
    )
    op.execute(
        """
        INSERT INTO event_sequences (project_id, last_seq)
        SELECT project_id, MAX(project_seq)
        FROM events
        WHERE project_id IS NOT NULL AND project_seq IS NOT NULL
        GROUP BY project_id
        """
    )


def downgrade() -> None:
    op.drop_index("ix_events_project_seq", table_name="events")
    op.drop_column("events", "project_seq")
    op.drop_table("event_sequences")
