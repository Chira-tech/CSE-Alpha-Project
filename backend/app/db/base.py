from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base for all ORM models. Import every model module in
    alembic/env.py so autogenerate can see the full schema."""
