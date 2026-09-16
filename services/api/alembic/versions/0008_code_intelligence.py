"""Phase 5: code intelligence (symbols + embeddings) and model cost ledger

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-15

- `symbol_files`: one row per indexed file (language + content hash) driving
  incremental re-indexing (PERF-008).
- `symbols`: structural symbols from tree-sitter/ast extraction, with a pgvector
  embedding column for hybrid retrieval (spec: lexical first, embeddings as one ranker).
- `model_invocations`: per-call token/cost accounting (spec §32 budgets).
"""

from __future__ import annotations

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

_EMBEDDING_DIM = 256


def upgrade() -> None:
    # The compose image (pgvector/pgvector:pg16) ships the extension.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "symbol_files",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("path", sa.String(1024), nullable=False),
        sa.Column("language", sa.String(30), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("symbol_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "indexed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("project_id", "path", name="uq_symbol_files_project_path"),
    )
    op.create_index("ix_symbol_files_project", "symbol_files", ["project_id"])

    op.create_table(
        "symbols",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "file_id",
            UUID(as_uuid=True),
            sa.ForeignKey("symbol_files.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("parent", sa.String(300), nullable=True),
        sa.Column("start_line", sa.Integer(), nullable=False),
        sa.Column("end_line", sa.Integer(), nullable=False),
        sa.Column("signature", sa.Text(), nullable=True),
        sa.Column("doc", sa.Text(), nullable=True),
        sa.Column("embedding", Vector(_EMBEDDING_DIM), nullable=True),
    )
    op.create_index("ix_symbols_project_name", "symbols", ["project_id", "name"])
    op.create_index("ix_symbols_file", "symbols", ["file_id"])
    op.create_index("ix_symbols_project_kind", "symbols", ["project_id", "kind"])

    op.create_table(
        "model_invocations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "task_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tasks.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "agent_id",
            UUID(as_uuid=True),
            sa.ForeignKey("agents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("role", sa.String(50), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("model", sa.String(200), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completion_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Numeric(12, 6), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_model_invocations_task", "model_invocations", ["task_id", "created_at"])
    op.create_index(
        "ix_model_invocations_project", "model_invocations", ["project_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_table("model_invocations")
    op.drop_table("symbols")
    op.drop_table("symbol_files")
    # The `vector` extension is intentionally left installed: dropping it would
    # break any other database objects using it.
