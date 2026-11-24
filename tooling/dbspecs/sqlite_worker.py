"""Stand-alone SQLite worker: JSON lines on stdin -> JSON lines on stdout.

Runs with the Python standard library only (also inside python:*-slim containers, Python 3.7+),
so tests use the SQLite version linked into that interpreter.

Requests:  {"op": "version"}
           {"op": "connect"}                -> {"ok": true, "conn": <id>}  (new connection, same database file)
           {"op": "close", "conn": <id>}
           {"op": "execute", "conn": <id>, "sql": "...", "params": {...} | [...] | null}
           {"op": "script", "conn": <id>, "sql": "..."}   (several statements, sqlite3.executescript)
Responses: {"ok": true, "columns": [...] | null, "rows": [[...], ...]}
           {"ok": false, "error": "..."}
"""

import json
import sqlite3
import sys


def encode(value):
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"$blob": bytes(value).hex()}
    return value


def main():
    path = "/tmp/dbspecs-sqlite.db" if len(sys.argv) < 2 else sys.argv[1]
    conns = {}
    next_id = [0]
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        req = json.loads(line)
        try:
            if req["op"] == "version":
                resp = {"ok": True, "columns": ["version"], "rows": [[sqlite3.sqlite_version]]}
            elif req["op"] == "connect":
                next_id[0] += 1
                # autocommit: BEGIN/COMMIT are explicit, as with the server engines
                conns[next_id[0]] = sqlite3.connect(path, isolation_level=None)
                resp = {"ok": True, "conn": next_id[0]}
            elif req["op"] == "close":
                conns.pop(req["conn"]).close()
                resp = {"ok": True}
            elif req["op"] == "script":
                conns[req["conn"]].executescript(req["sql"])
                resp = {"ok": True, "columns": None, "rows": []}
            elif req["op"] == "execute":
                cur = conns[req["conn"]].execute(req["sql"], req.get("params") or ())
                columns = [d[0] for d in cur.description] if cur.description else None
                rows = [[encode(v) for v in row] for row in cur.fetchall()] if columns else []
                resp = {"ok": True, "columns": columns, "rows": rows}
            else:
                resp = {"ok": False, "error": "unknown op " + str(req.get("op"))}
        except Exception as exc:  # report every SQLite error to the caller
            resp = {"ok": False, "error": type(exc).__name__ + ": " + str(exc)}
        sys.stdout.write(json.dumps(resp) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
