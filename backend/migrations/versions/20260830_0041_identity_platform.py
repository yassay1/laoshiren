"""Phase 7 identity platform tables."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260830_0041"
down_revision: str | None = "20260830_0040"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    user_status = postgresql.ENUM(
        "ACTIVE", "DELETING", "DELETED", name="user_status", create_type=False
    )
    device_platform = postgresql.ENUM(
        "HARMONYOS", "OTHER", name="device_platform", create_type=False
    )
    user_status.create(op.get_bind(), checkfirst=True)
    device_platform.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "users",
        sa.Column("status", user_status, server_default="ACTIVE", nullable=False),
    )
    op.add_column(
        "users",
        sa.Column("external_subject", sa.String(length=200), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "uq_users_external_subject",
        "users",
        ["external_subject"],
        unique=True,
        postgresql_where=sa.text("external_subject IS NOT NULL"),
    )

    op.create_table(
        "devices",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("platform", device_platform, nullable=False),
        sa.Column("timezone_name", sa.String(length=100), nullable=False),
        sa.Column("active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_devices_user_active", "devices", ["user_id", "active"])

    op.execute(
        """
        INSERT INTO devices (
            id, user_id, platform, timezone_name, active, last_seen_at, created_at, updated_at
        )
        SELECT DISTINCT
            pe.device_id,
            pe.user_id,
            'HARMONYOS'::device_platform,
            'UTC',
            TRUE,
            NOW(),
            NOW(),
            NOW()
        FROM push_endpoints pe
        WHERE NOT EXISTS (SELECT 1 FROM devices d WHERE d.id = pe.device_id)
        """
    )

    op.create_foreign_key(
        "push_endpoints_device_id_fkey",
        "push_endpoints",
        "devices",
        ["device_id"],
        ["id"],
    )

    op.create_table(
        "business_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=True),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_business_sessions_token_hash"),
    )
    op.create_index("ix_business_sessions_user", "business_sessions", ["user_id", "expires_at"])


def downgrade() -> None:
    op.drop_index("ix_business_sessions_user", table_name="business_sessions")
    op.drop_table("business_sessions")
    op.drop_constraint("push_endpoints_device_id_fkey", "push_endpoints", type_="foreignkey")
    op.drop_index("ix_devices_user_active", table_name="devices")
    op.drop_table("devices")
    op.drop_index("uq_users_external_subject", table_name="users")
    op.drop_column("users", "updated_at")
    op.drop_column("users", "external_subject")
    op.drop_column("users", "status")
    op.execute("DROP TYPE IF EXISTS device_platform")
    op.execute("DROP TYPE IF EXISTS user_status")
