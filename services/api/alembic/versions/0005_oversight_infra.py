"""durable core: oversight (decisions, reviews, validations, HITL) + infra configs

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-14
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

NOW = sa.func.now()
JSON_OBJ = sa.text("'{}'::jsonb")
JSON_ARR = sa.text("'[]'::jsonb")


def upgrade() -> None:
    op.create_table(
        "decisions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id", UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE")
        ),
        sa.Column("task_id", UUID(as_uuid=True), sa.ForeignKey("tasks.id", ondelete="SET NULL")),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("rationale", sa.Text()),
        sa.Column("kind", sa.String(50), nullable=False, server_default="architecture"),
        sa.Column("made_by", sa.String(200)),
        sa.Column("status", sa.String(30), nullable=False, server_default="proposed"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
    )
    op.create_index("ix_decisions_project", "decisions", ["project_id"])

    op.create_table(
        "reviews",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "decision_id", UUID(as_uuid=True), sa.ForeignKey("decisions.id", ondelete="SET NULL")
        ),
        sa.Column("task_id", UUID(as_uuid=True), sa.ForeignKey("tasks.id", ondelete="SET NULL")),
        sa.Column("reviewer_role", sa.String(50), nullable=False),
        sa.Column("verdict", sa.String(30), nullable=False, server_default="unknown"),
        sa.Column("summary", sa.Text()),
        sa.Column("rounds", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("model", sa.String(200)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
    )
    op.create_index("ix_reviews_decision", "reviews", ["decision_id"])
    op.create_index("ix_reviews_task", "reviews", ["task_id"])

    op.create_table(
        "validations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id", UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE")
        ),
        sa.Column("task_id", UUID(as_uuid=True), sa.ForeignKey("tasks.id", ondelete="SET NULL")),
        sa.Column(
            "acceptance_criterion_id",
            UUID(as_uuid=True),
            sa.ForeignKey("acceptance_criteria.id", ondelete="SET NULL"),
        ),
        sa.Column("kind", sa.String(50), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="pending"),
        sa.Column("evidence_artifact_id", UUID(as_uuid=True)),
        sa.Column("detail", JSONB(), nullable=False, server_default=JSON_OBJ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
    )
    op.create_index("ix_validations_project_kind", "validations", ["project_id", "kind"])
    op.create_index("ix_validations_criterion", "validations", ["acceptance_criterion_id"])

    op.create_table(
        "hitl_requests",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id", UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE")
        ),
        sa.Column("task_id", UUID(as_uuid=True), sa.ForeignKey("tasks.id", ondelete="SET NULL")),
        sa.Column("kind", sa.String(50), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("choices", JSONB(), nullable=False, server_default=JSON_ARR),
        sa.Column("risk", sa.String(30), nullable=False, server_default="medium"),
        sa.Column("status", sa.String(30), nullable=False, server_default="pending"),
        sa.Column("decided_by", sa.String(200)),
        sa.Column("decision_note", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_hitl_requests_project_status", "hitl_requests", ["project_id", "status"])
    op.create_index("ix_hitl_requests_task", "hitl_requests", ["task_id"])

    op.create_table(
        "runtime_instances",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id", UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE")
        ),
        sa.Column("kind", sa.String(50), nullable=False),
        sa.Column("reference", sa.String(300), nullable=False),
        sa.Column("ports", JSONB(), nullable=False, server_default=JSON_ARR),
        sa.Column("status", sa.String(30), nullable=False, server_default="running"),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("stopped_at", sa.DateTime(timezone=True)),
    )

    op.create_table(
        "toolchains",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("language", sa.String(50), nullable=False),
        sa.Column("config", JSONB(), nullable=False),
        sa.Column("source", sa.String(30), nullable=False, server_default="project_override"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.UniqueConstraint("project_id", "language", name="uq_toolchains_project_language"),
    )


def downgrade() -> None:
    for table in (
        "toolchains",
        "runtime_instances",
        "hitl_requests",
        "validations",
        "reviews",
        "decisions",
    ):
        op.drop_table(table)
