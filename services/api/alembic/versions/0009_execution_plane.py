"""Phase 6: execution plane — port allocations (spec §19.1)

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-16

Central port allocator: agents request ports instead of guessing; allocations
carry a TTL and are released on expiry or explicitly (spec §19.1).
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "port_allocations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("port", sa.Integer(), nullable=False),
        sa.Column("purpose", sa.String(50), nullable=False),  # preview|service|debug|...
        sa.Column("holder", sa.String(200), nullable=True),
        sa.Column("ttl_seconds", sa.Integer(), nullable=False, server_default="3600"),
        sa.Column(
            "allocated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_port_allocations_project", "port_allocations", ["project_id", "port"])


def downgrade() -> None:
    op.drop_index("ix_port_allocations_project", table_name="port_allocations")
    op.drop_table("port_allocations")
