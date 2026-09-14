"""durable core: artifacts, context items, memories, worktrees, resources

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-14
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

NOW = sa.func.now()
JSON_OBJ = sa.text("'{}'::jsonb")


def upgrade() -> None:
    op.create_table(
        "artifacts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id", UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE")
        ),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("kind", sa.String(50), nullable=False, server_default="raw_output"),
        sa.Column("mime", sa.String(100), nullable=False, server_default="text/plain"),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("storage_path", sa.String(1024), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
    )
    op.create_index("ix_artifacts_project_created", "artifacts", ["project_id", "created_at"])
    op.create_index("ix_artifacts_sha", "artifacts", ["sha256"])

    op.create_table(
        "context_items",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id", UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE")
        ),
        sa.Column("task_id", UUID(as_uuid=True), sa.ForeignKey("tasks.id", ondelete="SET NULL")),
        sa.Column("tier", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("kind", sa.String(50), nullable=False),
        sa.Column("ref", sa.String(500), nullable=False),
        sa.Column("summary", sa.Text()),
        sa.Column("tokens_est", sa.Integer()),
        sa.Column("confidence", sa.Float()),
        sa.Column("meta", JSONB(), nullable=False, server_default=JSON_OBJ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
    )
    op.create_index("ix_context_items_project_kind", "context_items", ["project_id", "kind"])
    op.create_index("ix_context_items_task", "context_items", ["task_id"])

    op.create_table(
        "memories",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id", UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE")
        ),
        sa.Column("scope", sa.String(30), nullable=False, server_default="project"),
        sa.Column("agent_id", UUID(as_uuid=True), sa.ForeignKey("agents.id", ondelete="SET NULL")),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("provenance", sa.String(500)),
        sa.Column("freshness_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
    )
    op.create_index("ix_memories_project_kind", "memories", ["project_id", "kind"])

    op.create_table(
        "worktrees",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("task_id", UUID(as_uuid=True), sa.ForeignKey("tasks.id", ondelete="SET NULL")),
        sa.Column("branch", sa.String(200), nullable=False),
        sa.Column("path", sa.String(1024), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.UniqueConstraint("project_id", "branch", name="uq_worktrees_project_branch"),
    )
    op.create_index("ix_worktrees_task", "worktrees", ["task_id"])

    op.create_table(
        "resources",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id", UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE")
        ),
        sa.Column("kind", sa.String(50), nullable=False),
        sa.Column("key", sa.String(500), nullable=False),
        sa.Column(
            "holder_agent_id", UUID(as_uuid=True), sa.ForeignKey("agents.id", ondelete="SET NULL")
        ),
        sa.Column("holder_session", sa.String(64)),
        sa.Column("ttl_seconds", sa.Integer(), nullable=False, server_default="300"),
        sa.Column("acquired_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("released_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("kind", "key", name="uq_resources_kind_key"),
    )
    op.create_index("ix_resources_expires", "resources", ["expires_at"])


def downgrade() -> None:
    for table in ("resources", "worktrees", "memories", "context_items", "artifacts"):
        op.drop_table(table)
