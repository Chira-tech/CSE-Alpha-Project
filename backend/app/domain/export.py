"""
R1 Phase 3 — export and backup. The user's own words: "I want to have a
backup in case the system loses its integrity." This is disaster
recovery, not a convenience feature, so `backup_tables` (T3.2) is the
real recovery artefact and is verified by actually restoring it
(`scripts/verify_backup_restore.py`), not just written and trusted.

Generic over EVERY table in `Base.metadata` — never a hand-maintained
table list that could silently drift from the real schema as new models
are added (`app.models.__init__`'s own docstring already establishes this
"import every model so metadata is complete" discipline; this module
just reads that same metadata rather than re-declaring it).
"""
from __future__ import annotations

import datetime as dt
import decimal
import enum
import hashlib
import io
import json
import zipfile
from dataclasses import dataclass

from sqlalchemy import Table, select
from sqlalchemy.orm import Session

from app.db.base import Base

SCHEMA_VERSION = "1"


def _json_safe(value: object) -> object:
    if value is None or isinstance(value, (str, int, bool, float)):
        return value
    if isinstance(value, decimal.Decimal):
        # A string, not a float — a backup must reproduce the exact
        # decimal value on restore, and float64 cannot always do that
        # (the whole reason this project stores money as Decimal/Numeric
        # everywhere else).
        return str(value)
    if isinstance(value, (dt.datetime, dt.date)):
        return value.isoformat()
    if isinstance(value, enum.Enum):
        return value.value
    return str(value)  # last resort — never raise and abort a real backup


def all_tables() -> list[Table]:
    """Every table this system actually has, straight from the real
    schema metadata — see this module's own docstring for why never a
    hand-maintained list."""
    return list(Base.metadata.sorted_tables)


@dataclass(frozen=True)
class TableManifestEntry:
    row_count: int
    sha256: str


def build_backup_zip(db: Session) -> tuple[bytes, dict[str, TableManifestEntry]]:
    """One newline-delimited-JSON file per table inside a zip, plus a
    `manifest.json` with a row count and a SHA-256 checksum per table —
    `scripts/verify_backup_restore.py` restores this and checks both
    against the manifest, which is the actual disaster-recovery
    guarantee, not just "a file exists."."""
    manifest: dict[str, TableManifestEntry] = {}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for table in all_tables():
            rows = db.execute(select(table)).mappings().all()
            lines = []
            for row in rows:
                record = {k: _json_safe(v) for k, v in row.items()}
                lines.append(json.dumps(record, sort_keys=True))
            content = "\n".join(lines)
            content_bytes = content.encode("utf-8")
            checksum = hashlib.sha256(content_bytes).hexdigest()
            manifest[table.name] = TableManifestEntry(row_count=len(rows), sha256=checksum)
            zf.writestr(f"{table.name}.ndjson", content_bytes)

        manifest_payload = {
            "schema_version": SCHEMA_VERSION,
            "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "tables": {
                name: {"row_count": entry.row_count, "sha256": entry.sha256}
                for name, entry in manifest.items()
            },
        }
        zf.writestr("manifest.json", json.dumps(manifest_payload, indent=2, sort_keys=True))

    return buf.getvalue(), manifest
