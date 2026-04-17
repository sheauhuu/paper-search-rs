"""JCR data loader — SQLite primary, CSV fallback.

Loads ShowJCR data into a JcrIndex for fast ISSN/journal lookups.
Primary: read from jcr.db (SQLite) with SQL JOIN.
Fallback: read CSV files and build index manually.
"""

from __future__ import annotations

import csv
import os
import re
import sqlite3
from pathlib import Path
from typing import Optional

from loguru import logger

from .models import JcrEntry, JcrIndex, _normalize_issn


def load_jcr_index(data_dir: str) -> JcrIndex:
    """Load JCR index from data_dir. Tries SQLite first, then CSV fallback.

    data_dir: path to directory containing jcr.db or CSV files
    """
    index = JcrIndex()
    db_path = Path(data_dir) / "jcr.db"

    if db_path.is_file():
        try:
            _load_from_sqlite(db_path, index)
            logger.info(f"JCR index loaded from SQLite: {index.size} entries")
            return index
        except Exception as e:
            logger.warning(f"SQLite load failed ({e}), falling back to CSV")

    # CSV fallback
    csv_dir = Path(data_dir)
    if csv_dir.is_dir() and any(csv_dir.glob("JCR*UTF8.csv")):
        _load_from_csv(csv_dir, index)
        logger.info(f"JCR index loaded from CSV: {index.size} entries")
        return index

    logger.warning(f"No JCR data found in {data_dir}")
    return index


# ── SQLite loader ─────────────────────────────────────────────────────────

def _load_from_sqlite(db_path: Path, index: JcrIndex) -> None:
    """Load from ShowJCR's jcr.db using SQL JOINs."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Detect available tables
    tables = {row[0] for row in cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}

    # 1. JCR IF data — find latest year table
    jcr_table = _find_latest_table(tables, "JCR")
    if jcr_table:
        _load_jcr_sqlite(cursor, jcr_table, index)

    # 2. 中科院分区 (FQBJCR) — find latest year
    fqb_table = _find_latest_table(tables, "FQBJCR")
    if fqb_table:
        _load_cas_sqlite(cursor, fqb_table, index)

    # 3. 中科院最新分区 (XR)
    xr_table = _find_latest_table(tables, "XR")
    if xr_table:
        _load_xr_sqlite(cursor, xr_table, index)

    # 4. CCF
    ccf_table = _find_latest_table(tables, "CCF")
    if ccf_table:
        _load_ccf_sqlite(cursor, ccf_table, index)

    # 5. 预警期刊 (GJQKYJMD)
    warning_table = _find_latest_table(tables, "GJQKYJMD")
    if warning_table:
        _load_warning_sqlite(cursor, warning_table, index)

    conn.close()


def _find_latest_table(tables: set[str], prefix: str) -> Optional[str]:
    """Find the table with the highest year for a given prefix."""
    candidates = []
    for t in tables:
        if t.upper().startswith(prefix.upper()):
            candidates.append(t)
    if not candidates:
        return None
    # Sort by trailing year number, descending
    def _year(t: str) -> int:
        m = re.search(r"(\d{4})", t)
        return int(m.group(1)) if m else 0
    candidates.sort(key=_year, reverse=True)
    return candidates[0]


def _load_jcr_sqlite(cursor: sqlite3.Cursor, table: str, index: JcrIndex) -> None:
    """Load JCR IF data from SQLite table."""
    try:
        rows = cursor.execute(f"SELECT * FROM [{table}]").fetchall()
        cols = [d[0] for d in cursor.description]
        for row in rows:
            r = dict(zip(cols, row))
            issn = _normalize_issn(r.get("ISSN", ""))
            eissn = _normalize_issn(r.get("EISSN") or r.get("eISSN", ""))
            journal = r.get("Journal", "")

            # Parse IF — may be string like "232.4" or "<0.1"
            if_raw = r.get("IF(2024)") or r.get("IF(2023)") or r.get("IF(2022)") or ""
            impact_factor = _parse_if(if_raw)

            # Detect quartile column
            quartile = ""
            for k in r:
                if k.startswith("IF Quartile"):
                    quartile = str(r[k] or "")
                    break

            rank = ""
            for k in r:
                if k.startswith("IF Rank"):
                    rank = str(r[k] or "")
                    break

            category = r.get("Category", "") or r.get("Web of Science", "")

            entry = JcrEntry(
                issn=issn,
                journal=journal,
                impact_factor=impact_factor,
                jcr_quartile=quartile or None,
                jcr_rank=rank or None,
                jcr_category=category or None,
            )
            index.add(entry)
            if eissn and eissn != issn:
                index.add_issn_alias(eissn, entry)

        # Store year
        m = re.search(r"(\d{4})", table)
        if m:
            index._loaded_year = int(m.group(1))

    except Exception as e:
        logger.warning(f"Error loading JCR table {table}: {e}")


def _load_cas_sqlite(cursor: sqlite3.Cursor, table: str, index: JcrIndex) -> None:
    """Load 中科院分区 data and merge into existing entries."""
    try:
        rows = cursor.execute(f"SELECT * FROM [{table}]").fetchall()
        cols = [d[0] for d in cursor.description]
        for row in rows:
            r = dict(zip(cols, row))
            # ISSN/EISSN is a combined field like "2649-664X/2649-6100"
            issn_raw = r.get("ISSN/EISSN") or r.get("ISSN") or ""
            issns = _parse_combined_issn(issn_raw)
            journal = r.get("Journal", "")
            cas_q = str(r.get("大类分区", "") or "")
            cas_cat = str(r.get("大类", "") or "")

            # Sub-categories
            subs: list[str] = []
            for k in r:
                if k.startswith("小类") and "分区" not in k:
                    v = r[k]
                    if v:
                        subs.append(str(v))

            # Find or create entry
            entry = None
            for issn in issns:
                entry = index.lookup_by_issn(issn)
                if entry:
                    break
            if not entry and journal:
                entry = index.lookup_by_journal(journal)

            if entry:
                entry.cas_quartile = cas_q or entry.cas_quartile
                entry.cas_category = cas_cat or entry.cas_category
                if subs:
                    entry.cas_sub_categories = subs
            else:
                # Create new entry for CAS-only journals
                entry = JcrEntry(
                    issn=issns[0] if issns else "",
                    journal=journal,
                    cas_quartile=cas_q or None,
                    cas_category=cas_cat or None,
                    cas_sub_categories=subs,
                )
                index.add(entry)
                for issn in issns[1:]:
                    index.add_issn_alias(issn, entry)

    except Exception as e:
        logger.warning(f"Error loading CAS table {table}: {e}")


def _load_xr_sqlite(cursor: sqlite3.Cursor, table: str, index: JcrIndex) -> None:
    """Load XR (中科院最新) data — mainly for Chinese journal names."""
    try:
        rows = cursor.execute(f"SELECT * FROM [{table}]").fetchall()
        cols = [d[0] for d in cursor.description]
        for row in rows:
            r = dict(zip(cols, row))
            issn = _normalize_issn(r.get("ISSN", ""))
            eissn = _normalize_issn(r.get("EISSN", ""))
            journal = r.get("Journal", "")

            # Merge into existing
            entry = index.lookup_by_issn(issn) or index.lookup_by_issn(eissn)
            if not entry and journal:
                entry = index.lookup_by_journal(journal)

            # XR has newer 分区 data, prefer it
            if entry:
                # Update cas_quartile from XR if available
                for k in r:
                    if "分区" in k and r[k]:
                        val = str(r[k])
                        # XR 分区 format: "1 区" or "1"
                        q = val.strip().replace("区", "").strip()
                        if q in ("1", "2", "3", "4"):
                            entry.cas_quartile = q
                            break
    except Exception as e:
        logger.warning(f"Error loading XR table {table}: {e}")


def _load_ccf_sqlite(cursor: sqlite3.Cursor, table: str, index: JcrIndex) -> None:
    """Load CCF recommendation data."""
    try:
        rows = cursor.execute(f"SELECT * FROM [{table}]").fetchall()
        cols = [d[0] for d in cursor.description]
        for row in rows:
            r = dict(zip(cols, row))
            journal = r.get("Journal", "")
            ccf_rank = ""
            ccf_field = ""

            for k in r:
                val = str(r[k] or "")
                # CCF rank is in "CCF推荐类型" (e.g. "A类") or "T分区" (e.g. "T1")
                if "推荐类型" in k:
                    if "A类" in val or "A 类" in val:
                        ccf_rank = "A"
                    elif "B类" in val or "B 类" in val:
                        ccf_rank = "B"
                    elif "C类" in val or "C 类" in val:
                        ccf_rank = "C"
                elif "T分区" in k:
                    if not ccf_rank and val.startswith("T"):
                        ccf_rank = val  # "T1", "T2", etc.
                # Also check 推荐类别 for A/B/C as fallback
                if "推荐类别" in k and not ccf_rank:
                    if "A类" in val or "A 类" in val:
                        ccf_rank = "A"
                    elif "B类" in val or "B 类" in val:
                        ccf_rank = "B"
                    elif "C类" in val or "C 类" in val:
                        ccf_rank = "C"
                if "领域" in k and "类别" not in k:
                    ccf_field = str(r[k] or "")

            if not journal:
                continue

            entry = index.lookup_by_journal(journal)
            if entry:
                entry.ccf_rank = ccf_rank or entry.ccf_rank
                entry.ccf_field = ccf_field or entry.ccf_field
            else:
                entry = JcrEntry(
                    journal=journal,
                    ccf_rank=ccf_rank or None,
                    ccf_field=ccf_field or None,
                )
                index.add(entry)
    except Exception as e:
        logger.warning(f"Error loading CCF table {table}: {e}")


def _load_warning_sqlite(cursor: sqlite3.Cursor, table: str, index: JcrIndex) -> None:
    """Load 期刊预警 data."""
    try:
        rows = cursor.execute(f"SELECT * FROM [{table}]").fetchall()
        cols = [d[0] for d in cursor.description]
        for row in rows:
            r = dict(zip(cols, row))
            journal = r.get("Journal", "")
            reason = ""
            for k in r:
                if "预警" in k:
                    reason = str(r[k] or "")
                    break

            if not journal:
                continue
            entry = index.lookup_by_journal(journal)
            if entry:
                entry.is_warning = True
                entry.warning_reason = reason or entry.warning_reason
    except Exception as e:
        logger.warning(f"Error loading warning table {table}: {e}")


# ── CSV fallback loader ───────────────────────────────────────────────────

def _load_from_csv(csv_dir: Path, index: JcrIndex) -> None:
    """Load JCR data from CSV files when SQLite DB is unavailable."""

    # 1. JCR IF
    jcr_files = sorted(csv_dir.glob("JCR*UTF8.csv"), reverse=True)
    if jcr_files:
        _load_jcr_csv(jcr_files[0], index)

    # 2. 中科院分区 (FQBJCR)
    fqb_files = sorted(csv_dir.glob("FQBJCR*UTF8.csv"), reverse=True)
    if fqb_files:
        _load_cas_csv(fqb_files[0], index)

    # 3. XR
    xr_files = sorted(csv_dir.glob("XR*UTF8.csv"), reverse=True)
    if xr_files:
        _load_xr_csv(xr_files[0], index)

    # 4. CCF
    ccf_files = sorted(csv_dir.glob("CCF*UTF8.csv"), reverse=True)
    if ccf_files:
        _load_ccf_csv(ccf_files[0], index)

    # 5. 预警
    warning_files = sorted(csv_dir.glob("GJQKYJMD*.csv"), reverse=True)
    if warning_files:
        _load_warning_csv(warning_files[0], index)


def _load_jcr_csv(path: Path, index: JcrIndex) -> None:
    """Load JCR IF from CSV."""
    with open(path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            issn = _normalize_issn(row.get("ISSN", ""))
            eissn = _normalize_issn(row.get("eISSN", ""))
            journal = row.get("Journal", "")

            # IF column name varies by year
            if_val = None
            quartile = None
            rank = None
            for k in row:
                if k.startswith("IF("):
                    if_val = _parse_if(row[k])
                if k.startswith("IF Quartile"):
                    quartile = row[k] or None
                if k.startswith("IF Rank"):
                    rank = row[k] or None

            entry = JcrEntry(
                issn=issn,
                journal=journal,
                impact_factor=if_val,
                jcr_quartile=quartile,
                jcr_rank=rank,
                jcr_category=row.get("Category") or None,
            )
            index.add(entry)
            if eissn and eissn != issn:
                index.add_issn_alias(eissn, entry)


def _load_cas_csv(path: Path, index: JcrIndex) -> None:
    """Load 中科院分区 from CSV and merge."""
    with open(path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            issn_raw = row.get("ISSN/EISSN") or row.get("ISSN") or ""
            issns = _parse_combined_issn(issn_raw)
            journal = row.get("Journal", "")

            cas_q = str(row.get("大类分区", "") or "")
            cas_cat = str(row.get("大类", "") or "")
            subs: list[str] = []
            for k in row:
                if k.startswith("小类") and "分区" not in k:
                    v = row[k]
                    if v:
                        subs.append(str(v))

            entry = None
            for issn in issns:
                entry = index.lookup_by_issn(issn)
                if entry:
                    break
            if not entry and journal:
                entry = index.lookup_by_journal(journal)

            if entry:
                entry.cas_quartile = cas_q or entry.cas_quartile
                entry.cas_category = cas_cat or entry.cas_category
                if subs:
                    entry.cas_sub_categories = subs
            else:
                entry = JcrEntry(
                    issn=issns[0] if issns else "",
                    journal=journal,
                    cas_quartile=cas_q or None,
                    cas_category=cas_cat or None,
                    cas_sub_categories=subs,
                )
                index.add(entry)
                for issn in issns[1:]:
                    index.add_issn_alias(issn, entry)


def _load_xr_csv(path: Path, index: JcrIndex) -> None:
    """Load XR from CSV and merge."""
    with open(path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            issn = _normalize_issn(row.get("ISSN", ""))
            eissn = _normalize_issn(row.get("EISSN", ""))
            journal = row.get("Journal", "")
            entry = index.lookup_by_issn(issn) or index.lookup_by_issn(eissn)
            if not entry and journal:
                entry = index.lookup_by_journal(journal)
            if entry:
                for k in row:
                    if "新锐分区" in k and row[k]:
                        q = str(row[k]).strip().replace("区", "").strip()
                        if q in ("1", "2", "3", "4"):
                            entry.cas_quartile = q
                            break


def _load_ccf_csv(path: Path, index: JcrIndex) -> None:
    """Load CCF from CSV and merge."""
    with open(path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            journal = row.get("Journal", "")
            if not journal:
                continue
            ccf_rank = ""
            ccf_field = ""
            for k in row:
                val = str(row[k] or "")
                if "推荐类型" in k:
                    if "A类" in val or "A 类" in val:
                        ccf_rank = "A"
                    elif "B类" in val or "B 类" in val:
                        ccf_rank = "B"
                    elif "C类" in val or "C 类" in val:
                        ccf_rank = "C"
                elif "T分区" in k:
                    if not ccf_rank and val.startswith("T"):
                        ccf_rank = val
                if "推荐类别" in k and not ccf_rank:
                    if "A类" in val or "A 类" in val:
                        ccf_rank = "A"
                    elif "B类" in val or "B 类" in val:
                        ccf_rank = "B"
                    elif "C类" in val or "C 类" in val:
                        ccf_rank = "C"
                if "领域" in k and "类别" not in k:
                    ccf_field = val

            entry = index.lookup_by_journal(journal)
            if entry:
                entry.ccf_rank = ccf_rank or entry.ccf_rank
                entry.ccf_field = ccf_field or entry.ccf_field
            else:
                entry = JcrEntry(
                    journal=journal,
                    ccf_rank=ccf_rank or None,
                    ccf_field=ccf_field or None,
                )
                index.add(entry)


def _load_warning_csv(path: Path, index: JcrIndex) -> None:
    """Load 期刊预警 from CSV and merge."""
    with open(path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            journal = row.get("Journal", "")
            if not journal:
                continue
            reason = ""
            for k in row:
                if "预警" in k:
                    reason = str(row[k] or "")
                    break
            entry = index.lookup_by_journal(journal)
            if entry:
                entry.is_warning = True
                entry.warning_reason = reason or entry.warning_reason


# ── Helpers ───────────────────────────────────────────────────────────────

def _parse_if(raw: str | None | float) -> float | None:
    """Parse IF value, handling '<0.1' and missing values."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    s = str(raw).strip()
    if not s or s == "-":
        return None
    if s.startswith("<"):
        s = s[1:]
    try:
        return float(s)
    except ValueError:
        return None


def _parse_combined_issn(raw: str) -> list[str]:
    """Parse combined ISSN field like '2649-664X/2649-6100'."""
    if not raw:
        return []
    parts = raw.split("/")
    result = []
    for p in parts:
        n = _normalize_issn(p.strip())
        if n:
            result.append(n)
    return result
