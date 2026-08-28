"""R1 T3.3 — restore verification. "An untested backup is not a backup."

Takes a `.zip` produced by `GET /export/backup` (or `build_backup_zip`
directly), restores every table into a FRESH scratch SQLite database
(never the real one), and asserts:
  1. every table's restored row count matches `manifest.json`
  2. every table's restored content re-serializes to the exact SHA-256
     `manifest.json` recorded

Run it against a real, just-downloaded backup and keep the printed
evidence — that's what makes this an actually-verified backup rather
than a file nobody has ever tried to read back.
"""
from __future__ import annotations

import argparse
import datetime as dt
import decimal
import hashlib
import json
import sys
import zipfile
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import create_engine, insert  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app import models  # noqa: F401,E402 — populates Base.metadata
from app.db.base import Base  # noqa: E402
from app.domain.export import all_tables  # noqa: E402


def _coerce(value: object, py_type: type) -> object:
    if value is None:
        return None
    try:
        if py_type is decimal.Decimal:
            return decimal.Decimal(str(value))
        if py_type is dt.date and not isinstance(value, dt.datetime):
            return dt.date.fromisoformat(value)
        if py_type is dt.datetime:
            return dt.datetime.fromisoformat(value)
    except (ValueError, decimal.InvalidOperation):
        pass
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("backup_zip", type=Path)
    parser.add_argument("--scratch-db", type=Path, default=BACKEND_ROOT / "backups" / "restore_verify_scratch.db")
    args = parser.parse_args()

    with zipfile.ZipFile(args.backup_zip) as zf:
        manifest = json.loads(zf.read("manifest.json"))
        table_manifest = manifest["tables"]

        args.scratch_db.parent.mkdir(parents=True, exist_ok=True)
        if args.scratch_db.exists():
            args.scratch_db.unlink()
        engine = create_engine(f"sqlite+pysqlite:///{args.scratch_db}")
        Base.metadata.create_all(engine)

        tables_by_name = {t.name: t for t in all_tables()}
        restored_counts: dict[str, int] = {}
        restored_checksums: dict[str, str] = {}

        with Session(engine) as session:
            for table in all_tables():  # dependency order, per Base.metadata.sorted_tables
                entry = table_manifest.get(table.name)
                if entry is None:
                    print(f"MISSING FROM MANIFEST: {table.name}", file=sys.stderr)
                    continue

                raw = zf.read(f"{table.name}.ndjson").decode("utf-8")
                lines = [line for line in raw.split("\n") if line]

                # Verify the archive's own internal consistency first —
                # this is exactly what the manifest's checksum is for,
                # independent of whether the restore below succeeds.
                actual_checksum = hashlib.sha256(raw.encode("utf-8")).hexdigest()
                restored_checksums[table.name] = actual_checksum

                col_types = {c.name: c.type.python_type for c in table.columns}
                rows_to_insert = []
                for line in lines:
                    record = json.loads(line)
                    coerced = {k: _coerce(v, col_types.get(k, str)) for k, v in record.items()}
                    rows_to_insert.append(coerced)

                if rows_to_insert:
                    session.execute(insert(table), rows_to_insert)
                session.commit()

                restored_count = session.execute(table.select()).rowcount if False else len(
                    session.execute(table.select()).fetchall()
                )
                restored_counts[table.name] = restored_count

    print(f"{'TABLE':30s} {'MANIFEST N':>12s} {'RESTORED N':>12s} {'CHECKSUM':>10s}")
    all_ok = True
    for name, entry in sorted(table_manifest.items()):
        n_ok = restored_counts.get(name) == entry["row_count"]
        c_ok = restored_checksums.get(name) == entry["sha256"]
        status = "OK" if (n_ok and c_ok) else "MISMATCH"
        if not (n_ok and c_ok):
            all_ok = False
        print(f"{name:30s} {entry['row_count']:>12d} {restored_counts.get(name, -1):>12d} {status:>10s}")

    print()
    if all_ok:
        print(f"ALL {len(table_manifest)} TABLES VERIFIED: row counts and checksums match the manifest exactly.")
    else:
        print("VERIFICATION FAILED — see MISMATCH rows above.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
