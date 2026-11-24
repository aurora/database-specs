"""dbspecs command line: validate | build | test."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .build import build
from .runner import Report, report_json, run_keywords, run_probes, run_syntax, run_tests
from .servers import running
from .specs import ROOT, Specs, load_yaml
from .validate import validate

VERIFICATION = ROOT / "dist" / "verification.json"
VERIFICATION_DIR = ROOT / "dist" / "verification"  # latest results per target; merged into VERIFICATION


def merge_verification() -> dict:
    """Combine the latest result file of every target (a run with --target only replaces those)."""
    import datetime as dt

    targets = {t["id"] for t in load_yaml(ROOT / "tests" / "targets.yaml")["targets"]}
    runs, results = {}, []
    for path in sorted(VERIFICATION_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if data["target"] not in targets:
            continue  # target was removed from targets.yaml
        runs[data["target"]] = {k: data[k] for k in ("engine", "version", "generated_at")}
        results += data["results"]
    merged = {"generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
              "targets": runs, "results": results}
    VERIFICATION.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
    return merged


def cmd_validate(args) -> int:
    errors = validate(Specs.load())
    for e in errors:
        print(e)
    print(f"{len(errors)} problem(s)" if errors else "ok")
    return 1 if errors else 0


def cmd_build(args) -> int:
    specs = Specs.load()
    errors = validate(specs)
    if errors:
        print("\n".join(errors))
        return 1
    out = build(specs, Path(args.out), VERIFICATION)
    print(f"wrote {out.relative_to(ROOT) if out.is_relative_to(ROOT) else out}")
    return 0


def cmd_test(args) -> int:
    specs = Specs.load()
    errors = validate(specs)
    if errors:
        print("\n".join(errors))
        return 1
    targets = load_yaml(ROOT / "tests" / "targets.yaml")["targets"]
    if args.target:
        targets = [t for t in targets if t["id"] in args.target or t["engine"] in args.target]
    report = Report()
    VERIFICATION_DIR.mkdir(parents=True, exist_ok=True)
    for target in targets:
        print(f"== {target['id']} ({target.get('image', 'local Python')})", flush=True)
        n_before = len(report.results)
        version = ""
        try:
            with running(target) as server:
                print(f"   server version {server.version}", flush=True)
                version = server.version
                n = len(report.results)
                run_probes(specs, server, report)
                run_tests(specs, server, report)
                run_syntax(specs, server, report)
                run_keywords(specs, server, report)
                for r in report.results[n:]:
                    mark = {"pass": "ok  ", "fail": "FAIL", "observed": "obs ", "skip": "skip"}.get(r.outcome, r.outcome)
                    print(f"   {mark} {r.kind:6} {r.id}" + (f"  - {r.detail}" if r.detail else ""))
        except Exception as exc:
            print(f"   FAIL could not start/connect: {exc}")
            from .runner import Result
            report.add(Result(target["id"], "", "target", target["id"], "fail", str(exc)))
        part = report_json(Report(report.results[n_before:]))
        part.update({"target": target["id"], "engine": target["engine"], "version": version})
        (VERIFICATION_DIR / f"{target['id']}.json").write_text(json.dumps(part, indent=2) + "\n", encoding="utf-8")
    merged = merge_verification()
    failed = report.failed()
    print(f"\n{len(report.results)} result(s), {len(failed)} failed "
          f"({len(merged['targets'])} targets in {VERIFICATION.relative_to(ROOT)})")
    try:
        from .coverage import write_coverage
        print(f"coverage -> {write_coverage(Specs.load()).relative_to(ROOT)}")
    except ImportError:
        pass
    return 1 if failed else 0


def cmd_keywords(args) -> int:
    from .keywords import generate, write

    specs = Specs.load()
    targets = load_yaml(ROOT / "tests" / "targets.yaml")["targets"]
    if args.target:
        targets = [t for t in targets if t["id"] in args.target or t["engine"] in args.target]
    deferred = []
    for rnd in (1, 2):  # probe-only engines run last: their candidates come from the complete lists
        for target in (targets if rnd == 1 else deferred):
            with running(target) as server:
                doc = generate(specs, server)
                if rnd == 1 and doc["method"] == "probe":
                    deferred.append(target)
                    continue
                path = write(doc)
                print(f"{target['id']:16} {server.version:10} {doc['method']:12} "
                      f"reserved {len(doc['reserved']):4}  nonreserved {len(doc['nonreserved']):4}  -> {path.relative_to(ROOT)}",
                      flush=True)
    return 0


def cmd_coverage(args) -> int:
    from .coverage import write_coverage

    specs = Specs.load()
    errors = validate(specs)
    if errors:
        print("\n".join(errors))
        return 1
    md = write_coverage(specs)
    print(f"wrote {md.relative_to(ROOT)} and dist/coverage.html")
    return 0


def cmd_show(args) -> int:
    from .show import ShowError, render_text, resolve

    try:
        res = resolve(Specs.load(), args.kind, args.id, args.engine, args.version, args.sql)
    except ShowError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(res, indent=2, ensure_ascii=False) if args.json else render_text(res))
    if res["kind"] == "query" and res.get("variant", True) is None:
        return 3  # no variant for this engine/version
    return 0


SHOW_HELP = """\
kinds:
  list [KIND]                 ids and titles (all kinds, or one)
  profile                     everything for --engine/--version at a glance
  capability ID               feature status (resolved with --engine/--version)
  query ID                    query contract (+ SQL variant with --engine/--version)
  operation ID                SQL template for client operations
  syntax ID                   EBNF (filtered with --version), examples; --sql checks a statement
  keywords [WORD]             keyword lists for --engine/--version (newest generated version <= it)
  engine ID | lexical ID | protocol ID   the raw document (or --engine for engine/lexical)

IDs can be shortened to their last segment if unique (e.g. 'returning').

exit codes: 0 ok, 2 bad input, 3 query has no variant for this engine/version.

examples:
  dbspecs show profile --engine mariadb --version 11.4
  dbspecs show capability returning --engine mysql --version 8.0.13
  dbspecs show query list-indexes --engine postgresql --version 16
  dbspecs show syntax create-index --engine mysql --version 5.7 --sql "CREATE INDEX i ON t ((a+1))"
"""


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="dbspecs")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("validate", help="validate all spec files").set_defaults(func=cmd_validate)
    p = sub.add_parser("build", help="bundle specs into dist/db-specs.json")
    p.add_argument("--out", default=str(ROOT / "dist" / "db-specs.json"))
    p.set_defaults(func=cmd_build)
    p = sub.add_parser("test", help="run probes and test cases against containers")
    p.add_argument("--target", action="append", help="target id or engine (repeatable)")
    p.set_defaults(func=cmd_test)
    sub.add_parser("coverage", help="write COVERAGE.md and dist/coverage.html (matrix spec x engine + roadmap)").set_defaults(func=cmd_coverage)
    p = sub.add_parser("keywords", help="generate keywords/<engine>/<version>.yaml from the test targets")
    p.add_argument("--target", action="append", help="target id or engine (repeatable)")
    p.set_defaults(func=cmd_keywords)
    p = sub.add_parser("show", help="resolve specs for an engine/version (for people and agents)",
                       epilog=SHOW_HELP, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("kind", help="list, profile, capability, query, operation, syntax, engine, lexical, protocol")
    p.add_argument("id", nargs="?", help="spec id (or kind for 'list')")
    p.add_argument("--engine", "-e")
    p.add_argument("--version", "-v", help="server version, e.g. 8.0.13 (range bounds: since incl., until excl.)")
    p.add_argument("--sql", help="syntax only: check this statement against the grammar")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.set_defaults(func=cmd_show)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
