"""dbspecs command line: validate | build | test."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .build import build
from .runner import Report, report_json, run_probes, run_syntax, run_tests
from .servers import running
from .specs import ROOT, Specs, load_yaml
from .validate import validate

VERIFICATION = ROOT / "dist" / "verification.json"


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
    for target in targets:
        print(f"== {target['id']} ({target['image']})", flush=True)
        try:
            with running(target) as server:
                print(f"   server version {server.version}", flush=True)
                n = len(report.results)
                run_probes(specs, server, report)
                run_tests(specs, server, report)
                run_syntax(specs, server, report)
                for r in report.results[n:]:
                    mark = {"pass": "ok  ", "fail": "FAIL", "observed": "obs ", "skip": "skip"}.get(r.outcome, r.outcome)
                    print(f"   {mark} {r.kind:6} {r.id}" + (f"  - {r.detail}" if r.detail else ""))
        except Exception as exc:
            print(f"   FAIL could not start/connect: {exc}")
            from .runner import Result
            report.add(Result(target["id"], "", "target", target["id"], "fail", str(exc)))
    VERIFICATION.parent.mkdir(parents=True, exist_ok=True)
    VERIFICATION.write_text(json.dumps(report_json(report), indent=2) + "\n", encoding="utf-8")
    failed = report.failed()
    print(f"\n{len(report.results)} result(s), {len(failed)} failed -> {VERIFICATION.relative_to(ROOT)}")
    return 1 if failed else 0


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
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
