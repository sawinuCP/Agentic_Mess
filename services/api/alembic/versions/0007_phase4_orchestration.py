"""Phase 4: message delivery tracking + worktree integration queue

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-14

FR-010: durable messages gain at-least-once delivery bookkeeping (delivered_at,
delivery_attempts) — the `messages` table remains the source of truth; NATS is a
transport. FR-012: worktrees gain integration-queue columns (spec §17: integration
happens through a controlled queue; conflicts are explicit tasks).
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "messages",
        sa.Column("delivery_attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "worktrees",
        sa.Column(
            "integration_status", sa.String(length=30), nullable=False, server_default="none"
        ),
    )
    op.add_column("worktrees", sa.Column("integration_position", sa.Integer(), nullable=True))
    op.create_index(
        "ix_worktrees_integration", "worktrees", ["integration_status", "integration_position"]
    )


def downgrade() -> None:
    op.drop_index("ix_worktrees_integration", table_name="worktrees")
    op.drop_column("worktrees", "integration_position")
    op.drop_column("worktrees", "integration_status")
    op.drop_column("messages", "delivery_attempts")
    op.drop_column("messages", "delivered_at")
