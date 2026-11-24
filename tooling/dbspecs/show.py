"""`dbspecs show`: resolve specs for one engine/version so consumers don't re-implement range logic.

Every resolver returns plain data (used for --json); render_text() turns it into compact text.
"""

from __future__ import annotations

from .ebnf import grammar_to_ebnf, matches, tokenize
from .specs import Specs, parse_version, statement_for, variant_for
from .syntax import examples_for, lexical_for, load_grammar

KIND_ALIASES = {
    "capability": "capability", "capabilities": "capability", "cap": "capability",
    "query": "query", "queries": "query",
    "operation": "operation", "operations": "operation", "op": "operation",
    "syntax": "syntax",
    "engine": "engine", "engines": "engine",
    "lexical": "lexical",
    "protocol": "protocol", "protocols": "protocol",
}


class ShowError(Exception):
    pass


# --- helpers ----------------------------------------------------------------

def _resolve_id(specs: Specs, kind: str, ident: str) -> str:
    ids = specs.docs[kind]
    if ident in ids:
        return ident
    hits = [i for i in ids if i.endswith("." + ident)]
    if len(hits) == 1:
        return hits[0]
    if hits:
        raise ShowError(f"'{ident}' is ambiguous: {', '.join(sorted(hits))}")
    raise ShowError(f"unknown {kind} '{ident}'. Known: {', '.join(sorted(ids))}")


def _check_engine(specs: Specs, engine: str | None):
    if engine and engine not in specs.docs["engine"]:
        raise ShowError(f"unknown engine '{engine}'. Known: {', '.join(sorted(specs.docs['engine']))}")


def _check_version(version: str | None):
    if version:
        try:
            parse_version(version)
        except ValueError:
            raise ShowError(f"not a version: '{version}' (use e.g. 8.0.13)")


def _range_text(entry: dict) -> str:
    parts = []
    if "since" in entry:
        parts.append(f">= {entry['since']}")
    if "until" in entry:
        parts.append(f"< {entry['until']}")
    return ", ".join(parts) or "all versions"


def _evidence(entry: dict) -> list[str]:
    return sorted({s["evidence"] for s in entry.get("sources", [])})


# --- resolvers --------------------------------------------------------------

def resolve_list(specs: Specs, kind: str | None) -> dict:
    kinds = [kind] if kind else ["engine", "capability", "query", "operation", "syntax", "lexical", "protocol"]
    out = {}
    for k in kinds:
        out[k] = {i: (d.get("title") or d.get("name") or d.get("description", "")) for i, d in sorted(specs.docs[k].items())}
    return {"kind": "list", "items": out}


def resolve_capability(specs: Specs, cap_id: str, engine: str | None, version: str | None) -> dict:
    cap = specs.get("capability", cap_id)
    res = {"kind": "capability", "id": cap_id, "title": cap["title"], "description": cap.get("description")}
    engines = [engine] if engine else sorted(set(specs.docs["engine"]) | set(cap["support"]))
    res["engines"] = {}
    for e in engines:
        stmts = cap["support"].get(e, [])
        if version and engine:
            st = statement_for(stmts, version)
            res["engines"][e] = {
                "version": version,
                "status": st["status"] if st else "unknown",
                "applies": _range_text(st) if st else None,
                "notes": st.get("notes", []) if st else [],
                "evidence": _evidence(st) if st else [],
            }
        else:
            res["engines"][e] = [{"range": _range_text(s), "status": s["status"], "notes": s.get("notes", [])}
                                 for s in stmts] or [{"range": "all versions", "status": "unknown", "notes": []}]
    return res


def resolve_query(specs: Specs, q_id: str, engine: str | None, version: str | None) -> dict:
    q = specs.get("query", q_id)
    base = specs.path("query", q_id).parent
    res = {
        "kind": "query", "id": q_id, "title": q["title"], "description": q.get("description"),
        "parameters": q.get("parameters", []),
        "placeholders": ":name - translate to the driver's style (? for libmariadb, $1 for libpq)",
        "result": q["result"],
        "gaps": q.get("gaps", []),
    }
    if engine and version:
        var = variant_for(q, engine, version)
        if var:
            res["variant"] = {"engine": engine, "version": version, "applies": _range_text(var),
                              "file": str((base / var["file"]).relative_to(specs.root)),
                              "notes": var.get("notes", []),
                              "sql": (base / var["file"]).read_text(encoding="utf-8")}
        else:
            res["variant"] = None
    else:
        res["variants"] = [{"engine": v["engine"], "applies": _range_text(v), "file": v["file"]}
                           for v in q["variants"] if not engine or v["engine"] == engine]
    return res


def resolve_operation(specs: Specs, op_id: str, engine: str | None, version: str | None) -> dict:
    op = specs.get("operation", op_id)
    res = {"kind": "operation", "id": op_id, "title": op["title"], "description": op.get("description"),
           "parameters": op["parameters"]}
    if engine and version:
        impl = statement_for(op["implementations"].get(engine, []), version)
        res["implementation"] = None if impl is None else {
            "engine": engine, "version": version, "applies": _range_text(impl), **{
                k: impl[k] for k in ("status", "method", "template", "steps", "protocol_call", "requires",
                                     "transactional", "caveats", "notes") if k in impl}}
    else:
        res["implementations"] = {e: [{"range": _range_text(i), "status": i["status"],
                                       "template": i.get("template"), "method": i.get("method", "template")}
                                      for i in impls]
                                  for e, impls in op["implementations"].items() if not engine or e == engine}
    return res


def resolve_syntax(specs: Specs, syn_id: str, engine: str | None, version: str | None, sql: str | None) -> dict:
    syn = specs.get("syntax", syn_id)
    res = {"kind": "syntax", "id": syn_id, "title": syn["title"]}
    if not engine:
        res["grammars"] = {e: {"since": g.get("since"), "file": g["file"]} for e, g in syn["grammars"].items()}
        return res
    if engine not in syn["grammars"]:
        raise ShowError(f"no {syn_id} grammar for {engine}; available: {', '.join(syn['grammars'])}")
    g = syn["grammars"][engine]
    grammar = load_grammar(specs, syn_id, engine)
    if version:
        grammar = grammar.for_version(version)
    res.update({"engine": engine, "version": version, "start": g["start"], "notes": g.get("notes", []),
                "ebnf": grammar_to_ebnf(grammar),
                "builtins": "identifier, string_literal, integer, expression (loose: balanced tokens)"})
    if version:
        res["examples"] = [{"sql": ex["sql"], "expect": ex["expect"]} for _, ex in examples_for(syn, engine, version)]
    if sql is not None:
        if not version:
            raise ShowError("--sql needs --version")
        ok = matches(grammar, g["start"], tokenize(sql, lexical_for(specs, engine)))
        res["check"] = {"sql": sql, "grammar_accepts": ok,
                        "hint": "grammar only - the server may still reject it (names, types, semantics)"}
    return res


def resolve_doc(specs: Specs, kind: str, ident: str) -> dict:
    return {"kind": kind, "id": ident, "document": specs.get(kind, ident)}


def resolve_profile(specs: Specs, engine: str, version: str) -> dict:
    """Everything relevant for one engine/version at a glance (also usable as LLM context)."""
    eng = specs.get("engine", engine)
    lex = lexical_for(specs, engine)
    caps = {}
    for cap_id, cap in sorted(specs.docs["capability"].items()):
        st = statement_for(cap["support"].get(engine, []), version)
        caps[cap_id] = {"title": cap["title"], "status": st["status"] if st else "unknown",
                        "note": (st.get("notes") or [None])[0] if st else None}
    queries = {}
    for q_id, q in sorted(specs.docs["query"].items()):
        var = variant_for(q, engine, version)
        queries[q_id] = var["file"] if var else None
    ops = {}
    for op_id, op in sorted(specs.docs["operation"].items()):
        impl = statement_for(op["implementations"].get(engine, []), version)
        ops[op_id] = impl["status"] if impl else "unknown"
    syntax = [s for s, d in sorted(specs.docs["syntax"].items()) if engine in d["grammars"]]
    ident_quotes = [f"{q['open']}...{q['close']}" + (f" (if {q['when']['setting']}={q['when'].get('value')})"
                    if "when" in q else "") for q in lex["identifiers"]["quotes"] if "prefix" not in q]
    return {
        "kind": "profile", "engine": engine, "name": eng["name"], "version": version,
        "protocols": eng["protocols"],
        "lexical": {
            "identifier_quotes": ident_quotes,
            "preferred_quote": lex["identifiers"].get("preferred_quote"),
            "case_folding": lex["identifiers"].get("case_folding"),
            "max_identifier_length": lex["identifiers"].get("max_length"),
            "comments": [c["open"] + (" ... " + c["close"] if "close" in c else "") for c in lex["comments"]],
            "statement_terminator": lex["statements"]["terminator"],
            "client_delimiter_command": lex["statements"].get("client_delimiter_command", {}).get("keyword"),
            "parameter_placeholders": [p["pattern"] for p in lex.get("parameters", []) if "when" not in p],
        },
        "capabilities": caps,
        "queries": queries,
        "operations": ops,
        "syntax": syntax,
    }


def resolve(specs: Specs, kind: str, ident: str | None, engine: str | None, version: str | None,
            sql: str | None = None) -> dict:
    _check_engine(specs, engine)
    _check_version(version)
    if version and not engine:
        raise ShowError("--version needs --engine")
    if kind == "list":
        return resolve_list(specs, KIND_ALIASES.get(ident) if ident else None)
    if kind == "profile":
        if not (engine and version):
            raise ShowError("profile needs --engine and --version")
        return resolve_profile(specs, engine, version)
    if kind not in KIND_ALIASES:
        raise ShowError(f"unknown kind '{kind}'. Use: list, profile, {', '.join(sorted(set(KIND_ALIASES.values())))}")
    kind = KIND_ALIASES[kind]
    if kind in ("lexical", "engine", "protocol") and not ident:
        if kind == "protocol" or not engine:
            raise ShowError(f"{kind} needs an id" + (" or --engine" if kind != "protocol" else ""))
        ident = engine if kind == "engine" else specs.get("engine", engine)["lexical"]
    if not ident:
        return resolve_list(specs, kind)
    ident = _resolve_id(specs, kind, ident)
    if kind == "capability":
        return resolve_capability(specs, ident, engine, version)
    if kind == "query":
        return resolve_query(specs, ident, engine, version)
    if kind == "operation":
        return resolve_operation(specs, ident, engine, version)
    if kind == "syntax":
        return resolve_syntax(specs, ident, engine, version, sql)
    return resolve_doc(specs, kind, ident)


# --- text rendering ---------------------------------------------------------

def _bullets(lines, indent="  "):
    return [f"{indent}- {line}" for line in lines]


def render_text(res: dict) -> str:
    import yaml

    k = res["kind"]
    out: list[str] = []
    if k == "list":
        for kind, items in res["items"].items():
            out.append(f"{kind}:")
            width = max((len(i) for i in items), default=0)
            out += [f"  {i.ljust(width)}  {t}" for i, t in items.items()]
        return "\n".join(out)

    if k == "profile":
        out.append(f"{res['name']} {res['version']}  (engine: {res['engine']}, protocol: {', '.join(res['protocols'])})")
        out.append("lexical:")
        out += [f"  {key}: {v}" for key, v in res["lexical"].items()]
        out.append("capabilities:")
        for cap_id, c in res["capabilities"].items():
            note = f"  - {c['note']}" if c["note"] else ""
            out.append(f"  {c['status']:<11} {cap_id}{note}")
        out.append("queries (variant file, '-' = no variant):")
        out += [f"  {q}: {f or '-'}" for q, f in res["queries"].items()]
        out.append("operations:")
        out += [f"  {o}: {s}" for o, s in res["operations"].items()]
        out.append("syntax: " + (", ".join(res["syntax"]) or "-"))
        out.append("note: 'unknown' means not researched yet - NOT unsupported.")
        return "\n".join(out)

    out.append(f"{res['id']} - {res['title']}")
    if res.get("description"):
        out.append(res["description"].strip())

    if k == "capability":
        for e, info in res["engines"].items():
            if isinstance(info, dict):
                ev = f"  [evidence: {', '.join(info['evidence'])}]" if info["evidence"] else ""
                applies = f"  ({info['applies']})" if info["applies"] else ""
                out.append(f"{e} {info['version']}: {info['status']}{applies}{ev}")
                out += _bullets(info["notes"])
            else:
                for st in info:
                    out.append(f"{e} {st['range']}: {st['status']}")
                    out += _bullets(st["notes"])
        if any(isinstance(i, dict) and i["status"] == "unknown" for i in res["engines"].values()):
            out.append("note: 'unknown' means not researched yet - NOT unsupported.")

    elif k == "query":
        if res["parameters"]:
            out.append("parameters: " + ", ".join(f":{p['name']} ({p['type']})" for p in res["parameters"]))
            out.append(f"placeholders: {res['placeholders']}")
        out.append(f"result columns (order: {res['result'].get('order', '-')}):")
        for c in res["result"]["columns"]:
            extra = f" one of {c['enum']}" if "enum" in c else ""
            desc = f" - {c['description']}" if c.get("description") else ""
            out.append(f"  {c['name']}: {c['type']}{'' if c['nullable'] else ' NOT NULL'}{extra}{desc}")
        if "variant" in res:
            v = res["variant"]
            if v is None:
                out.append("NO VARIANT for this engine/version (gap).")
                out += _bullets(res["gaps"])
            else:
                out.append(f"variant: {v['file']} ({v['applies']})")
                out += _bullets(v["notes"])
                out.append("sql:")
                out.append(v["sql"].rstrip())
        else:
            out.append("variants:")
            out += [f"  {v['engine']} {v['applies']}: {v['file']}" for v in res["variants"]]
            if res["gaps"]:
                out.append("gaps:")
                out += _bullets(res["gaps"])

    elif k == "operation":
        out.append("parameters: " + ", ".join(f"{p['name']} ({p['kind']})" for p in res["parameters"]))
        out.append("identifier parameters must be quoted per the engine's lexical spec before substitution.")
        if "implementation" in res:
            impl = res["implementation"]
            if impl is None:
                out.append("no implementation for this engine/version (unknown).")
            else:
                out.append(f"{impl['engine']} {impl['version']}: {impl['status']} ({impl['applies']}),"
                           f" method: {impl.get('method', 'template')}")
                for key in ("template", "protocol_call"):
                    if key in impl:
                        out.append(f"{key}: {impl[key]}")
                if "steps" in impl:
                    out.append("steps:")
                    out += _bullets(impl["steps"])
                if "requires" in impl:
                    out.append("requires: " + ", ".join(impl["requires"]))
                if "transactional" in impl:
                    out.append(f"transactional (can be rolled back): {impl['transactional']}")
                for key in ("caveats", "notes"):
                    if impl.get(key):
                        out.append(f"{key}:")
                        out += _bullets(impl[key])
        else:
            for e, impls in res["implementations"].items():
                for i in impls:
                    out.append(f"{e} {i['range']}: {i['status']} ({i['method']})"
                               + (f"\n  template: {i['template']}" if i["template"] else ""))

    elif k == "syntax":
        if "grammars" in res:
            out += [f"  {e}: {g['file']}" + (f" (describes {g['since']}+)" if g["since"] else "")
                    for e, g in res["grammars"].items()]
            out.append("use --engine (and --version) to see the grammar.")
        else:
            ver = res["version"] or "all versions (annotated)"
            out.append(f"{res['engine']} {ver}, start rule: {res['start']}")
            out += _bullets(res["notes"])
            out.append(f"built-ins: {res['builtins']}")
            out.append("ebnf:")
            out.append(res["ebnf"].rstrip())
            if res.get("examples"):
                out.append("examples:")
                out += [f"  {ex['expect']:<14} {ex['sql']}" for ex in res["examples"]]
            if "check" in res:
                c = res["check"]
                out.append(f"check: grammar {'ACCEPTS' if c['grammar_accepts'] else 'REJECTS'}: {c['sql']}")
                out.append(f"  ({c['hint']})")

    else:  # engine / lexical / protocol: the document itself
        out = [yaml.safe_dump(res["document"], sort_keys=False, allow_unicode=True, width=110).rstrip()]
    return "\n".join(out)
