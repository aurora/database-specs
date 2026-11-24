"""Generate keyword lists per engine version from real servers / libraries.

reserved = the word fails as an unquoted column name. This is probed for every engine, so the
meaning is the same everywhere (server flags differ: MySQL RESERVED, PostgreSQL catcode, MariaDB
none).
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import yaml

from .servers import Server, fetch_dicts
from .specs import ROOT, Specs, load_yaml, parse_version, variant_for

KEYWORD_DIR = ROOT / "keywords"

# Seed for engines without a keyword list (SQL Server): T-SQL keyword names. Only a candidate list -
# which of them are reserved is decided by probing the server.
TSQL_CANDIDATES = """
ADD ALL ALTER AND ANY AS ASC AUTHORIZATION BACKUP BEGIN BETWEEN BREAK BROWSE BULK BY CASCADE CASE
CHECK CHECKPOINT CLOSE CLUSTERED COALESCE COLLATE COLUMN COMMIT COMPUTE CONSTRAINT CONTAINS
CONTAINSTABLE CONTINUE CONVERT CREATE CROSS CURRENT CURRENT_DATE CURRENT_TIME CURRENT_TIMESTAMP
CURRENT_USER CURSOR DATABASE DBCC DEALLOCATE DECLARE DEFAULT DELETE DENY DESC DISK DISTINCT
DISTRIBUTED DOUBLE DROP DUMP ELSE END ERRLVL ESCAPE EXCEPT EXEC EXECUTE EXISTS EXIT EXTERNAL FETCH
FILE FILLFACTOR FOR FOREIGN FREETEXT FREETEXTTABLE FROM FULL FUNCTION GOTO GRANT GROUP HAVING
HOLDLOCK IDENTITY IDENTITY_INSERT IDENTITYCOL IF IN INDEX INNER INSERT INTERSECT INTO IS JOIN KEY
KILL LEFT LIKE LINENO LOAD MERGE NATIONAL NOCHECK NONCLUSTERED NOT NULL NULLIF OF OFF OFFSETS ON
OPEN OPENDATASOURCE OPENQUERY OPENROWSET OPENXML OPTION OR ORDER OUTER OVER PERCENT PIVOT PLAN
PRECISION PRIMARY PRINT PROC PROCEDURE PUBLIC RAISERROR READ READTEXT RECONFIGURE REFERENCES
REPLICATION RESTORE RESTRICT RETURN REVERT REVOKE RIGHT ROLLBACK ROWCOUNT ROWGUIDCOL RULE SAVE
SCHEMA SECURITYAUDIT SELECT SEMANTICKEYPHRASETABLE SEMANTICSIMILARITYDETAILSTABLE
SEMANTICSIMILARITYTABLE SESSION_USER SET SETUSER SHUTDOWN SOME STATISTICS SYSTEM_USER TABLE
TABLESAMPLE TEXTSIZE THEN TO TOP TRAN TRANSACTION TRIGGER TRUNCATE TRY_CONVERT TSEQUAL UNION UNIQUE
UNPIVOT UPDATE UPDATETEXT USE USER VALUES VARYING VIEW WAITFOR WHEN WHERE WHILE WITH WITHIN
WRITETEXT
""".split()

PROBES = {
    # statement that succeeds iff the word can be an unquoted column name; cleanup after success
    "mysql": ("CREATE TEMPORARY TABLE kw_probe ({w} INT)", "DROP TEMPORARY TABLE kw_probe"),
    "mariadb": ("CREATE TEMPORARY TABLE kw_probe ({w} INT)", "DROP TEMPORARY TABLE kw_probe"),
    "postgresql": ("CREATE TEMPORARY TABLE kw_probe ({w} INT)", "DROP TABLE kw_probe"),
    "sqlserver": ("DECLARE @kw_probe TABLE ({w} INT)", None),
    "sqlite": ("CREATE TEMP TABLE kw_probe ({w} INT)", "DROP TABLE kw_probe"),
}


def stored_files() -> dict[str, dict[str, dict]]:
    """engine -> version -> document"""
    out: dict[str, dict[str, dict]] = {}
    for path in sorted(KEYWORD_DIR.glob("*/*.yaml")):
        doc = load_yaml(path)
        out.setdefault(doc["engine"], {})[doc["version"]] = doc
    return out


def _series(version: str) -> tuple[int, ...]:
    """Version without its last component: 8.0.46 -> (8, 0), 17.12 -> (17,), 14.0.3570 -> (14, 0)."""
    parts = tuple(int(p) for p in version.split("."))
    return parts[:-1] if len(parts) > 1 else parts


def resolve(engine: str, version: str) -> tuple[dict, bool] | None:
    """Keyword data for a version: exact match, else the same series (closest patch level), else
    the newest older series. Returns (document, exact)."""
    versions = stored_files().get(engine, {})
    if version in versions:
        return versions[version], True
    want = parse_version(version)
    series_len = len(_series(next(iter(versions)))) if versions else 0
    want_series = want[:series_len]
    same = [v for v in versions if _series(v) == want_series]
    if same:
        best = min(same, key=lambda v: abs(int(v.split(".")[-1]) - want[series_len] if series_len < len(want) else 0))
        return versions[best], False
    older = [v for v in versions if _series(v) < want_series]
    if older:
        return versions[max(older, key=parse_version)], False
    return None


def _server_list(specs: Specs, server: Server, conn) -> list[str] | None:
    if server.engine == "sqlite":
        resp = server.worker.request({"op": "keywords"})
        return resp.get("words") if resp.get("ok") else None
    query = specs.get("query", "lexical.keywords")
    var = variant_for(query, server.engine, server.version)
    if not var:
        return None
    sql = (specs.path("query", "lexical.keywords").parent / var["file"]).read_text(encoding="utf-8")
    with conn.cursor() as cur:
        cur.execute(sql)
        return [r["word"] for r in fetch_dicts(cur)]


def _candidates(engine: str) -> set[str]:
    words = set(TSQL_CANDIDATES) if engine == "sqlserver" else set()
    for eng, versions in stored_files().items():
        for doc in versions.values():
            if doc["complete"] or eng == engine:
                words |= set(doc["reserved"]) | set(doc.get("nonreserved", []))
    return words


def _probe_reserved(server: Server, conn, words) -> set[str]:
    create, drop = PROBES[server.engine]
    reserved = set()
    with conn.cursor() as cur:
        for w in sorted(words):
            if not w.replace("_", "").isalnum() or w[0].isdigit():
                continue
            try:
                cur.execute(create.format(w=w))
            except Exception:  # connections are in autocommit mode: a failed statement leaves no state
                reserved.add(w)
                continue
            if drop:
                cur.execute(drop)
    return reserved


def generate(specs: Specs, server: Server) -> dict:
    with server.connect() as conn:
        words = _server_list(specs, server, conn)
        method = ("c-api" if server.engine == "sqlite" else "server-query") if words else "probe"
        complete = words is not None
        candidates = set(w.upper() for w in (words or _candidates(server.engine)))
        reserved = _probe_reserved(server, conn, candidates)
    doc = {
        "engine": server.engine,
        "version": server.version,
        "generated_at": dt.date.today().isoformat(),
        "method": method,
        "complete": complete,
    }
    if not complete:
        doc["candidates"] = len(candidates)
        doc["notes"] = ["The server has no keyword list: candidate words (keywords of other engines"
                        + (" and T-SQL keyword names" if server.engine == "sqlserver" else "")
                        + ") were probed. Only reserved words are known; reserved words that no other list"
                        " contains can be missing."]
    doc["reserved"] = sorted(reserved)
    doc["nonreserved"] = sorted(candidates - reserved) if complete else []
    return doc


def write(doc: dict) -> Path:
    path = KEYWORD_DIR / doc["engine"] / f"{doc['version']}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    header = "# Generated by `uv run dbspecs keywords` from a real server/library - do not edit.\n"
    path.write_text(header + yaml.safe_dump(doc, sort_keys=False, width=100), encoding="utf-8")
    return path


def compare(stored: dict, fresh: dict) -> list[str]:
    problems = []
    for key in ("reserved", "nonreserved"):
        a, b = set(stored.get(key, [])), set(fresh.get(key, []))
        if a != b:
            problems.append(f"{key}: +{sorted(b - a)[:5]} -{sorted(a - b)[:5]}")
    return problems
