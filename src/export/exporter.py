"""Export the normalized DB to a gzip-compressed JSON snapshot for the mobile app.

The ML model and the full pipeline run on the PC. This module is the PC side of
the mobile "data access layer": it dumps the already-categorized transactions
into one compact JSON file that the phone downloads and caches offline.

Reads the DB read-only (no locks), stdlib-only (no pandas/sqlalchemy needed).
"""

import gzip
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DB_DIR = BASE_DIR / "data" / "db"
DB_PATH = DB_DIR / "normalized.db"
DB_PATH_V2 = DB_DIR / "normalized_v2.db"
EXPORT_DIR = BASE_DIR / "data" / "export"
EXPORT_PATH = EXPORT_DIR / "snapshot.json.gz"

SCHEMA_VERSION = 1


def active_db_path() -> Path:
    """Return the active normalized DB, honouring the *_v2 convention."""
    env = os.environ.get("GESTOR_NORMALIZED_DB")
    if env:
        return Path(env)
    if DB_PATH_V2.exists():
        return DB_PATH_V2
    return DB_PATH


def build_snapshot(db_path: Path = None) -> dict:
    """Read categorized transactions and categories into a plain dict."""
    db_path = Path(db_path or active_db_path())
    if not db_path.exists():
        raise FileNotFoundError(
            f"Normalized DB not found: {db_path}. Run the pipeline first."
        )

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        categories = [
            dict(row)
            for row in conn.execute(
                "SELECT id, name, keywords FROM categories ORDER BY id"
            )
        ]
        transactions = [
            dict(row)
            for row in conn.execute(
                "SELECT id, date, description, amount, category_id, category_name, source "
                "FROM transactions "
                "WHERE category_name IS NOT NULL "
                "ORDER BY date"
            )
        ]
    finally:
        conn.close()

    return {
        "schema_version": SCHEMA_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "categories": categories,
        "transactions": transactions,
    }


def export(db_path: Path = None, out_path: Path = None, verbose: bool = True) -> Path:
    """Write snapshot.json.gz and return its path."""
    snapshot = build_snapshot(db_path)
    out_path = Path(out_path or EXPORT_PATH)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with gzip.open(out_path, "wt", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False)

    if verbose:
        size_kb = out_path.stat().st_size / 1024
        print(f"Exported {len(snapshot['transactions'])} transactions to {out_path} ({size_kb:.1f} KB)")
    return out_path


if __name__ == "__main__":
    export()
