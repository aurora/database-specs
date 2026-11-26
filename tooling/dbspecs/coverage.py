"""Coverage matrix: what exists / is tested per spec item and engine, plus the roadmap.

Generated only from the specs and the merged test results (dist/verification.json), so it cannot
drift from the repository. Output: COVERAGE.md (checked in) and dist/coverage.html.
"""

from __future__ import annotations

import datetime as dt
import html
import json
from dataclasses import dataclass
from pathlib import Path

from .specs import ROOT, Specs, load_yaml, parse_version, statement_for, variant_for

ENGINE_ORDER = ["mysql", "mariadb", "postgresql", "sqlserver", "sqlite"]
VERIFICATION = ROOT / "dist" / "verification.json"
ROADMAP = ROOT / "roadmap.yaml"

LEGEND = [
    ("✅", "tested against real servers"),
    ("◐", "partly: some versions missing or unsupported"),
    ("📄", "documented, no automated test"),
    ("➖", "not applicable: the engine has no such feature"),
    ("⬜", "missing"),
    ("❓", "not researched"),
    ("❌", "test failed in the last run"),
]


STATE = {"✅": "ok", "◐": "part", "📄": "doc", "➖": "na", "⬜": "miss", "❓": "unk", "❌": "fail"}


@dataclass
class Cell:
    symbol: str
    detail: str = ""


class Results:
    """Test outcomes from dist/verification.json, indexed by engine."""

    def __init__(self):
        self.data = json.loads(VERIFICATION.read_text(encoding="utf-8")) if VERIFICATION.is_file() else None
        targets = {t["id"]: t["engine"] for t in load_yaml(ROOT / "tests" / "targets.yaml")["targets"]}
        self.by_engine: dict[str, list[dict]] = {}
        for r in (self.data or {}).get("results", []):
            eng = targets.get(r["target"])
            if eng:
                self.by_engine.setdefault(eng, []).append(r)

    def outcomes(self, engine: str, kind: str, match) -> set[str]:
        return {r["outcome"] for r in self.by_engine.get(engine, []) if r["kind"] == kind and match(r["id"])}


def _engines(specs: Specs) -> list[str]:
    rest = sorted(e for e in specs.docs["engine"] if e not in ENGINE_ORDER)
    return [e for e in ENGINE_ORDER if e in specs.docs["engine"]] + rest


def _series(specs: Specs, engine: str, tested_versions: list[str] | None = None) -> list[str]:
    """Version series that count for coverage: all except end-of-life series without a test target."""
    today = dt.date.today().isoformat()
    out = []
    for v in specs.get("engine", engine)["versions"]:
        series = parse_version(v["series"])[: len(v["series"].split("."))]
        tested = any(parse_version(t)[: len(series)] == series for t in (tested_versions or []))
        if "eol" in v and v["eol"] < today and not tested:
            continue
        out.append(v["series"])
    return out


def _tested(outcomes: set[str], fallback: Cell) -> Cell:
    if "fail" in outcomes:
        return Cell("❌", "failed in the last test run")
    if outcomes & {"pass", "observed"}:
        return Cell("✅")
    return fallback


def _partial(cell: Cell, missing: list[str], what: str) -> Cell:
    if missing and cell.symbol in ("✅", "📄"):
        return Cell("◐", f"{what}: {', '.join(missing)}" + (f"; {cell.detail}" if cell.detail else ""))
    return cell


def _tests_using(specs: Specs) -> dict[tuple[str, str], set[str]]:
    """(kind, id) -> test ids that exercise a query / operation."""
    out: dict[tuple[str, str], set[str]] = {}
    for test_id, test in specs.docs["test"].items():
        for step in test["steps"]:
            rt = step.get("roundtrip")
            if "query" in step:
                out.setdefault(("query", step["query"]), set()).add(test_id)
            if "operation" in step:
                out.setdefault(("operation", step["operation"]), set()).add(test_id)
            if rt:
                out.setdefault(("operation", rt["operation"]), set()).add(test_id)
                for c in rt["compare"]:
                    out.setdefault(("query", c["query"]), set()).add(test_id)
    return out


def matrix(specs: Specs) -> dict:
    res = Results()
    engines = _engines(specs)
    using = _tests_using(specs)
    sections: dict[str, list[dict]] = {}
    tested: dict[str, list[str]] = {}
    for run in ((res.data or {}).get("targets") or {}).values():
        if run.get("version"):
            tested.setdefault(run["engine"], []).append(run["version"])

    def test_outcomes(kind, item_id, engine):
        tests = {t for t in using.get((kind, item_id), set()) if engine in specs.get("test", t)["engines"]}
        return res.outcomes(engine, "test", lambda i: i in tests)

    # capabilities ---------------------------------------------------------------
    rows = []
    for cid, cap in sorted(specs.docs["capability"].items()):
        cells = {}
        for e in engines:
            stmts = cap["support"].get(e)
            if not stmts:
                cells[e] = Cell("❓", "not researched")
                continue
            summary = "; ".join(f"{s['status']} {_range(s)}".strip() for s in stmts)
            cell = _tested(res.outcomes(e, "probe", lambda i, c=cid: i == c or i.startswith(c + "#")), Cell("📄", summary))
            if cell.symbol == "✅":
                cell.detail = summary
            missing = [s for s in _series(specs, e, tested.get(e)) if statement_for(stmts, s) is None]
            cells[e] = _partial(cell, missing, "no statement for")
        rows.append({"id": cid, "title": cap["title"], "cells": cells})
    sections["Capabilities"] = rows

    # queries --------------------------------------------------------------------------
    rows = []
    for qid, q in sorted(specs.docs["query"].items()):
        cells = {}
        na = q.get("not_applicable", {})
        for e in engines:
            if not any(v["engine"] == e for v in q["variants"]):
                cells[e] = Cell("➖", na[e]) if e in na else Cell("⬜", "no variant")
                continue
            cell = _tested(test_outcomes("query", qid, e), Cell("📄", "no test case"))
            missing = [s for s in _series(specs, e, tested.get(e)) if variant_for(q, e, s) is None]
            cells[e] = _partial(cell, missing, "no variant for")
        rows.append({"id": qid, "title": q["title"], "cells": cells})
    sections["Queries"] = rows

    # operations -----------------------------------------------------------------------
    rows = []
    for oid, op in sorted(specs.docs["operation"].items()):
        cells = {}
        for e in engines:
            impls = op["implementations"].get(e)
            if not impls:
                cells[e] = Cell("⬜", "no implementation")
                continue
            usable = [i for i in impls if i["status"] in ("supported", "partial")]
            if not usable:
                notes = "; ".join(n for i in impls for n in i.get("notes", []))
                cells[e] = Cell("➖", notes or "unsupported")
                continue
            if any(i.get("method") == "protocol" for i in usable):
                cell = Cell("📄", "client-library call, not testable through SQL")
            else:
                cell = _tested(test_outcomes("operation", oid, e), Cell("📄", "no test case"))
            missing = [s for s in _series(specs, e, tested.get(e))
                       if (statement_for(impls, s) or {}).get("status") not in ("supported", "partial")]
            cells[e] = _partial(cell, missing, "not available for")
        rows.append({"id": oid, "title": op["title"], "cells": cells})
    sections["Operations"] = rows

    # syntax ---------------------------------------------------------------------------------
    rows = []
    for sid, syn in sorted(specs.docs["syntax"].items()):
        cells = {}
        for e in engines:
            if e not in syn["grammars"]:
                na = syn.get("not_applicable", {})
                cells[e] = Cell("➖", na[e]) if e in na else Cell("⬜", "no grammar")
                continue
            cells[e] = _tested(res.outcomes(e, "syntax", lambda i, s=sid: i.startswith(s + "#")),
                               Cell("📄", "examples not run"))
        rows.append({"id": sid, "title": syn["title"], "cells": cells})
    sections["Syntax"] = rows

    # protocol profiles ------------------------------------------------------------------------
    cells = {}
    for e in engines:
        profs = specs.get("engine", e)["protocols"]
        if not any(p.get("type_mapping") for p in profs):
            cells[e] = Cell("⬜", "no type_mapping in the protocol profile")
            continue
        if not any(p.get("type_probe") for p in profs):
            cells[e] = Cell("📄", "type_mapping without type_probe")
            continue
        cells[e] = _tested(res.outcomes(e, "protocol", lambda i: i.endswith(".type-mapping")), Cell("📄", "probe not run"))
    sections["Protocol"] = [{"id": "protocol-profile", "title": "Wire type codes / flags per column type", "cells": cells}]

    # keywords ---------------------------------------------------------------------------------
    files: dict[str, list[dict]] = {}
    for kw in specs.docs["keywords"].values():
        files.setdefault(kw["engine"], []).append(kw)
    cells = {}
    for e in engines:
        docs = sorted(files.get(e, []), key=lambda d: parse_version(d["version"]))
        if not docs:
            cells[e] = Cell("⬜", "no keyword data")
            continue
        incomplete = [d["version"] for d in docs if not d["complete"]]
        versions = ", ".join(d["version"] for d in docs)
        cells[e] = Cell("◐", f"reserved words only: {', '.join(incomplete)} (data: {versions})") if incomplete \
            else Cell("✅", f"data: {versions}")
    sections["Keywords"] = [{"id": "keywords", "title": "Keyword lists per version", "cells": cells}]

    roadmap = load_yaml(ROADMAP)["items"] if ROADMAP.is_file() else []
    runs = (res.data or {}).get("targets", {})
    return {"engines": engines, "sections": sections, "roadmap": roadmap, "runs": runs,
            "inventory": inventory_summary(specs)}


def inventory_summary(specs: Specs) -> list[dict]:
    """Per engine inventory: item counts per status and the rule groups behind them."""
    from . import inventory as inv
    from .keywords import stored_files

    keyword_files = stored_files()
    scopes = {d["engine"]: d for d in specs.docs["scope"].values()}
    out = []
    for doc in sorted(specs.docs["inventory"].values(), key=lambda d: (d["engine"], parse_version(d["version"]))):
        result = inv.classify(doc, scopes.get(doc["engine"]), keyword_files.get(doc["engine"], {}).get(doc["version"]))
        counts: dict[str, int] = {}
        groups: dict[int, dict] = {}
        for item_id, rule in result.items():
            status = rule["status"] if rule else "unclassified"
            counts[status] = counts.get(status, 0) + 1
            g = groups.setdefault(id(rule), {"rule": rule, "status": status, "items": []})
            g["items"].append(item_id)
        out.append({"engine": doc["engine"], "version": doc["version"], "counts": counts,
                    "kinds": {k: sum(1 for i in doc["items"] if i["kind"] == k) for k in ("keyword", "grammar", "function", "type", "option", "operator", "privilege", "docs")},
                    "groups": list(groups.values())})
    return out


def _range(stmt: dict) -> str:
    parts = []
    if "since" in stmt:
        parts.append(f">= {stmt['since']}")
    if "until" in stmt:
        parts.append(f"< {stmt['until']}")
    return " ".join(parts)


def _summary(m: dict) -> dict[str, dict[str, int]]:
    out = {e: {} for e in m["engines"]}
    for rows in m["sections"].values():
        for row in rows:
            for e, cell in row["cells"].items():
                out[e][cell.symbol] = out[e].get(cell.symbol, 0) + 1
    return out


def render_markdown(specs: Specs, m: dict) -> str:
    names = {e: specs.get("engine", e)["name"] for e in m["engines"]}
    runs = m["runs"]
    dates = sorted(r["generated_at"][:10] for r in runs.values())
    lines = [
        "# Coverage",
        "",
        "Generated by `uv run dbspecs coverage` (also after every `dbspecs test`) - do not edit.",
        f"Test results: {len(runs)} targets" + (f", runs from {dates[0]} to {dates[-1]}." if dates else " (no test run yet)."),
        "Planned items come from [roadmap.yaml](roadmap.yaml).",
        "",
        " · ".join(f"{s} {t}" for s, t in LEGEND),
        "",
        "## Summary",
        "",
        "| | " + " | ".join(names[e] for e in m["engines"]) + " |",
        "|---|" + "---|" * len(m["engines"]),
    ]
    summary = _summary(m)
    for sym, text in LEGEND:
        counts = [str(summary[e].get(sym, "")) for e in m["engines"]]
        if any(counts):
            lines.append(f"| {sym} {text} | " + " | ".join(counts) + " |")
    for section, rows in m["sections"].items():
        lines += ["", f"## {section}", "",
                  "| id | title | " + " | ".join(names[e] for e in m["engines"]) + " | notes |",
                  "|---|---|" + "---|" * len(m["engines"]) + "---|"]
        for row in rows:
            notes = "; ".join(f"{e}: {c.detail}" for e, c in row["cells"].items()
                              if c.symbol in ("◐", "❌", "⬜") and c.detail)
            lines.append(f"| `{row['id']}` | {row['title']} | "
                         + " | ".join(row["cells"][e].symbol for e in m["engines"])
                         + f" | {_md(notes)} |")
    lines += _inventory_markdown(m.get("inventory", []))
    lines += ["", "## Planned", "", "| priority | kind | id | title | engines |", "|---|---|---|---|---|"]
    order = {"high": 0, "medium": 1, "low": 2}
    for item in sorted(m["roadmap"], key=lambda i: (order[i["priority"]], i["kind"], i["id"])):
        engines = "-" if item["kind"] == "engine" else (", ".join(item.get("engines", [])) or "all")
        lines.append(f"| {item['priority']} | {item['kind']} | `{item['id']}` | {_md(item['title'])} | {engines} |")
    return "\n".join(lines) + "\n"


INVENTORY_STATUS = [("covered", "✅"), ("planned", "🗓"), ("open", "⬜"), ("out-of-scope", "➖"), ("unclassified", "❓")]


def _inventory_markdown(inventories: list[dict]) -> list[str]:
    if not inventories:
        return []
    lines = ["", "## Inventory", "",
             "Everything the engine has, from its own parser grammar and the manual's reference index "
             "(`inventory/`), classified in `scope/<engine>.yaml`.", "",
             "| engine | version | items (keywords / grammar / functions + types / options + operators + privileges / docs) | "
             + " | ".join(f"{sym} {st}" for st, sym in INVENTORY_STATUS) + " |",
             "|---|---|---|" + "---|" * len(INVENTORY_STATUS)]
    for inv in inventories:
        k = inv["kinds"]
        lines.append(f"| {inv['engine']} | {inv['version']} | {sum(k.values())} ({k["keyword"]} / {k["grammar"]} / {k["function"] + k["type"]} / {k["option"] + k["operator"] + k["privilege"]} / {k["docs"]}) | "
                     + " | ".join(str(inv["counts"].get(st, "")) for st, _ in INVENTORY_STATUS) + " |")
    for inv in inventories:
        lines += ["", f"### {inv['engine']} {inv['version']}: open and planned", "",
                  "| status | what | items | examples |", "|---|---|---|---|"]
        order = {"unclassified": 0, "open": 1, "planned": 2}
        for g in sorted((g for g in inv["groups"] if g["status"] in order),
                        key=lambda g: (order[g["status"]], -len(g["items"]))):
            rule = g["rule"] or {}
            what = rule.get("reason") or (f"roadmap `{rule['roadmap']}`" if rule.get("roadmap") else "no scope rule")
            examples = "; ".join(f"`{i}`" for i in g["items"][:3])
            lines.append(f"| {g['status']} | {_md(what)} | {len(g['items'])} | {_md(examples)} |")
    return lines


def _md(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def render_html(specs: Specs, m: dict) -> str:
    names = {e: specs.get("engine", e)["name"] for e in m["engines"]}
    parts = []
    for section, rows in m["sections"].items():
        head = "".join(f"<th>{html.escape(names[e])}</th>" for e in m["engines"])
        body = []
        for row in rows:
            tds = "".join(
                f'<td class="c s{STATE[row["cells"][e].symbol]}" title="{html.escape(row["cells"][e].detail)}">{row["cells"][e].symbol}</td>'
                for e in m["engines"])
            body.append(f"<tr><td><code>{html.escape(row['id'])}</code></td><td>{html.escape(row['title'])}</td>{tds}</tr>")
        parts.append(f"<h2>{section}</h2><div class=scroll><table><thead><tr><th>id</th><th>title</th>{head}"
                     f"</tr></thead><tbody>{''.join(body)}</tbody></table></div>")
    road = "".join(
        f"<tr><td>{i['priority']}</td><td>{i['kind']}</td><td><code>{html.escape(i['id'])}</code></td>"
        f"<td>{html.escape(i['title'])}</td><td>{'-' if i['kind'] == 'engine' else html.escape(', '.join(i.get('engines', [])) or 'all')}</td></tr>"
        for i in sorted(m["roadmap"], key=lambda i: ({"high": 0, "medium": 1, "low": 2}[i["priority"]], i["id"])))
    legend = " &middot; ".join(f"{s} {html.escape(t)}" for s, t in LEGEND)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Spec Coverage</title>
<style>
:root {{ --bg:#fbfaf7; --fg:#1d1d1f; --muted:#6b6b70; --border:#e3e0d8; --card:#fff; }}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{ --bg:#17181a; --fg:#ececee; --muted:#9a9aa2; --border:#33343a; --card:#1f2023; }} }}
:root[data-theme="dark"] {{ --bg:#17181a; --fg:#ececee; --muted:#9a9aa2; --border:#33343a; --card:#1f2023; }}
body {{ margin:0; padding:24px 16px 64px; background:var(--bg); color:var(--fg); font:15px/1.5 system-ui, sans-serif; }}
main {{ max-width:1200px; margin:0 auto; }} .muted {{ color:var(--muted); }}
.scroll {{ overflow-x:auto; }} table {{ border-collapse:collapse; background:var(--card); width:100%; }}
th, td {{ border:1px solid var(--border); padding:4px 8px; text-align:left; font-size:14px; }}
td.c {{ text-align:center; cursor:help; }} code {{ font-size:13px; }}
td.sok {{ background:#dff3e3; }} td.spart {{ background:#fff1cc; }} td.sdoc {{ background:#e6eefb; }}
td.sna {{ background:transparent; color:var(--muted); }} td.smiss {{ background:#fde2e1; }}
td.sunk {{ background:#eeeeee; }} td.sfail {{ background:#f8b4b0; }}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) td.sok {{ background:#1f3a27; }}
  :root:not([data-theme="light"]) td.spart {{ background:#3d3418; }} :root:not([data-theme="light"]) td.sdoc {{ background:#1e2a40; }}
  :root:not([data-theme="light"]) td.smiss {{ background:#432423; }} :root:not([data-theme="light"]) td.sunk {{ background:#2a2a2d; }}
  :root:not([data-theme="light"]) td.sfail {{ background:#6a2622; }} }}
</style></head><body><main>
<h1>Spec coverage</h1>
<p class=muted>Generated {dt.date.today().isoformat()} from the specs and the merged test results. Hover a cell for details.</p>
<p>{legend}</p>
{''.join(parts)}
<h2>Planned</h2><div class=scroll><table><thead><tr><th>priority</th><th>kind</th><th>id</th><th>title</th><th>engines</th></tr></thead>
<tbody>{road}</tbody></table></div>
</main></body></html>
"""


def write_coverage(specs: Specs) -> Path:
    m = matrix(specs)
    md = ROOT / "COVERAGE.md"
    md.write_text(render_markdown(specs, m), encoding="utf-8")
    out = ROOT / "dist" / "coverage.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_html(specs, m), encoding="utf-8")
    return md
