"""Schema validation and cross-reference checks."""

from __future__ import annotations

import fnmatch
import re
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from .ebnf import GrammarError
from .specs import KINDS, Specs, load_yaml
from .syntax import load_grammar, offline_check

BASE = "https://db-specs.invalid/schemas/"


def _registry(root: Path) -> tuple[Registry, dict[str, dict]]:
    schemas = {}
    resources = []
    for path in sorted((root / "schemas").glob("*.schema.json")):
        schema = json.loads(path.read_text(encoding="utf-8"))
        schemas[path.name.removesuffix(".schema.json")] = schema
        resources.append((schema["$id"], Resource.from_contents(schema)))
    return Registry().with_resources(resources), schemas


def validate(specs: Specs) -> list[str]:
    errors: list[str] = []
    registry, schemas = _registry(specs.root)

    # 1. JSON schema
    for directory, kind in KINDS.items():
        validator = Draft202012Validator(schemas[kind], registry=registry, format_checker=FormatChecker())
        for doc_id, doc in specs.docs[kind].items():
            rel = specs.path(kind, doc_id).relative_to(specs.root)
            for err in sorted(validator.iter_errors(doc), key=lambda e: list(e.path)):
                loc = "/".join(str(p) for p in err.path) or "<root>"
                errors.append(f"{rel}: {loc}: {err.message}")

    if errors:
        return errors  # cross refs assume valid structure

    # 2. ids unique per kind and matching the file location
    for kind in ("capability", "operation", "query", "syntax"):
        for doc_id in specs.docs[kind]:
            path = specs.path(kind, doc_id)
            rel = path.relative_to(specs.root)
            if kind in ("query", "syntax"):
                expected = ".".join(rel.parent.parts[1:])
            else:
                expected = ".".join(rel.with_suffix("").parts[1:])
            if doc_id != expected:
                errors.append(f"{rel}: id '{doc_id}' should be '{expected}' (derived from path)")
    for kind in ("engine", "protocol", "lexical"):
        for doc_id in specs.docs[kind]:
            path = specs.path(kind, doc_id)
            if path.stem != doc_id:
                errors.append(f"{path.relative_to(specs.root)}: id '{doc_id}' should match file name")

    engines = specs.docs["engine"]

    def check_engine(rel, eid):
        if eid not in engines:
            errors.append(f"{rel}: unknown engine '{eid}'")

    # 3. cross references
    for eid, eng in engines.items():
        rel = specs.path("engine", eid).relative_to(specs.root)
        for prof in eng["protocols"]:
            proto = specs.docs["protocol"].get(prof["id"])
            if proto is None:
                errors.append(f"{rel}: unknown protocol '{prof['id']}'")
                continue
            codes = {t["code"] for t in proto.get("type_codes", [])}
            flags = {f["name"] for f in proto.get("column_flags", [])}
            mapped = {m["type"] for m in prof.get("type_mapping", [])}
            for m in prof.get("type_mapping", []):
                if m["code"] not in codes:
                    errors.append(f"{rel}: {prof['id']} type_mapping {m['type']}: code {m['code']} not in protocols/{prof['id']}.yaml")
                for f in m.get("flags", []):
                    if f not in flags:
                        errors.append(f"{rel}: {prof['id']} type_mapping {m['type']}: unknown flag {f}")
            for col, spec in prof.get("type_probe", {}).get("columns", {}).items():
                for t in spec.split("|"):
                    if t in mapped:
                        continue
                    errors.append(f"{rel}: {prof['id']} type_probe column {col}: type {t} has no type_mapping")
        if eng["lexical"] not in specs.docs["lexical"]:
            errors.append(f"{rel}: unknown lexical spec '{eng['lexical']}'")
        if "extends" in eng and eng["extends"].split("@")[0] == eid:
            errors.append(f"{rel}: engine cannot extend itself")

    for lid, lex in specs.docs["lexical"].items():
        for emb in lex.get("embedded_languages", []):
            if emb["syntax"] not in specs.docs["syntax"]:
                errors.append(f"{specs.path('lexical', lid).relative_to(specs.root)}: unknown syntax '{emb['syntax']}'")
        kq = lex.get("keywords", {}).get("query")
        if kq and kq not in specs.docs["query"]:
            errors.append(f"{specs.path('lexical', lid).relative_to(specs.root)}: unknown query '{kq}'")
        if "extends" in eng:
            check_engine(rel, eng["extends"].split("@")[0])

    for kind, key in (("capability", "support"), ("operation", "implementations")):
        for doc_id, doc in specs.docs[kind].items():
            rel = specs.path(kind, doc_id).relative_to(specs.root)
            for eid in doc[key]:
                check_engine(rel, eid)
            for probe in doc.get("probes", []):
                for eid in probe["engines"]:
                    check_engine(rel, eid)
            for r in doc.get("related", []):
                if r not in specs.docs[kind]:
                    errors.append(f"{rel}: related '{r}' not found")

    for doc_id, q in specs.docs["query"].items():
        path = specs.path("query", doc_id)
        rel = path.relative_to(specs.root)
        for var in q["variants"]:
            check_engine(rel, var["engine"])
            if not (path.parent / var["file"]).is_file():
                errors.append(f"{rel}: variant file '{var['file']}' missing")
            pnames = {p["name"] for p in q.get("parameters", [])}
            for name in var.get("inline_parameters", {}):
                if name not in pnames:
                    errors.append(f"{rel}: {var['file']}: inline parameter '{name}' is not a query parameter")
            if "transform" in var:
                cols = [c["name"] for c in q["result"]["columns"]]
                if list(var["transform"]) != cols:
                    errors.append(f"{rel}: {var['file']}: transform must list the contract columns in order {cols}")
                for name, rule in var["transform"].items():
                    if "param" in rule and rule["param"] not in pnames:
                        errors.append(f"{rel}: {var['file']}: transform {name}: unknown parameter '{rule['param']}'")
                    if len({"map", "equals", "contains"} & set(rule)) > 1:
                        errors.append(f"{rel}: {var['file']}: transform {name}: map/equals/contains are exclusive")
            elif "extra_columns" in var:
                errors.append(f"{rel}: {var['file']}: extra_columns need a transform")

    for doc_id, syn in specs.docs["syntax"].items():
        rel = specs.path("syntax", doc_id).relative_to(specs.root)
        parse_ok = True
        for eid, g in syn["grammars"].items():
            check_engine(rel, eid)
            if eid not in engines:
                parse_ok = False
                continue
            try:
                grammar = load_grammar(specs, doc_id, eid)
            except FileNotFoundError:
                errors.append(f"{rel}: grammar file '{g['file']}' missing")
                parse_ok = False
                continue
            except GrammarError as exc:
                errors.append(f"{rel}: {g['file']}: {exc}")
                parse_ok = False
                continue
            if g["start"] not in grammar.rules:
                errors.append(f"{rel}: {g['file']}: start rule '{g['start']}' not defined")
                parse_ok = False
            for name in sorted(grammar.undefined()):
                errors.append(f"{rel}: {g['file']}: rule '{name}' referenced but not defined")
                parse_ok = False
        for i, ex in enumerate(syn["examples"]):
            for eid in ex["engines"]:
                if eid not in syn["grammars"]:
                    errors.append(f"{rel}: example {i} names engine '{eid}' without a grammar")
                    parse_ok = False
        if parse_ok:
            errors += [f"{rel}: {p}" for p in offline_check(specs, doc_id)]

    for doc_id, kw in specs.docs["keywords"].items():
        path = specs.path("keywords", doc_id)
        rel = path.relative_to(specs.root)
        check_engine(rel, kw["engine"])
        if path.parent.name != kw["engine"] or path.stem != kw["version"]:
            errors.append(f"{rel}: must be keywords/{kw['engine']}/{kw['version']}.yaml")
        if not kw["complete"] and kw.get("nonreserved"):
            errors.append(f"{rel}: incomplete lists carry reserved words only")

    roadmap = specs.root / "roadmap.yaml"
    if roadmap.is_file():
        rm = load_yaml(roadmap)
        validator = Draft202012Validator(schemas["roadmap"], registry=registry, format_checker=FormatChecker())
        for err in validator.iter_errors(rm):
            errors.append(f"roadmap.yaml: {'/'.join(str(p) for p in err.path) or '<root>'}: {err.message}")
        kinds = {"capability": "capability", "query": "query", "operation": "operation",
                 "syntax": "syntax", "engine": "engine"}
        seen = set()
        for item in rm.get("items", []):
            if item["id"] in seen:
                errors.append(f"roadmap.yaml: {item['id']} listed twice")
            seen.add(item["id"])
            for eid in item.get("engines", []):
                check_engine("roadmap.yaml", eid)
            kind = kinds.get(item["kind"])
            if kind and item["id"] in specs.docs[kind]:
                errors.append(f"roadmap.yaml: {item['id']} exists now - remove it from the roadmap")

    for doc_id, q in specs.docs["query"].items():
        for eid in q.get("not_applicable", {}):
            check_engine(specs.path("query", doc_id).relative_to(specs.root), eid)
    for doc_id, syn in specs.docs["syntax"].items():
        for eid, g in syn["grammars"].items():
            if g.get("lexical") and g["lexical"] not in specs.docs["lexical"]:
                errors.append(f"{specs.path('syntax', doc_id).relative_to(specs.root)}: unknown lexical '{g['lexical']}'")
        for eid in syn.get("not_applicable", {}):
            check_engine(specs.path("syntax", doc_id).relative_to(specs.root), eid)
            if eid in syn["grammars"]:
                errors.append(f"{specs.path('syntax', doc_id).relative_to(specs.root)}: {eid} has a grammar and is not_applicable")

    # inventories: every item classified, every reference valid, no stale rules
    from . import inventory as inv
    from .keywords import stored_files
    keyword_files = stored_files()
    scopes = {d["engine"]: d for d in specs.docs["scope"].values()}
    roadmap_ids = {i["id"] for i in load_yaml(specs.root / "roadmap.yaml").get("items", [])}
    used_patterns: dict[str, set[tuple[int, int]]] = {}
    winning_patterns: dict[str, set[tuple[int, int]]] = {}
    compiled_patterns: dict[str, list] = {}
    seen_ids: dict[str, set[str]] = {}
    for doc in specs.docs["inventory"].values():
        engine = doc["engine"]
        rel = f"inventory/{engine}/{doc['version']}.yaml"
        check_engine(rel, engine)
        scope = scopes.get(engine)
        if scope is None:
            errors.append(f"{rel}: no scope/{engine}.yaml classifies this inventory")
            continue
        result = inv.classify(doc, scope, keyword_files.get(engine, {}).get(doc["version"]))
        missing = [i for i, r in result.items() if r is None]
        if missing:
            errors.append(f"scope/{engine}.yaml: {len(missing)} item(s) of {rel} unclassified, e.g. "
                          + "; ".join(missing[:5]))
        used = used_patterns.setdefault(engine, set())
        won = winning_patterns.setdefault(engine, set())
        compiled = compiled_patterns.setdefault(engine, [
            (n, k, re.compile(fnmatch.translate(pat)).match)
            for n, rule in enumerate(scope["rules"]) for k, pat in enumerate(rule["match"])])
        seen = seen_ids.setdefault(engine, set())  # most items repeat in every version: check each id once
        for item in doc["items"]:
            if item["id"] in seen:
                continue
            seen.add(item["id"])
            first = None
            for n, k, match in compiled:
                if match(item["id"]):
                    used.add((n, k))
                    if first is None or first == n:
                        first = n
                        won.add((n, k))
    for engine, used in used_patterns.items():  # a pattern must match an item of at least one inventory
        for n, rule in enumerate(scopes[engine]["rules"]):
            for k, pat in enumerate(rule["match"]):
                if (n, k) not in used:
                    errors.append(f"scope/{engine}.yaml: rule {n} pattern {pat!r} matches no inventory item")
                elif (n, k) not in winning_patterns[engine]:  # first match wins: the pattern never decides anything
                    errors.append(f"scope/{engine}.yaml: rule {n} pattern {pat!r} is shadowed - every item it matches "
                                  "is classified by an earlier rule")
    for engine, scope in scopes.items():
        for n, rule in enumerate(scope["rules"]):
            for ref in rule.get("specs", []):
                problem = inv.spec_applies(specs, ref, engine)
                if problem:
                    errors.append(f"scope/{engine}.yaml: rule {n}: {problem}")
            if rule.get("roadmap") and rule["roadmap"] not in roadmap_ids:
                errors.append(f"scope/{engine}.yaml: rule {n}: roadmap item '{rule['roadmap']}' not found")

    for doc_id, t in specs.docs["test"].items():
        rel = specs.path("test", doc_id).relative_to(specs.root)
        for eid in t["engines"]:
            check_engine(rel, eid)
        for step in t["steps"]:
            if "query" in step and step["query"] not in specs.docs["query"]:
                errors.append(f"{rel}: unknown query '{step['query']}'")
            if "operation" in step and step["operation"] not in specs.docs["operation"]:
                errors.append(f"{rel}: unknown operation '{step['operation']}'")

    return errors
