"""Safe reset of old (nationwide / worldwide) discovery data before the Chennai-only refocus.

Three steps, never combined automatically:

1. `backup`  — consistent SQLite copy (online backup API) + CSV exports + a manifest with row counts.
2. `preview` — exactly which rows would be deleted, per table, and which tables are kept.
3. `execute` — deletes rows ONLY when given (a) a verified backup file and (b) a confirmation phrase
               that repeats the exact row count shown by the preview. Runs in one transaction.

Rules:
- Rows only. Tables, indexes, the schema and `alembic_version` (migration history) are never dropped.
- Kept untouched: sources (source definitions), app_settings, activity_logs (audit), ai_usage_logs,
  action_items, source_runs / discovery_jobs (run history), the new Chennai lead tables, and the
  vendor/partner-programme reference records (opportunities from the `partner_programmes` source).
- Stale "running" jobs are marked failed so nothing resumes them.

CLI (from backend/):
    uv run python -m app.reset preview
    uv run python -m app.reset backup
    uv run python -m app.reset execute --backup data/backups/<file>.db --confirm "DELETE <N> RECORDS"
    uv run python -m app.reset vacuum        # optional: reclaim disk space afterwards
"""

from __future__ import annotations

import csv
import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.config import BACKEND_DIR, get_settings

BACKUP_DIR = BACKEND_DIR / "data" / "backups"

# Opportunities from these sources are reference data, not discovered leads: always kept.
KEEP_OPPORTUNITY_SOURCES = ("partner_programmes",)

# Tables whose rows are never touched by the reset (listed in the preview so the scope is explicit).
PRESERVED_TABLES = (
    "sources", "app_settings", "activity_logs", "ai_usage_logs", "action_items", "source_runs",
    "discovery_jobs", "alembic_version", "chennai_leads", "lead_signals",
)

# Tables exported to CSV alongside the full database copy.
EXPORT_TABLES = ("prospects", "business_chains", "project_leads", "opportunities", "organisations", "contacts",
                 "evidence", "buying_signals", "outreach_drafts")


def _sqlite_path() -> Path:
    url = get_settings().database_url
    if not url.startswith("sqlite:///"):
        raise RuntimeError("Reset tooling supports the SQLite database only")
    return Path(url.removeprefix("sqlite:///"))


# ------------------------------------------------------------------------------------------------
# Scope: what each group deletes. Each entry: (table, WHERE clause or None for all rows).
# Order matters: children first so foreign keys never block or cascade unexpectedly.
# ------------------------------------------------------------------------------------------------
_DISCOVERED_OPPS = (
    "SELECT o.id FROM opportunities o LEFT JOIN sources s ON s.id = o.source_id "
    f"WHERE s.key IS NULL OR s.key NOT IN ({', '.join(repr(k) for k in KEEP_OPPORTUNITY_SOURCES)})"
)
_OPP_CHILD = f"opportunity_id IN ({_DISCOVERED_OPPS})"

GROUPS: dict[str, dict[str, Any]] = {
    "nationwide_directory": {
        "label": "All-India business directory data (OpenStreetMap / Overture scans, multi-branch groups, India-wide news projects)",
        "tables": [
            ("prospects", None),
            ("business_chains", None),
            ("project_leads", None),
            ("prospect_runs", "areas NOT LIKE '%Chennai leads%'"),  # logs of the nationwide scans (Chennai lead runs kept)
        ],
    },
    "opportunity_pipeline": {
        "label": "Worldwide freelance/job-board opportunities (Hacker News, n8n, Make) and everything derived from them. "
                 "Vendor/partner-programme records are kept.",
        "tables": [
            ("outreach_approvals", f"draft_id IN (SELECT id FROM outreach_drafts WHERE {_OPP_CHILD})"),
            ("follow_up_tasks", _OPP_CHILD),
            ("call_tasks", _OPP_CHILD),
            ("outreach_drafts", _OPP_CHILD),
            ("ai_reviews", _OPP_CHILD),
            ("research_tasks", _OPP_CHILD),
            ("opportunity_scores", _OPP_CHILD),
            ("eligibility_assessments", _OPP_CHILD),
            ("eligibility_requirements", _OPP_CHILD),
            ("buying_signals", _OPP_CHILD),
            ("opportunity_relationships", f"source_opportunity_id IN ({_DISCOVERED_OPPS}) OR target_opportunity_id IN ({_DISCOVERED_OPPS})"),
            ("organisation_relationships", f"target_opportunity_id IN ({_DISCOVERED_OPPS})"),
            ("contacts", _OPP_CHILD),
            ("evidence", _OPP_CHILD),
            ("opportunities", f"id IN ({_DISCOVERED_OPPS})"),
            ("raw_records", "id NOT IN (SELECT raw_record_id FROM evidence WHERE raw_record_id IS NOT NULL)"
                            " AND source_id IN (SELECT id FROM sources WHERE key NOT IN "
                            f"({', '.join(repr(k) for k in KEEP_OPPORTUNITY_SOURCES)}))"),
            # Organisations left with no opportunity of their own (evaluated after opportunities are gone).
            ("organisation_relationships", "source_org_id IN (SELECT id FROM organisations WHERE id NOT IN "
                                           "(SELECT organisation_id FROM opportunities WHERE organisation_id IS NOT NULL))"),
            ("contacts", "organisation_id IN (SELECT id FROM organisations WHERE id NOT IN "
                         "(SELECT organisation_id FROM opportunities WHERE organisation_id IS NOT NULL))"),
            ("evidence", "organisation_id IN (SELECT id FROM organisations WHERE id NOT IN "
                         "(SELECT organisation_id FROM opportunities WHERE organisation_id IS NOT NULL))"),
            ("organisations", "id NOT IN (SELECT organisation_id FROM opportunities WHERE organisation_id IS NOT NULL)"),
        ],
    },
}
DEFAULT_GROUPS = tuple(GROUPS)


def _columns(conn: Connection, table: str) -> set[str]:
    return {r[1] for r in conn.execute(text(f'PRAGMA table_info("{table}")'))}


def _where_ok(conn: Connection, table: str, where: str | None) -> bool:
    """Skip a scope entry if its table or referenced column doesn't exist (older/newer schema)."""
    cols = _columns(conn, table)
    if not cols:
        return False
    if where is None:
        return True
    first_col = where.split(" ", 1)[0]
    return first_col in cols


@dataclass
class Preview:
    groups: list[str]
    delete: list[dict[str, Any]] = field(default_factory=list)  # [{group, table, rows}]
    keep: dict[str, int] = field(default_factory=dict)
    kept_opportunities: int = 0
    stale_jobs: int = 0

    @property
    def total(self) -> int:
        return sum(d["rows"] for d in self.delete)

    @property
    def confirm_phrase(self) -> str:
        return f"DELETE {self.total} RECORDS"

    def as_dict(self) -> dict[str, Any]:
        return {
            "groups": {g: GROUPS[g]["label"] for g in self.groups},
            "delete": self.delete,
            "total_rows_to_delete": self.total,
            "kept_tables": self.keep,
            "kept_partner_programme_opportunities": self.kept_opportunities,
            "stale_running_jobs_to_mark_failed": self.stale_jobs,
            "never_touched": "table definitions, indexes, migration history (alembic_version)",
            "confirm_phrase": self.confirm_phrase,
        }


def _count_scope(conn: Connection, groups: tuple[str, ...]) -> list[dict[str, Any]]:
    """Row counts per scope entry, computed by simulating the deletes inside a rolled-back savepoint.

    Later entries depend on earlier ones (e.g. organisations orphaned once opportunities go), so
    counting each WHERE independently would be wrong; simulating keeps preview == execute.
    """
    out: list[dict[str, Any]] = []
    for g in groups:
        for table, where in GROUPS[g]["tables"]:
            if not _where_ok(conn, table, where):
                continue
            if where is None:  # whole table: a count is exact and avoids a large simulated delete
                n = conn.execute(text(f'SELECT count(*) FROM "{table}"')).scalar()
            else:
                n = conn.execute(text(f'DELETE FROM "{table}" WHERE {where}')).rowcount
            out.append({"group": g, "table": table, "rows": int(n or 0)})
    # Merge repeated tables within a group for display.
    merged: dict[tuple[str, str], int] = {}
    for d in out:
        merged[(d["group"], d["table"])] = merged.get((d["group"], d["table"]), 0) + d["rows"]
    return [{"group": g, "table": t, "rows": n} for (g, t), n in merged.items()]


def preview(conn: Connection, groups: tuple[str, ...] = DEFAULT_GROUPS) -> Preview:
    unknown = set(groups) - set(GROUPS)
    if unknown:
        raise ValueError(f"Unknown reset group(s): {', '.join(sorted(unknown))}")
    p = Preview(groups=list(groups))
    tx = conn.begin_nested()
    try:
        p.delete = _count_scope(conn, groups)
    finally:
        tx.rollback()
    for t in PRESERVED_TABLES:
        if _columns(conn, t):
            p.keep[t] = int(conn.execute(text(f'SELECT count(*) FROM "{t}"')).scalar() or 0)
    p.kept_opportunities = int(conn.execute(text(
        "SELECT count(*) FROM opportunities o JOIN sources s ON s.id = o.source_id WHERE s.key IN "
        f"({', '.join(repr(k) for k in KEEP_OPPORTUNITY_SOURCES)})")).scalar() or 0)
    p.stale_jobs = _stale_jobs(conn, count_only=True)
    return p


def _stale_jobs(conn: Connection, *, count_only: bool) -> int:
    n = 0
    for table, col in (("prospect_runs", "status"), ("discovery_jobs", "status"), ("source_runs", "status")):
        if not _columns(conn, table):
            continue
        where = f"{col} IN ('running', 'queued', 'stopping', 'pending')"
        if count_only:
            n += int(conn.execute(text(f"SELECT count(*) FROM {table} WHERE {where}")).scalar() or 0)
        else:
            n += int(conn.execute(text(f"UPDATE {table} SET {col} = 'failed' WHERE {where}")).rowcount or 0)
    return n


# ------------------------------------------------------------------------------------------------
# Backup
# ------------------------------------------------------------------------------------------------
def backup(db_path: Path | None = None, out_dir: Path = BACKUP_DIR, *, export_csv: bool = True) -> dict[str, Any]:
    """Consistent online copy of the SQLite database (safe while the app runs) + CSV exports."""
    db_path = db_path or _sqlite_path()
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = out_dir / f"ioi-{stamp}.db"
    src = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    dst = sqlite3.connect(target)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    check = sqlite3.connect(f"file:{target}?mode=ro", uri=True)
    try:
        integrity = check.execute("PRAGMA quick_check").fetchone()[0]
        counts = {t: check.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0]
                  for (t,) in check.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")}
        exports: dict[str, str] = {}
        if export_csv:
            exp_dir = out_dir / f"export-{stamp}"
            exp_dir.mkdir(exist_ok=True)
            for t in EXPORT_TABLES:
                if t not in counts:
                    continue
                path = exp_dir / f"{t}.csv"
                cur = check.execute(f'SELECT * FROM "{t}"')
                with path.open("w", newline="", encoding="utf-8") as fh:
                    w = csv.writer(fh)
                    w.writerow([d[0] for d in cur.description])
                    for row in cur:
                        w.writerow(row)
                exports[t] = str(path)
    finally:
        check.close()
    if integrity != "ok":
        raise RuntimeError(f"Backup integrity check failed: {integrity}")
    manifest = {"backup": str(target), "source": str(db_path), "created": stamp, "integrity": integrity,
                "row_counts": counts, "csv_exports": exports}
    target.with_suffix(".manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest


def verify_backup(backup_path: Path) -> dict[str, int]:
    """The backup must exist, pass an integrity check and contain the tables being reset."""
    if not backup_path.is_file():
        raise ValueError(f"Backup not found: {backup_path}")
    con = sqlite3.connect(f"file:{backup_path}?mode=ro", uri=True)
    try:
        if con.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise ValueError("Backup failed its integrity check")
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        return {t: con.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0] for t in ("prospects", "opportunities") if t in tables}
    finally:
        con.close()


# ------------------------------------------------------------------------------------------------
# Execute (destructive — guarded)
# ------------------------------------------------------------------------------------------------
class ResetRefused(Exception):
    pass


def execute(conn: Connection, *, backup_path: Path, confirm: str, groups: tuple[str, ...] = DEFAULT_GROUPS,
            actor: str = "owner") -> dict[str, Any]:
    """Delete the previewed rows. Refuses unless the backup verifies and `confirm` matches the preview."""
    try:
        backed_up = verify_backup(backup_path)
    except ValueError as exc:
        raise ResetRefused(str(exc)) from exc
    p = preview(conn, groups)
    if confirm.strip() != p.confirm_phrase:
        raise ResetRefused(f"Confirmation does not match. Type exactly: {p.confirm_phrase}")
    # A backup older than the data it is meant to protect is useless: it must hold at least as many rows.
    live = {t: int(conn.execute(text(f'SELECT count(*) FROM "{t}"')).scalar() or 0) for t in backed_up}
    short = [t for t in backed_up if backed_up[t] < live[t]]
    if short:
        raise ResetRefused(f"Backup is older than the current data ({', '.join(short)} has more rows now). Take a new backup.")

    tables_before = {r[0] for r in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
    deleted: list[dict[str, Any]] = []
    for g in groups:
        for table, where in GROUPS[g]["tables"]:
            if not _where_ok(conn, table, where):
                continue
            n = conn.execute(text(f'DELETE FROM "{table}"' + (f" WHERE {where}" if where else ""))).rowcount
            deleted.append({"group": g, "table": table, "rows": int(n or 0)})
    stale = _stale_jobs(conn, count_only=False)
    tables_after = {r[0] for r in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
    if tables_after != tables_before:  # defensive: DELETE can't drop tables, but never commit if it somehow did
        raise ResetRefused("Table set changed during reset; aborting")
    summary = {"deleted": deleted, "total": sum(d["rows"] for d in deleted), "stale_jobs_marked_failed": stale,
               "backup": str(backup_path), "groups": list(groups)}
    conn.execute(
        text("INSERT INTO activity_logs (actor, action, entity_type, entity_id, detail, created_at) "
             "VALUES (:a, 'data_reset', 'database', NULL, :d, CURRENT_TIMESTAMP)"),
        {"a": actor, "d": json.dumps(summary)},
    )
    return summary


def vacuum(db_path: Path | None = None) -> None:
    con = sqlite3.connect(db_path or _sqlite_path())
    try:
        con.execute("PRAGMA optimize")
        con.execute("VACUUM")
    finally:
        con.close()


def main(argv: list[str] | None = None) -> int:
    import argparse

    from app.db import engine

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("preview", "execute"):
        sp = sub.add_parser(name)
        sp.add_argument("--groups", default=",".join(DEFAULT_GROUPS), help=f"comma list of: {', '.join(GROUPS)}")
        if name == "execute":
            sp.add_argument("--backup", required=True, help="path to a backup made by `backup`")
            sp.add_argument("--confirm", required=True, help='the exact phrase printed by preview, e.g. "DELETE 123 RECORDS"')
    sub.add_parser("backup")
    sub.add_parser("vacuum")
    a = ap.parse_args(argv)

    if a.cmd == "backup":
        print(json.dumps(backup(), indent=2))
        return 0
    if a.cmd == "vacuum":
        vacuum()
        print("VACUUM done")
        return 0
    groups = tuple(g.strip() for g in a.groups.split(",") if g.strip())
    if a.cmd == "preview":
        with engine.connect() as conn:
            print(json.dumps(preview(conn, groups).as_dict(), indent=2))
        return 0
    with engine.begin() as conn:
        try:
            print(json.dumps(execute(conn, backup_path=Path(a.backup), confirm=a.confirm, groups=groups), indent=2))
        except ResetRefused as exc:
            print(f"REFUSED: {exc}")
            raise SystemExit(2) from exc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
