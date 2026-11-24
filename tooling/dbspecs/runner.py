"""Run capability probes and test cases against real servers."""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field

from .servers import Server, fetch_dicts
from .specs import Specs, in_range, quote_identifier, quote_literal, render, statement_for, variant_for
from .syntax import examples_for, grammar_accepts, grammar_should_accept, server_should_accept


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


def _exec_all(conn, statements):
    with conn.cursor() as cur:
        for sql in statements:
            if sql.strip():  # rendered templates can leave empty optional steps
                cur.execute(sql)


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
            if server.engine not in probe["engines"]:
                continue
            name = cap_id + (f"#{probe['name']}" if "name" in probe else "")
            try:
                with server.connect() as conn:
                    _exec_all(conn, probe.get("setup", []))
                    try:
                        _exec_all(conn, probe["statements"])
                        ok = True
                        if "check" in probe:
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
    return {k: (v.replace("{{schema}}", server.schema) if isinstance(v, str) else v) for k, v in params.items()}


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
    with conn.cursor() as cur:
        cur.execute(server.format_sql(sql), params)
        rows = fetch_dicts(cur)
    problems = []
    expected_cols = [c["name"] for c in query["result"]["columns"]]
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
    try:
        with conn.cursor() as cur:
            cur.execute(ddl)
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


def run_tests(specs: Specs, server: Server, report: Report):
    for test_id, test in sorted(specs.docs["test"].items()):
        if server.engine not in test["engines"]:
            continue
        if not in_range(server.version, test.get("versions", {}).get(server.engine, {})):
            report.add(Result(server.target["id"], server.version, "test", test_id, "skip",
                              "outside the test's version range"))
            continue
        problems: list[str] = []
        try:
            with server.connect() as conn:
                _exec_all(conn, _statements(test.get("setup", {}).get(server.engine), server.version))
                for step in test["steps"]:
                    if "engines" in step and not (server.engine in step["engines"]
                                                  and in_range(server.version, step["engines"][server.engine])):
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
                        _exec_all(conn, [ex["sql"]])
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


def report_json(report: Report) -> dict:
    return {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "results": [r.as_dict() for r in report.results],
    }
