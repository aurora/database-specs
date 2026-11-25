"""Throw-away database containers and DB-API connections."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

import psycopg
import pymssql
import pymysql

PASSWORD = "dbspecs-test"
MSSQL_PASSWORD = "Dbspecs-test1"  # SQL Server enforces password complexity
DATABASE = "dbspecs"

ENGINE_SETUP = {
    "mysql": {
        "port": 3306,
        "env": {"MYSQL_ROOT_PASSWORD": PASSWORD, "MYSQL_DATABASE": DATABASE},
        "schema": DATABASE,
    },
    "mariadb": {
        "port": 3306,
        "env": {"MARIADB_ROOT_PASSWORD": PASSWORD, "MARIADB_DATABASE": DATABASE},
        "schema": DATABASE,
    },
    "postgresql": {
        "port": 5432,
        "env": {"POSTGRES_PASSWORD": PASSWORD, "POSTGRES_DB": DATABASE},
        "schema": "public",
    },
    "sqlserver": {
        "port": 1433,
        # ACCEPT_EULA: accepting the SQL Server Developer Edition license for local tests was
        # approved by the repository owner (Developer Edition is licensed for dev/test only).
        "env": {"ACCEPT_EULA": "Y", "MSSQL_SA_PASSWORD": MSSQL_PASSWORD, "MSSQL_PID": "Developer"},
        "schema": "dbo",
    },
    "manticore": {
        "port": 9306,
        "env": {},
        "schema": "Manticore",  # no databases: DATABASE() always returns 'Manticore'
    },
    "sphinx": {
        "port": 9306,
        "env": {},
        "schema": "default",  # no databases at all; query contracts echo this as schema_name
    },
    # embedded: no container port; a worker process (tooling/dbspecs/sqlite_worker.py) runs
    # locally or inside a python:*-slim image and uses the SQLite linked into that Python
    "sqlite": {"embedded": True, "schema": "main"},
}

WORKER_SOURCE = Path(__file__).with_name("sqlite_worker.py")


class EmbeddedError(Exception):
    pass


class WorkerProcess:
    """JSON-lines client for sqlite_worker.py."""

    def __init__(self, args: list[str]):
        self.proc = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, text=True, bufsize=1)

    def request(self, req: dict) -> dict:
        self.proc.stdin.write(json.dumps(req) + "\n")
        self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        if not line:
            raise RuntimeError("sqlite worker died: " + self.proc.stderr.read()[-2000:])
        return json.loads(line)

    def close(self):
        try:
            self.proc.stdin.close()
            self.proc.wait(timeout=20)
        except Exception:
            self.proc.kill()


def _decode(v):
    return bytes.fromhex(v["$blob"]) if isinstance(v, dict) and "$blob" in v else v


class WorkerCursor:
    def __init__(self, worker: WorkerProcess, conn_id: int):
        self.worker = worker
        self.conn_id = conn_id
        self.description = None
        self._rows: list = []

    def execute(self, sql, params=None):
        resp = self.worker.request({"op": "execute", "conn": self.conn_id, "sql": sql, "params": params})
        if not resp["ok"]:
            raise EmbeddedError(resp["error"])
        cols = resp["columns"]
        self.description = [(c, None, None, None, None, None, None) for c in cols] if cols else None
        self._rows = [tuple(_decode(v) for v in r) for r in resp["rows"]]

    def fetchone(self):
        return self._rows.pop(0) if self._rows else None

    def fetchall(self):
        rows, self._rows = self._rows, []
        return rows

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class WorkerConnection:
    """Minimal DB-API style wrapper: one SQLite connection in the worker (same database file)."""

    def __init__(self, worker: WorkerProcess):
        self.worker = worker
        self.conn_id = worker.request({"op": "connect"})["conn"]

    def cursor(self):
        return WorkerCursor(self.worker, self.conn_id)

    def close(self):
        if self.conn_id is not None:
            self.worker.request({"op": "close", "conn": self.conn_id})
            self.conn_id = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def container_cli() -> str:
    for cli in ("docker", "podman"):
        if shutil.which(cli):
            return cli
    raise RuntimeError("neither docker nor podman found")


@dataclass
class Server:
    target: dict
    host: str
    port: int
    version: str = ""
    worker: WorkerProcess | None = field(default=None, repr=False)

    @property
    def engine(self) -> str:
        return self.target["engine"]

    @property
    def schema(self) -> str:
        return ENGINE_SETUP[self.engine]["schema"]

    def run_script(self, conn, text: str, batch_separator: str | None = None):
        """Execute SQL that may contain several statements (e.g. reconstructed DDL)."""
        if self.engine == "sqlite":
            resp = conn.worker.request({"op": "script", "conn": conn.conn_id, "sql": text})
            if not resp["ok"]:
                raise EmbeddedError(resp["error"])
            return
        batches = [text]
        if batch_separator:  # e.g. T-SQL GO: client-side, on a line of its own
            # the line break before the separator line belongs to the separator, not to the batch
            batches = re.split(rf"(?:\r?\n|^)[ \t]*{re.escape(batch_separator)}[ \t]*(?:\r?\n|$)", text, flags=re.I)
        with conn.cursor() as cur:
            for batch in batches:
                if batch.strip():
                    cur.execute(batch)

    def format_sql(self, sql: str) -> str:
        """Placeholders: the spec's :name style -> what the test driver expects."""
        return sql if self.engine == "sqlite" else to_pyformat(sql)

    def connect(self, database: str = DATABASE):
        if self.engine == "sqlite":
            return WorkerConnection(self.worker)
        if self.engine in ("mysql", "mariadb"):  # mysql wire protocol
            return pymysql.connect(host=self.host, port=self.port, user="root", password=PASSWORD,
                                   database=DATABASE, autocommit=True, connect_timeout=3)
        if self.engine in ("manticore", "sphinx"):  # mysql wire protocol, no authentication, no databases
            return pymysql.connect(host=self.host, port=self.port, user="root", autocommit=True,
                                   connect_timeout=3)
        if self.engine == "sqlserver":
            return pymssql.connect(server=self.host, port=self.port, user="sa", password=MSSQL_PASSWORD,
                                   database=database, autocommit=True, login_timeout=3)
        if self.engine == "postgresql":
            return psycopg.connect(host=self.host, port=self.port, user="postgres", password=PASSWORD,
                                   dbname=DATABASE, autocommit=True, connect_timeout=3)
        raise ValueError(self.engine)

    def detect_version(self) -> str:
        if self.engine == "sqlite":
            resp = self.worker.request({"op": "version"})
            self.version = resp["rows"][0][0]
            return self.version
        if self.engine == "sqlserver":
            # no database exists yet: connect to master and create it
            with self.connect("master") as conn, conn.cursor() as cur:
                cur.execute("SELECT CAST(SERVERPROPERTY('ProductVersion') AS nvarchar(128))")
                self.version = re.match(r"\d+\.\d+\.\d+", cur.fetchone()[0]).group(0)
                cur.execute(f"IF DB_ID('{DATABASE}') IS NULL CREATE DATABASE [{DATABASE}]")
            return self.version
        if self.engine == "sphinx":  # 2.x has no VERSION(): the handshake carries the version
            with self.connect() as conn:
                self.version = re.match(r"\d+\.\d+\.\d+", conn.server_version).group(0)
            return self.version
        with self.connect() as conn, conn.cursor() as cur:
            if self.engine in ("mysql", "mariadb", "manticore"):
                cur.execute("SELECT VERSION()")
                self.version = re.match(r"\d+\.\d+\.\d+", cur.fetchone()[0]).group(0)
            else:
                cur.execute("SHOW server_version_num")
                num = int(cur.fetchone()[0])
                self.version = f"{num // 10000}.{num % 10000}"
        return self.version


def build_image(target: dict) -> str:
    """Targets with `build: <dir>` (no official image): build the Dockerfile there; cached by the CLI."""
    from .specs import ROOT
    tag = f"dbspecs-{target['id']}:local"
    subprocess.run([container_cli(), "build", "-q", "-t", tag, str(ROOT / target["build"])],
                   check=True, capture_output=True, text=True)
    return tag


@contextmanager
def running(target: dict, timeout: float = 180):
    setup = ENGINE_SETUP[target["engine"]]
    if setup.get("embedded"):
        with _running_embedded(target) as server:
            yield server
        return
    cli = container_cli()
    image = target.get("image") or build_image(target)
    args = [cli, "run", "-d", "--rm", "-p", f"127.0.0.1::{setup['port']}"]
    for k, v in setup["env"].items():
        args += ["-e", f"{k}={v}"]
    args.append(image)
    cid = subprocess.run(args, check=True, capture_output=True, text=True).stdout.strip()
    try:
        out = subprocess.run([cli, "port", cid, f"{setup['port']}/tcp"], check=True,
                             capture_output=True, text=True).stdout.splitlines()[0]
        host, port = out.rsplit(":", 1)
        server = Server(target, host.strip("[]"), int(port))
        deadline = time.monotonic() + timeout
        while True:
            try:
                server.detect_version()
                break
            except Exception:
                if time.monotonic() > deadline:
                    raise RuntimeError(f"{target['id']}: server did not become ready")
                time.sleep(1)
        yield server
    finally:
        subprocess.run([cli, "rm", "-f", cid], capture_output=True)


@contextmanager
def _running_embedded(target: dict):
    source = WORKER_SOURCE.read_text(encoding="utf-8")
    tmpdir = None
    if target.get("image"):
        args = [container_cli(), "run", "-i", "--rm", target["image"], "python", "-c", source]
    else:  # the SQLite linked into this Python
        tmpdir = tempfile.mkdtemp(prefix="dbspecs-sqlite-")
        args = [sys.executable, "-c", source, str(Path(tmpdir) / "test.db")]
    worker = WorkerProcess(args)
    try:
        server = Server(target, "", 0, worker=worker)
        server.detect_version()
        yield server
    finally:
        worker.close()
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)


_PARAM = re.compile(r"(?<![:\w]):([A-Za-z_]\w*)")


def to_pyformat(sql: str) -> str:
    """Translate :name placeholders to %(name)s (both drivers accept pyformat).
    Simplified: does not skip string literals/comments - fine for the curated SQL in this repo."""
    return _PARAM.sub(r"%(\1)s", sql.replace("%", "%%"))


def fetch_dicts(cur) -> list[dict]:
    cols = [d[0] for d in cur.description]
    rows = []
    for row in cur.fetchall():
        rows.append({c: (v.decode() if isinstance(v, (bytes, bytearray)) else v) for c, v in zip(cols, row)})
    return rows
