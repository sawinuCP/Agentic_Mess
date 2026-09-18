"""Create idempotency keys for retried port/worktree creates.

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-18

Retried ``POST .../ports`` / ``POST .../worktrees`` (client timeout → retry)
must return the live row instead of reserving a second port or re-running git.
Both tables gain a nullable ``idempotency_key`` guarded by a partial unique
index — NULL keys (callers that opt out) never collide.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("port_allocations", sa.Column("idempotency_key", sa.String(64), nullable=True))
    op.add_column("worktrees", sa.Column("idempotency_key", sa.String(64), nullable=True))
    op.create_index(
        "uq_port_allocations_idempotency",
        "port_allocations",
        ["project_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
    op.create_index(
        "uq_worktrees_idempotency",
        "worktrees",
        ["project_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_worktrees_idempotency", table_name="worktrees")
    op.drop_index("uq_port_allocations_idempotency", table_name="port_allocations")
    op.drop_column("worktrees", "idempotency_key")
    op.drop_column("port_allocations", "idempotency_key")
