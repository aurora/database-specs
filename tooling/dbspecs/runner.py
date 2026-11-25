"""Run capability probes and test cases against real servers."""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field

from .servers import Server, fetch_dicts
from .specs import (Specs, apply_transform, in_range, query_sql, quote_identifier, quote_literal, render,
                    statement_for, variant_for)
from .syntax import examples_for, grammar_accepts, grammar_should_accept, server_should_accept, server_sql


@dataclass
class Result:
    target: str
    version: str
    kind: str  # probe | test
    id: str
    outcome: str  # pass | fail | observed | skip
    detail: str = ""
    observed: str | None = None  # for probes: supported/unsupported

    def as_dict(self):
        return {k: v for k, v in self.__dict__.items() if v not in (None, "")}


@dataclass
class Report:
    results: list[Result] = field(default_factory=list)

    def add(self, r: Result):
        self.results.append(r)
        return r

    def failed(self):
        return [r for r in self.results if r.outcome == "fail"]


def _exec_all(conn, statements, count_sets: bool = False) -> int | tuple[int, int]:
    """Run statements; with count_sets, returns (result sets, rows of the first set) of the last one."""
    sets = nrows = 0
    with conn.cursor() as cur:
        for sql in statements:
            if sql.strip():  # rendered templates can leave empty optional steps
                cur.execute(sql)
                if not count_sets:
                    continue
                sets = 1 if cur.description else 0
                nrows = len(cur.fetchall()) if cur.description else 0
                while cur.nextset():
                    sets += 1 if cur.description else 0
    return (sets, nrows) if count_sets else sets


def _statements(items, version: str) -> list[str]:
    """Setup/cleanup entries: plain SQL strings or {sql, since, until} objects."""
    out = []
    for item in items or []:
        if isinstance(item, str):
            out.append(item)
        elif in_range(version, item):
            out.append(item["sql"])
    return out


def _cleanup(server: Server, statements):
    if not statements:
        return
    try:
        with server.connect() as conn:
            for sql in statements:
                try:
                    _exec_all(conn, [sql])
                except Exception:
                    pass
    except Exception:
        pass


# --- probes -----------------------------------------------------------------

def run_probes(specs: Specs, server: Server, report: Report):
    for cap_id, cap in sorted(specs.docs["capability"].items()):
        for probe in cap.get("probes", []):
            if server.engine not in probe["engines"] or not in_range(server.version, probe):
                continue
            name = cap_id + (f"#{probe['name']}" if "name" in probe else "")
            try:
                with server.connect() as conn:
                    _exec_all(conn, probe.get("setup", []))
                    try:
                        ok, err = True, ""
                        if "result_sets" in probe or "rows" in probe:
                            sets, nrows = _exec_all(conn, probe["statements"], True)
                            if sets < probe.get("result_sets", 0):
                                ok, err = False, f"{sets} result set(s), expected {probe['result_sets']}"
                            elif "rows" in probe and nrows != probe["rows"]:
                                ok, err = False, f"{nrows} row(s), expected {probe['rows']}"
                        else:
                            _exec_all(conn, probe["statements"])
                        if ok and "check" in probe:
                            with conn.cursor() as cur:
                                cur.execute(probe["check"])
                                ok = bool(cur.fetchone()[0])
                            err = "" if ok else "check returned false"
                    except Exception as exc:  # the statement under test failed
                        ok, err = False, f"{type(exc).__name__}: {exc}".splitlines()[0]
            except Exception as exc:  # setup failed -> probe itself is broken
                report.add(Result(server.target["id"], server.version, "probe", name, "fail",
                                  f"probe setup failed: {exc}"))
                continue
            finally:
                _cleanup(server, probe.get("cleanup", []))

            if probe.get("invert"):
                ok, err = (not ok), ("" if not ok else "statements succeeded but should fail")
            observed = "supported" if ok else "unsupported"
            stmt = statement_for(cap["support"].get(server.engine, []), server.version)
            declared = stmt["status"] if stmt else "unknown"
            if declared == "unknown":
                outcome, detail = "observed", f"declared unknown, probe says {observed}"
            elif (declared in ("supported", "partial")) == ok:
                outcome, detail = "pass", ""
            else:
                outcome, detail = "fail", f"declared {declared}, probe says {observed}. {err}".strip()
            report.add(Result(server.target["id"], server.version, "probe", name, outcome, detail, observed))


# --- tests ------------------------------------------------------------------

def _resolve_params(params: dict, server: Server) -> dict:
    def sub(v):
        if not isinstance(v, str):
            return v
        v = v.replace("{{schema}}", server.schema)
        bg = getattr(server, "background", None)
        return v.replace("{{background_session}}", str(bg["session_id"])) if bg else v
    return {k: sub(v) for k, v in params.items()}


class _Background:
    """A second session running one long statement in a thread (for cancel / kill tests)."""

    def __init__(self, specs: Specs, server: Server, sql: str):
        import threading
        import time
        self.error = None
        self.session_id = None
        self.started = time.monotonic()
        self.finished = None
        id_query = specs.get("engine", server.engine)["identification"]["session_id_query"]
        ready = threading.Event()

        def run():
            try:
                conn = server.connect()
                with conn.cursor() as cur:
                    cur.execute(id_query)
                    self.session_id = int(cur.fetchone()[0])
                    ready.set()
                    cur.execute(sql)
                    try:
                        cur.fetchall()
                    except Exception:
                        pass
                conn.close()
            except Exception as exc:  # expected when cancelled / killed
                self.error = f"{type(exc).__name__}: {exc}".splitlines()[0]
            finally:
                ready.set()
                self.finished = time.monotonic()

        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()
        ready.wait(30)
        time.sleep(1.5)  # let the statement start before it is cancelled

    def wait(self, timeout: float) -> float:
        self.thread.join(timeout)
        return (self.finished or float("inf")) - self.started


def _render_operation(specs: Specs, op_id: str, server: Server, params: dict) -> list[str]:
    op = specs.get("operation", op_id)
    impl = statement_for(op["implementations"].get(server.engine, []), server.version)
    if not impl or impl["status"] in ("unsupported", "unknown"):
        raise RuntimeError(f"operation {op_id} not available for {server.engine} {server.version}")
    method = impl.get("method", "template")
    if method == "protocol":
        raise RuntimeError(f"operation {op_id} uses a protocol call; not testable via SQL")
    lexical = specs.get("lexical", specs.get("engine", server.engine)["lexical"])
    kinds = {p["name"]: p["kind"] for p in op["parameters"]}
    values = {}
    for name, value in params.items():
        if kinds.get(name) == "identifier":
            value = quote_identifier(lexical, value)
        elif kinds.get(name) == "qualified-identifier":
            value = ".".join(quote_identifier(lexical, part) for part in str(value).split("."))
        elif kinds.get(name) == "string-literal":
            value = quote_literal(lexical, str(value))
        elif kinds.get(name) == "boolean":
            value = bool(value) or None  # sections test truthiness
        values[name] = value
    templates = impl.get("steps") or [impl["template"]]
    return [render(t, values) for t in templates]


def _operation_impl(specs: Specs, op_id: str, server: Server) -> dict:
    op = specs.get("operation", op_id)
    return statement_for(op["implementations"].get(server.engine, []), server.version) or {}


def _run_operation(specs: Specs, server: Server, conn, op_id: str, params: dict) -> list[dict]:
    """Execute all rendered statements; return the rows of the last one that produced a result."""
    rows: list[dict] = []
    with conn.cursor() as cur:
        for sql in _render_operation(specs, op_id, server, params):
            if not sql.strip():
                continue
            cur.execute(sql)
            if cur.description:
                rows = fetch_dicts(cur)
    return rows


def _result_text(rows: list[dict], impl: dict) -> str:
    """The text an operation returns (e.g. DDL): result_column by name or 1-based position."""
    if not rows:
        raise RuntimeError("operation returned no rows")
    col = impl.get("result_column", 1)
    row = rows[0]
    value = list(row.values())[col - 1] if isinstance(col, int) else row[col]
    return value.decode() if isinstance(value, (bytes, bytearray)) else value


def _run_query(specs: Specs, server: Server, conn, query_id: str, params: dict) -> tuple[list[dict], list[str]]:
    query = specs.get("query", query_id)
    var = variant_for(query, server.engine, server.version)
    if not var:
        return [], [f"no variant of {query_id} for {server.engine} {server.version}"]
    sql = (specs.path("query", query_id).parent / var["file"]).read_text(encoding="utf-8")
    lexical = specs.get("lexical", specs.get("engine", server.engine)["lexical"])
    sql, bind = query_sql(var, sql, lexical, params)
    with conn.cursor() as cur:
        cur.execute(server.format_sql(sql), bind or None)
        rows = fetch_dicts(cur)
    problems = []
    try:
        rows = apply_transform(var, rows, params)
    except (KeyError, ValueError) as exc:
        return rows, [f"transform failed: {exc}"]
    expected_cols = [c["name"] for c in query["result"]["columns"]] + [e["name"] for e in var.get("extra_columns", [])]
    if rows and list(rows[0]) != expected_cols:
        problems.append(f"columns {list(rows[0])} != contract {expected_cols}")
    problems += _check_contract(query, rows)
    return rows, problems


def _step_params(step: dict, server: Server) -> dict:
    return _resolve_params({**step.get("params", {}),
                            **step.get("params_by_engine", {}).get(server.engine, {})}, server)


def _roundtrip(specs: Specs, server: Server, conn, spec: dict) -> list[str]:
    """Snapshot introspection, reconstruct DDL, drop, re-run the DDL, compare the snapshot."""
    def snapshot():
        out = []
        for c in spec["compare"]:
            rows, problems = _run_query(specs, server, conn, c["query"], _step_params(c, server))
            if problems:
                raise RuntimeError(f"{c['query']}: {problems[0]}")
            out.append((c["query"], rows))
        return out

    before = snapshot()
    impl = _operation_impl(specs, spec["operation"], server)
    ddl = _result_text(_run_operation(specs, server, conn, spec["operation"], _step_params(spec, server)), impl)
    _exec_all(conn, _statements(spec["drop"].get(server.engine), server.version))
    lexical = specs.get("lexical", specs.get("engine", server.engine)["lexical"])
    try:
        server.run_script(conn, ddl, lexical["statements"].get("batch_separator"))
    except Exception as exc:
        return [f"reconstructed DDL failed: {exc}".splitlines()[0] + f" -- DDL: {ddl[:300]!r}"]
    problems = []
    for (qid, old), (_, new) in zip(before, snapshot()):
        if old != new:
            diff = next(((o, n) for o, n in zip(old, new) if o != n), (len(old), len(new)))
            problems.append(f"{qid} differs after round trip: {diff}")
    return problems


def _check_contract(query: dict, rows: list[dict]) -> list[str]:
    """Every row must match the declared column types, nullability and enums."""
    problems = []
    for col in query["result"]["columns"]:
        name = col["name"]
        for row in rows:
            v = row.get(name)
            if v is None:
                if not col["nullable"]:
                    problems.append(f"{name} is NULL but declared NOT NULL")
                    break
                continue
            t = col["type"]
            ok = (t == "string" and isinstance(v, str)) \
                or (t == "integer" and isinstance(v, int) and not isinstance(v, bool)) \
                or (t == "boolean" and (isinstance(v, bool) or v in (0, 1)))
            if not ok:
                problems.append(f"{name}: {v!r} ({type(v).__name__}) is not {t}")
                break
            if "enum" in col and v not in col["enum"]:
                problems.append(f"{name}: {v!r} not in {col['enum']}")
                break
    return problems


def _check(expect: dict, rows: list[dict], server: Server) -> list[str]:
    problems = []
    if "row_count" in expect and len(rows) != expect["row_count"]:
        problems.append(f"row_count {len(rows)} != {expect['row_count']}")
    for exp in expect.get("rows", []):
        if "engine" in exp and exp["engine"] != server.engine:
            continue
        if not in_range(server.version, exp):
            continue
        matches = [r for r in rows if all(r.get(k) == v for k, v in exp["match"].items())]
        want = exp.get("count", 1)
        if len(matches) != want:
            problems.append(f"{exp['match']}: {len(matches)} matching rows, expected {want}")
            continue
        if want != 1:
            continue
        row = matches[0]
        for k, pattern in exp.get("matches", {}).items():
            got = row.get(k)
            if not isinstance(got, str) or not re.search(pattern, got, re.S):
                problems.append(f"{exp['match']} {k}: {got!r} does not match /{pattern}/")
        for k, v in exp.get("values", {}).items():
            got = row.get(k)
            if isinstance(v, bool) and isinstance(got, int):
                got = bool(got)
            if got != v:
                problems.append(f"{exp['match']} {k}: got {got!r}, expected {v!r}")
    return problems


def _missing_variant(specs: Specs, test: dict, server: Server) -> str | None:
    """First query / operation a test needs that has no variant for this server version."""
    for step in test["steps"]:
        if "engines" in step and not (server.engine in step["engines"]
                                      and in_range(server.version, step["engines"][server.engine])):
            continue
        queries = [step["query"]] if "query" in step else []
        ops = [step["operation"]] if "operation" in step else []
        if "roundtrip" in step:
            ops.append(step["roundtrip"]["operation"])
            queries += [c["query"] for c in step["roundtrip"]["compare"]]
        for q in queries:
            if variant_for(specs.get("query", q), server.engine, server.version) is None:
                return f"no variant of {q} for {server.version} (documented gap)"
        for o in ops:
            impl = statement_for(specs.get("operation", o)["implementations"].get(server.engine, []), server.version)
            if not impl or impl["status"] in ("unsupported", "unknown"):
                return f"operation {o} not available for {server.version}"
    return None


def run_tests(specs: Specs, server: Server, report: Report):
    for test_id, test in sorted(specs.docs["test"].items()):
        if server.engine not in test["engines"]:
            continue
        if not in_range(server.version, test.get("versions", {}).get(server.engine, {})):
            report.add(Result(server.target["id"], server.version, "test", test_id, "skip",
                              "outside the test's version range"))
            continue
        gap = _missing_variant(specs, test, server)
        if gap:  # a documented gap (query without variant / operation not available), not a failure
            report.add(Result(server.target["id"], server.version, "test", test_id, "skip", gap))
            continue
        problems: list[str] = []
        try:
            with server.connect() as conn:
                _exec_all(conn, _statements(test.get("setup", {}).get(server.engine), server.version))
                for step in test["steps"]:
                    if "engines" in step and not (server.engine in step["engines"]
                                                  and in_range(server.version, step["engines"][server.engine])):
                        continue
                    if "background" in step:
                        if server.engine in step["background"]:
                            bg = _Background(specs, server, step["background"][server.engine])
                            server.background = {"session_id": bg.session_id, "obj": bg}
                        continue
                    if "await_background" in step:
                        spec = step["await_background"]
                        bg = (getattr(server, "background", None) or {}).get("obj")
                        if bg is None:
                            continue
                        took = bg.wait(spec["within_seconds"] + 5)
                        if took > spec["within_seconds"]:
                            problems.append(f"background statement still ran after {spec['within_seconds']}s")
                        if spec.get("expect_error") and not bg.error:
                            problems.append("background statement ended without error")
                        server.background = None
                        continue
                    params = _step_params(step, server)
                    if "roundtrip" in step:
                        label = f"roundtrip {step['roundtrip']['operation']}"
                        problems += [f"{label}: {p}" for p in _roundtrip(specs, server, conn, step["roundtrip"])]
                        continue
                    if "operation" in step:
                        label = step["operation"]
                        rows = _run_operation(specs, server, conn, step["operation"], params)
                    elif "sql" in step:
                        label = "sql"
                        if server.engine not in step["sql"]:
                            continue
                        with conn.cursor() as cur:
                            cur.execute(step["sql"][server.engine])
                            rows = fetch_dicts(cur) if cur.description else []
                    else:
                        label = step["query"]
                        rows, qp = _run_query(specs, server, conn, step["query"], params)
                        problems += [f"{label}: {p}" for p in qp]
                        if qp and qp[0].startswith("no variant"):
                            break
                    problems += [f"{label}: {p}" for p in _check(step.get("expect", {}), rows, server)]
        except Exception as exc:
            problems.append(f"{type(exc).__name__}: {exc}".splitlines()[0])
        finally:
            _cleanup(server, _statements(test.get("cleanup", {}).get(server.engine), server.version))
        report.add(Result(server.target["id"], server.version, "test", test_id,
                          "fail" if problems else "pass", "; ".join(problems)))


def run_syntax(specs: Specs, server: Server, report: Report):
    """Each example: grammar (for the server's exact version) and server must agree with `expect`."""
    for syn_id, syn in sorted(specs.docs["syntax"].items()):
        if server.engine not in syn["grammars"]:
            continue
        floor = syn["grammars"][server.engine].get("since")
        if floor and not in_range(server.version, {"since": floor}):
            report.add(Result(server.target["id"], server.version, "syntax", syn_id, "skip",
                              f"grammar describes {floor}+"))
            continue
        for i, ex in examples_for(syn, server.engine, server.version):
            name = f"{syn_id}#{i}"
            problems = []
            if grammar_accepts(specs, syn_id, server.engine, server.version, ex["sql"]) != grammar_should_accept(ex["expect"]):
                problems.append("grammar disagrees")
            error = ""
            try:
                with server.connect() as conn:
                    _exec_all(conn, syn.get("setup", {}).get(server.engine, []))
                    try:
                        _exec_all(conn, [server_sql(specs, syn_id, server.engine, ex["sql"])])
                        ok = True
                    except Exception as exc:
                        ok, error = False, f"{exc}".splitlines()[0]
            except Exception as exc:
                problems.append(f"setup failed: {exc}")
                ok = None
            finally:
                _cleanup(server, syn.get("cleanup", {}).get(server.engine, []))
            if ok is not None and ok != server_should_accept(ex["expect"]):
                problems.append(f"server {'accepts' if ok else 'rejects'}" + (f" ({error})" if error else ""))
            detail = "; ".join(problems)
            if detail:
                detail = f"expect={ex['expect']}: {detail} - {ex['sql']}"
            report.add(Result(server.target["id"], server.version, "syntax", name,
                              "fail" if problems else "pass", detail))


def run_keywords(specs: Specs, server: Server, report: Report):
    """The stored keyword file for this exact version must still match the server."""
    from . import keywords as kw

    stored = kw.stored_files().get(server.engine, {}).get(server.version)
    if stored is None:
        report.add(Result(server.target["id"], server.version, "keywords", server.engine, "observed",
                          f"no keywords/{server.engine}/{server.version}.yaml - run `dbspecs keywords --target {server.target['id']}`"))
        return
    try:
        problems = kw.compare(stored, kw.generate(specs, server))
    except Exception as exc:
        problems = [f"{type(exc).__name__}: {exc}".splitlines()[0]]
    report.add(Result(server.target["id"], server.version, "keywords", server.engine,
                      "fail" if problems else "pass", "; ".join(problems)))


def report_json(report: Report) -> dict:
    return {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "results": [r.as_dict() for r in report.results],
    }


def run_inventory(specs: Specs, server: Server, report: Report):
    """Engines with an inventory need one for every tested version (new version = new items)."""
    from .inventory import stored
    versions = stored().get(server.engine)
    if versions is None:
        return
    if server.version in versions:
        report.add(Result(server.target["id"], server.version, "inventory", server.engine, "pass"))
    else:
        report.add(Result(server.target["id"], server.version, "inventory", server.engine, "observed",
                          f"no inventory/{server.engine}/{server.version}.yaml (have {', '.join(versions)}) - run "
                          f"`dbspecs inventory --target {server.target['id']}` and classify new items in scope/"))


TYPE_FLAGS = {"mysql": {"UNSIGNED": 32, "ZEROFILL": 64, "BINARY": 128, "BLOB": 16, "ENUM": 256, "SET": 2048}}


def run_protocol(specs: Specs, server: Server, report: Report):
    """Every protocol profile with a type_probe: wire type code, type flags and binary charset per column."""
    eng = specs.get("engine", server.engine)
    for prof in eng["protocols"]:
        probe = prof.get("type_probe")
        if not probe:
            continue
        mapping = {}
        for m in prof["type_mapping"]:
            if in_range(server.version, m):
                mapping[m["type"]] = m
        name = f"{prof['id']}.type-mapping"
        problems = []
        try:
            with server.connect() as conn:
                _exec_all(conn, _statements(probe["setup"], server.version))
                with conn.cursor() as cur:
                    cur.execute(probe["query"])
                    cur.fetchall()
                    fields = getattr(getattr(cur, "_result", None), "fields", None)  # pymysql: flags + charsetnr
                    cols = [(f.name, f.type_code, f.flags, f.charsetnr) for f in fields] if fields else \
                           [(d[0], d[1], None, None) for d in cur.description]
        except Exception as exc:
            report.add(Result(server.target["id"], server.version, "protocol", name, "fail", f"probe failed: {exc}"))
            continue
        finally:
            _cleanup(server, probe.get("cleanup", []))
        # a column may name alternatives (mva|uint_set): the first type mapped for this version
        columns = {c: next((t for t in spec.split("|") if t in mapping), spec.split("|")[0])
                   for c, spec in probe["columns"].items()}
        flagbits = TYPE_FLAGS.get(prof["id"], {})
        seen = {c[0] for c in cols}
        for col, etype in columns.items():
            if col not in seen and etype in mapping:
                problems.append(f"{col}: column missing from the result")
        for col, code, flags, charsetnr in cols:
            etype = columns.get(col)
            m = mapping.get(etype)
            if m is None:
                continue
            if code != m["code"]:
                problems.append(f"{col} ({etype}): code {code}, expected {m['code']}")
            if flags is not None and flagbits:
                got = sorted(n for n, b in flagbits.items() if flags & b)
                if got != sorted(m.get("flags", [])):
                    problems.append(f"{col} ({etype}): flags {got}, expected {sorted(m.get('flags', []))}")
            if charsetnr is not None and "binary" in m and (charsetnr == 63) != m["binary"]:
                problems.append(f"{col} ({etype}): charsetnr {charsetnr}, expected binary={m['binary']}")
        report.add(Result(server.target["id"], server.version, "protocol", name,
                          "fail" if problems else "pass", "; ".join(problems)))
