"""TASK 1.1: job_runs table for the manual Run Capture control

Revision ID: 0017
Revises: 0016
Create Date: 2026-08-18

See app/models/job_run.py for the full design, including why the
concurrency guard is enforced in app.jobs.runner rather than a Postgres-
style partial unique index (this project's real database is SQLite).
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: Union[str, None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "job_runs",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("job", sa.String(50), nullable=False),
        sa.Column("trigger", sa.String(10), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("progress_pct", sa.Numeric(5, 2), nullable=False, server_default="0"),
        sa.Column("progress_note", sa.String(200), nullable=True),
        sa.Column("rows_written", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("cancel_requested", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_job_runs_job", "job_runs", ["job"])
    op.create_index("ix_job_runs_status", "job_runs", ["status"])


def downgrade() -> None:
    op.drop_index("ix_job_runs_status", table_name="job_runs")
    op.drop_index("ix_job_runs_job", table_name="job_runs")
    op.drop_table("job_runs")
