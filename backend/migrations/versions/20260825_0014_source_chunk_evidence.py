"""Add page provenance and semantic vectors to Source evidence chunks."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "20260825_0014"
down_revision: str | None = "20260825_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("source_chunks", sa.Column("page_number", sa.Integer()))
    op.add_column("source_chunks", sa.Column("embedding", Vector(1536)))
    op.create_index(
        "ix_source_chunks_embedding_hnsw",
        "source_chunks",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


def downgrade() -> None:
    op.drop_index("ix_source_chunks_embedding_hnsw", table_name="source_chunks")
    op.drop_column("source_chunks", "embedding")
    op.drop_column("source_chunks", "page_number")
