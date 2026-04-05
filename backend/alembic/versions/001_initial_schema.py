"""Initial schema — workspaces, API keys, prompt versions, rate limits, alert rules.

Revision ID: 001
Revises: None
Create Date: 2026-03-25
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "workspaces",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("slug", sa.String(), nullable=False, unique=True),
        sa.Column("description", sa.String(), nullable=False, server_default=""),
        sa.Column("created_at", sa.String(), nullable=False),
    )

    op.create_table(
        "api_keys",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("workspace_id", sa.String(), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("key_hash", sa.String(), nullable=False),
        sa.Column("key_prefix", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
    )
    op.create_index("idx_api_keys_hash", "api_keys", ["key_hash"])
    op.create_index("idx_api_keys_workspace", "api_keys", ["workspace_id"])

    op.create_table(
        "prompt_versions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("model", sa.String(), nullable=False, server_default="gpt-4o-mini"),
        sa.Column("temperature", sa.Float(), server_default="0.7"),
        sa.Column("max_tokens", sa.Integer(), server_default="1024"),
        sa.Column("workspace_id", sa.String(), nullable=False, server_default="default"),
        sa.Column("version_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("parent_id", sa.String(), nullable=True),
        sa.Column("tags", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("is_published", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.String(), nullable=False),
    )
    op.create_index("idx_prompt_versions_workspace", "prompt_versions", ["workspace_id"])
    op.create_index("idx_prompt_versions_name", "prompt_versions", ["name", "workspace_id"])

    op.create_table(
        "playground_rate_limits",
        sa.Column("key", sa.String(), primary_key=True),
        sa.Column("count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("window_start", sa.String(), nullable=False),
    )

    op.create_table(
        "alert_rules",
        sa.Column("rule_id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("condition", sa.String(), nullable=False),
        sa.Column("window_minutes", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("channels", sa.Text(), nullable=False, server_default='["webhook"]'),
        sa.Column("webhook_url", sa.String(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("last_fired", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("alert_rules")
    op.drop_table("playground_rate_limits")
    op.drop_index("idx_prompt_versions_name", "prompt_versions")
    op.drop_index("idx_prompt_versions_workspace", "prompt_versions")
    op.drop_table("prompt_versions")
    op.drop_index("idx_api_keys_workspace", "api_keys")
    op.drop_index("idx_api_keys_hash", "api_keys")
    op.drop_table("api_keys")
    op.drop_table("workspaces")
