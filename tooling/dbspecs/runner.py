"""Run capability probes and test cases against real servers."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from .servers import Server, fetch_dicts, to_pyformat
from .specs import Specs, in_range, quote_identifier, render, statement_for, variant_for
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
            cur.execute(sql)


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
        values[name] = value
    templates = impl.get("steps") or [impl["template"]]
    return [render(t, values) for t in templates]


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
        if len(matches) != 1:
            problems.append(f"{exp['match']}: {len(matches)} matching rows")
            continue
        row = matches[0]
        for k, v in exp["values"].items():
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
                _exec_all(conn, test.get("setup", {}).get(server.engine, []))
                for step in test["steps"]:
                    params = _resolve_params({**step.get("params", {}),
                                              **step.get("params_by_engine", {}).get(server.engine, {})}, server)
                    if "operation" in step:
                        _exec_all(conn, _render_operation(specs, step["operation"], server, params))
                        continue
                    query = specs.get("query", step["query"])
                    var = variant_for(query, server.engine, server.version)
                    if not var:
                        problems.append(f"no variant of {step['query']} for {server.engine} {server.version}")
                        break
                    sql = (specs.path("query", step["query"]).parent / var["file"]).read_text(encoding="utf-8")
                    with conn.cursor() as cur:
                        cur.execute(to_pyformat(sql), params)
                        rows = fetch_dicts(cur)
                    expected_cols = [c["name"] for c in query["result"]["columns"]]
                    if rows and list(rows[0]) != expected_cols:
                        problems.append(f"{step['query']}: columns {list(rows[0])} != contract {expected_cols}")
                    problems += [f"{step['query']}: {p}" for p in _check_contract(query, rows)]
                    problems += [f"{step['query']}: {p}" for p in _check(step.get("expect", {}), rows, server)]
        except Exception as exc:
            problems.append(f"{type(exc).__name__}: {exc}".splitlines()[0])
        finally:
            _cleanup(server, test.get("cleanup", {}).get(server.engine, []))
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
