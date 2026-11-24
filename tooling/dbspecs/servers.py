"""Throw-away database containers and DB-API connections."""

from __future__ import annotations

import re
import shutil
import subprocess
import time
from contextlib import contextmanager
from dataclasses import dataclass

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
}


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

    @property
    def engine(self) -> str:
        return self.target["engine"]

    @property
    def schema(self) -> str:
        return ENGINE_SETUP[self.engine]["schema"]

    def connect(self, database: str = DATABASE):
        if self.engine in ("mysql", "mariadb"):  # mysql wire protocol
            return pymysql.connect(host=self.host, port=self.port, user="root", password=PASSWORD,
                                   database=DATABASE, autocommit=True, connect_timeout=3)
        if self.engine == "sqlserver":
            return pymssql.connect(server=self.host, port=self.port, user="sa", password=MSSQL_PASSWORD,
                                   database=database, autocommit=True, login_timeout=3)
        if self.engine == "postgresql":
            return psycopg.connect(host=self.host, port=self.port, user="postgres", password=PASSWORD,
                                   dbname=DATABASE, autocommit=True, connect_timeout=3)
        raise ValueError(self.engine)

    def detect_version(self) -> str:
        if self.engine == "sqlserver":
            # no database exists yet: connect to master and create it
            with self.connect("master") as conn, conn.cursor() as cur:
                cur.execute("SELECT CAST(SERVERPROPERTY('ProductVersion') AS nvarchar(128))")
                self.version = re.match(r"\d+\.\d+\.\d+", cur.fetchone()[0]).group(0)
                cur.execute(f"IF DB_ID('{DATABASE}') IS NULL CREATE DATABASE [{DATABASE}]")
            return self.version
        with self.connect() as conn, conn.cursor() as cur:
            if self.engine in ("mysql", "mariadb"):
                cur.execute("SELECT VERSION()")
                self.version = re.match(r"\d+\.\d+\.\d+", cur.fetchone()[0]).group(0)
            else:
                cur.execute("SHOW server_version_num")
                num = int(cur.fetchone()[0])
                self.version = f"{num // 10000}.{num % 10000}"
        return self.version


@contextmanager
def running(target: dict, timeout: float = 180):
    cli = container_cli()
    setup = ENGINE_SETUP[target["engine"]]
    args = [cli, "run", "-d", "--rm", "-p", f"127.0.0.1::{setup['port']}"]
    for k, v in setup["env"].items():
        args += ["-e", f"{k}={v}"]
    args.append(target["image"])
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
