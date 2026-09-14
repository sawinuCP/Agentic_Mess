"""durable core: tasks, attempts, agent sessions, messages

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-14
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

NOW = sa.func.now()
JSON_OBJ = sa.text("'{}'::jsonb")
JSON_ARR = sa.text("'[]'::jsonb")


def upgrade() -> None:
    op.create_table(
        "tasks",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("plan_id", UUID(as_uuid=True), sa.ForeignKey("plans.id", ondelete="SET NULL")),
        sa.Column(
            "requirement_id",
            UUID(as_uuid=True),
            sa.ForeignKey("requirements.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "parent_task_id", UUID(as_uuid=True), sa.ForeignKey("tasks.id", ondelete="SET NULL")
        ),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("request", sa.Text(), nullable=False),
        sa.Column("expected_output", sa.Text()),
        sa.Column("constraints", JSONB(), nullable=False, server_default=JSON_OBJ),
        sa.Column("acceptance_criteria", JSONB(), nullable=False, server_default=JSON_ARR),
        sa.Column("allowed_tools", JSONB(), nullable=False, server_default=JSON_ARR),
        sa.Column("context_refs", JSONB(), nullable=False, server_default=JSON_ARR),
        sa.Column("retry_policy", JSONB(), nullable=False, server_default=JSON_OBJ),
        sa.Column("payload", JSONB(), nullable=False, server_default=JSON_OBJ),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("status", sa.String(30), nullable=False, server_default="pending"),
        sa.Column("deadline", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
    )
    op.create_index("ix_tasks_project_status", "tasks", ["project_id", "status"])
    op.create_index("ix_tasks_plan", "tasks", ["plan_id"])
    op.create_index("ix_tasks_requirement", "tasks", ["requirement_id"])
    op.create_index("ix_tasks_parent", "tasks", ["parent_task_id"])

    op.create_table(
        "task_dependencies",
        sa.Column(
            "task_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tasks.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "depends_on_task_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tasks.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.UniqueConstraint("task_id", "depends_on_task_id", name="uq_task_dependency"),
    )
    op.create_index("ix_task_dependencies_depends_on", "task_dependencies", ["depends_on_task_id"])

    op.create_table(
        "task_attempts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "task_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("agent_id", UUID(as_uuid=True), sa.ForeignKey("agents.id", ondelete="SET NULL")),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("outcome", sa.String(30)),
        sa.Column("failure_class", sa.String(50)),
        sa.Column("failure_detail", sa.Text()),
        sa.Column("evidence_artifact_ids", JSONB(), nullable=False, server_default=JSON_ARR),
        sa.UniqueConstraint("task_id", "attempt_number", name="uq_task_attempt_number"),
    )
    op.create_index("ix_task_attempts_task", "task_attempts", ["task_id"])

    op.create_table(
        "agent_sessions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "agent_id",
            UUID(as_uuid=True),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("runtime", sa.String(50), nullable=False, server_default="local"),
        sa.Column("status", sa.String(30), nullable=False, server_default="running"),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_agent_sessions_agent", "agent_sessions", ["agent_id"])

    op.create_table(
        "messages",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("conversation_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "sender_agent_id", UUID(as_uuid=True), sa.ForeignKey("agents.id", ondelete="SET NULL")
        ),
        sa.Column(
            "recipient_agent_id",
            UUID(as_uuid=True),
            sa.ForeignKey("agents.id", ondelete="SET NULL"),
        ),
        sa.Column("task_id", UUID(as_uuid=True), sa.ForeignKey("tasks.id", ondelete="SET NULL")),
        sa.Column("type", sa.String(50), nullable=False),
        sa.Column("payload", JSONB(), nullable=False, server_default=JSON_OBJ),
        sa.Column("payload_ref", UUID(as_uuid=True)),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("correlation_id", sa.String(64)),
        sa.Column("reply_to", UUID(as_uuid=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_messages_conversation", "messages", ["conversation_id"])
    op.create_index("ix_messages_recipient", "messages", ["recipient_agent_id", "created_at"])
    op.create_index("ix_messages_correlation", "messages", ["correlation_id"])


def downgrade() -> None:
    for table in ("messages", "agent_sessions", "task_attempts", "task_dependencies", "tasks"):
        op.drop_table(table)
